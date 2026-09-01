"""On-demand trusted HostRunner used by the remote ``awf-agent`` command."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_workflow.runtime.artifact import (
    PostflightContract,
    validate_postflight_paths,
    validate_secret_observation,
)
from agent_workflow.runtime.workspace import (
    WorkspaceSpec,
    bind_environment,
    import_workspace_delta,
    prepare_workspace,
    serialize_workspace_delta,
)

from .contracts import (
    ContractError,
    ImplementationResult,
    RoleBinding,
    TaskProposal,
    TaskSpec,
    one_json_object,
)
from .executor import JobReceipt, JobSpec, ReceiptStatus


class HostError(RuntimeError):
    """The trusted HostRunner denied or failed one exact Job."""


_MAX_PROVIDER_EVENTS = 1024 * 1024


def extract_opencode_result(raw: bytes) -> ImplementationResult:
    """Extract one typed result from OpenCode's native NDJSON text events."""
    text_parts: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = one_json_object(line)
        except ContractError as exc:
            raise HostError("OpenCode emitted an invalid native JSON event") from exc
        if event.get("type") != "text":
            continue
        part = event.get("part")
        if (
            not isinstance(part, dict)
            or part.get("type") != "text"
            or not isinstance(part.get("text"), str)
        ):
            raise HostError("OpenCode emitted an invalid native text event")
        text_parts.append(part["text"])
    if not text_parts:
        raise HostError("OpenCode emitted no native text Result")
    try:
        return ImplementationResult.from_dict(one_json_object("".join(text_parts).encode("utf-8")))
    except ContractError as exc:
        raise HostError("OpenCode native text was not one typed ImplementationResult") from exc


@dataclass(frozen=True, slots=True)
class HostConfig:
    source_repo: str
    push_remote: str
    state_dir: str
    provider_binary: str = "opencode"
    provider_args: tuple[str, ...] = ()
    provider_model: str = ""

    @classmethod
    def load(cls) -> HostConfig:
        config_path = os.environ.get("AWF_AGENT_CONFIG", "")
        if not config_path:
            config_path = str(Path.home() / ".config" / "agent-workflow" / "agent.json")
        try:
            value = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HostError("awf-agent config is unavailable") from exc
        if not isinstance(value, dict) or set(value) != {
            "source_repo",
            "push_remote",
            "state_dir",
            "provider_binary",
            "provider_args",
            "provider_model",
        }:
            raise HostError("awf-agent config fields are invalid")
        if not isinstance(value["provider_args"], list) or not all(
            isinstance(item, str) and item for item in value["provider_args"]
        ):
            raise HostError("awf-agent provider_args are invalid")
        value["provider_args"] = tuple(value["provider_args"])
        return cls(**value)


def _run(
    argv: list[str],
    *,
    cwd: Path,
    input_bytes: bytes | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            shell=False,
            env=environment,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise HostError(f"trusted process could not start: {argv[0]}") from exc


def _git(cwd: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    completed = _run(["git", *args], cwd=cwd, input_bytes=input_bytes)
    if completed.returncode != 0:
        raise HostError(completed.stderr.decode("utf-8", errors="replace")[:4096])
    return completed.stdout


def _model_environment() -> tuple[tuple[str, str], ...]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "NO_PROXY",
        "OPENCODE_CONFIG_DIR",
        "PATH",
        "PATHEXT",
        "PI_CODING_AGENT_DIR",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
        "XDG_CONFIG_HOME",
    }
    values = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    values["PYTHONIOENCODING"] = "utf-8"
    return bind_environment(values)


def _task_from_dict(value: object) -> TaskSpec:
    if not isinstance(value, dict) or set(value) != {
        "task_id",
        "ordinal",
        "repository",
        "base_ref",
        "base_sha",
        "task_ref",
        "proposal",
        "roles",
    }:
        raise HostError("JobSpec Task fields are invalid")
    try:
        return TaskSpec(
            task_id=value["task_id"],
            ordinal=value["ordinal"],
            repository=value["repository"],
            base_ref=value["base_ref"],
            base_sha=value["base_sha"],
            task_ref=value["task_ref"],
            proposal=TaskProposal.from_dict(value["proposal"]),
            roles=tuple(RoleBinding(**binding) for binding in value["roles"]),
        )
    except (TypeError, ValueError) as exc:
        raise HostError("JobSpec Task is invalid") from exc


def parse_job(raw: bytes) -> JobSpec:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostError("JobSpec is not JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "job_id",
        "operation_id",
        "task",
        "reviewed_head_sha",
        "rework_count",
    }:
        raise HostError("JobSpec fields are invalid")
    return JobSpec(
        job_id=value["job_id"],
        operation_id=value["operation_id"],
        task=_task_from_dict(value["task"]),
        reviewed_head_sha=value["reviewed_head_sha"],
        rework_count=value["rework_count"],
    )


class HostRunner:
    def __init__(self, config: HostConfig) -> None:
        self.config = config
        self.state = Path(config.state_dir).resolve()

    def inspect(self, job_id: str) -> JobReceipt:
        path = self._receipt_path(job_id)
        if not path.is_file():
            return JobReceipt(job_id, "", ReceiptStatus.NOT_FOUND)
        return JobReceipt.from_bytes(path.read_bytes())

    def execute(self, job: JobSpec) -> JobReceipt:
        current = self.inspect(job.job_id)
        if current.status != ReceiptStatus.NOT_FOUND:
            if current.request_sha256 != job.request_sha256:
                raise HostError("stable job ID has a conflicting request hash")
            return current
        running = JobReceipt(job.job_id, job.request_sha256, ReceiptStatus.RUNNING)
        self._write(running)
        try:
            terminal = self._execute(job)
        except Exception as exc:
            terminal = JobReceipt(
                job.job_id,
                job.request_sha256,
                ReceiptStatus.TERMINAL,
                diagnostics=str(exc)[:4096],
            )
        self._write(terminal)
        return terminal

    def _execute(self, job: JobSpec) -> JobReceipt:
        task = job.task
        expected = job.reviewed_head_sha or task.base_sha
        source = Path(self.config.source_repo).resolve()
        if (
            _git(source, "rev-parse", "--verify", f"{expected}^{{commit}}").decode().strip()
            != expected
        ):
            raise HostError("source repository lacks the exact dispatched head")
        environment = _model_environment()
        work_root = self.state / "workspaces"
        work_root.mkdir(parents=True, exist_ok=True)
        prepared = prepare_workspace(
            WorkspaceSpec(str(source), expected, str(work_root), "model-", environment)
        )
        model_workspace = Path(prepared.path)
        try:
            implementation, diagnostic = self._invoke_model(job, model_workspace)
            if implementation.status != "completed":
                raise HostError(f"Coder blocked: {implementation.summary}")
            delta = serialize_workspace_delta(str(model_workspace), environment)
            return self._publish(job, delta, implementation, diagnostic)
        finally:
            shutil.rmtree(model_workspace, ignore_errors=True)

    def _invoke_model(self, job: JobSpec, workspace: Path) -> tuple[ImplementationResult, Path]:
        task = job.task
        prompt = {
            "role": "coder",
            "task": task.proposal.brief,
            "change_paths": list(task.proposal.change_paths),
            "acceptance_criteria": list(task.proposal.acceptance_criteria),
            "rework_count": job.rework_count,
            "reviewed_head_sha": job.reviewed_head_sha,
            "result_contract": {
                "status": "completed | blocked",
                "summary": "string",
                "diagnostics": "string",
            },
            "instruction": "Edit only the allowed paths, then return exactly one JSON object.",
        }
        argv = [
            self.config.provider_binary,
            *self.config.provider_args,
            "run",
            "--format",
            "json",
            "--pure",
            "--dir",
            str(workspace),
        ]
        if self.config.provider_model:
            argv += ["-m", self.config.provider_model]
        argv += ["--", json.dumps(prompt, ensure_ascii=False, sort_keys=True)]
        completed = _run(argv, cwd=workspace, environment=dict(_model_environment()))
        diagnostic = self._retain_events(job.job_id, completed.stdout)
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace")[:4096]
            raise HostError(f"{detail}; raw_events={diagnostic}")
        try:
            return extract_opencode_result(completed.stdout), diagnostic
        except HostError as exc:
            raise HostError(f"{exc}; raw_events={diagnostic}") from exc

    def _retain_events(self, job_id: str, raw: bytes) -> Path:
        path = self.state / "diagnostics" / f"{job_id}.ndjson"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".tmp-{os.getpid()}")
        temporary.write_bytes(raw[:_MAX_PROVIDER_EVENTS])
        os.replace(temporary, path)
        if len(raw) > _MAX_PROVIDER_EVENTS:
            raise HostError(f"OpenCode native events exceeded the bound; raw_events={path}")
        return path

    def _publish(
        self,
        job: JobSpec,
        delta: Any,
        result: ImplementationResult,
        diagnostic: Path,
    ) -> JobReceipt:
        task = job.task
        with tempfile.TemporaryDirectory(prefix="trusted-", dir=self.state) as temporary:
            trusted = Path(temporary)
            _git(trusted.parent, "clone", "--no-hardlinks", self.config.source_repo, str(trusted))
            _git(trusted, "checkout", "--detach", job.reviewed_head_sha or task.base_sha)
            _git(trusted, "switch", "-c", task.task_ref)
            tree = import_workspace_delta(delta, str(trusted), _model_environment())
            paths = tuple(
                value
                for value in _git(trusted, "diff", "--cached", "--name-only", "-z")
                .decode("utf-8")
                .split("\0")
                if value
            )
            validate_postflight_paths(
                PostflightContract(task.proposal.change_paths, task.proposal.verification_argv),
                paths,
            )
            added: list[tuple[str, str]] = []
            for path in paths:
                patch = _git(
                    trusted,
                    "diff",
                    "--cached",
                    "--no-renames",
                    "--no-textconv",
                    "--no-ext-diff",
                    "--unified=0",
                    "--",
                    path,
                ).decode("utf-8", errors="replace")
                in_hunk = False
                for line in patch.splitlines():
                    if line.startswith("@@"):
                        in_hunk = True
                    elif in_hunk and line.startswith("+"):
                        added.append((path, line[1:]))
            validate_secret_observation(tuple(added), ())
            if _run(["git", "diff", "--cached", "--check"], cwd=trusted).returncode != 0:
                raise HostError("trusted tree failed git diff --check")
            for argv in task.proposal.verification_argv:
                completed = _run(list(argv), cwd=trusted, environment=dict(_model_environment()))
                if completed.returncode != 0:
                    raise HostError(f"verification failed: {argv[0]}")
            if _git(trusted, "write-tree").decode().strip() != tree:
                raise HostError("verified trusted tree drifted from model tree")
            _git(
                trusted,
                "-c",
                "user.name=Agent Workflow",
                "-c",
                "user.email=awf@localhost",
                "commit",
                "-m",
                f"awf: {task.task_id}",
            )
            commit = _git(trusted, "rev-parse", "HEAD^{commit}").decode().strip()
            _git(trusted, "remote", "set-url", "origin", self.config.push_remote)
            _git(trusted, "push", "origin", f"HEAD:refs/heads/{task.task_ref}")
            observed = (
                _git(trusted, "ls-remote", "origin", f"refs/heads/{task.task_ref}")
                .decode()
                .split()[0]
            )
            if observed != commit:
                raise HostError("published Task ref does not match the exact verified commit")
            provenance = {
                "base_sha": job.reviewed_head_sha or task.base_sha,
                "tree_sha": tree,
                "commit_sha": commit,
                "task_ref": task.task_ref,
                "remote_head_sha": observed,
            }
            return JobReceipt(
                job.job_id,
                job.request_sha256,
                ReceiptStatus.TERMINAL,
                asdict(result),
                provenance,
                f"raw_events={diagnostic}",
            )

    def _receipt_path(self, job_id: str) -> Path:
        if (
            not job_id
            or len(job_id) > 128
            or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for character in job_id
            )
        ):
            raise HostError("job ID is invalid")
        return self.state / "jobs" / f"{job_id}.json"

    def _write(self, receipt: JobReceipt) -> None:
        path = self._receipt_path(receipt.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".tmp-{os.getpid()}")
        temporary.write_bytes(receipt.bytes())
        os.replace(temporary, path)


def _stdin() -> bytes:
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise HostError("awf-agent stdin is too large")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awf-agent")
    parser.add_argument("action", choices=("execute", "inspect"))
    args = parser.parse_args(argv)
    try:
        runner = HostRunner(HostConfig.load())
        if args.action == "execute":
            receipt = runner.execute(parse_job(_stdin()))
        else:
            value = json.loads(_stdin().decode("utf-8"))
            if not isinstance(value, dict) or set(value) != {"job_id"}:
                raise HostError("inspect input is invalid")
            receipt = runner.inspect(value["job_id"])
        sys.stdout.buffer.write(receipt.bytes())
        sys.stdout.buffer.write(b"\n")
        return 0
    except (HostError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
