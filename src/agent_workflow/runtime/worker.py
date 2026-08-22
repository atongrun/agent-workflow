"""Stage-blind execution-host boundary for fresh Runtime v2 commands."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .application import ProcessResult, ProviderLauncher, SubprocessProviderLauncher
from .artifact import (
    parse_postflight_contract,
    parse_review_report,
    postflight_result,
    validate_implementation_report,
    validate_postflight_paths,
    validate_secret_observation,
)
from .contracts import FreshRunSpec, InvocationSpec, RoleBinding, _canonical_bytes
from .ports import WorkflowStage
from .renderers import ATTACH_INPUT, render_provider_invocation
from .transport import CommandEnvelope, ResultEnvelope
from .workspace import (
    WorkspaceSpec,
    bind_environment,
    freeze_workspace,
    prepare_workspace,
    serialize_workspace_delta,
)

WORKER_JOURNAL_FORMAT = "awf.runtime-v2.worker-journal.v1"
_MAX_RESULT_BYTES = 192 * 1024


class WorkerError(RuntimeError):
    """A command cannot safely authorize a worker invocation."""


@dataclass(frozen=True, slots=True)
class PreparedWorkerCommand:
    envelope: CommandEnvelope
    run_spec: FreshRunSpec
    stage: WorkflowStage
    role: str
    authorization_sha256: str
    journal_path: Path
    journal: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WorkerResult:
    envelope: ResultEnvelope
    journal_path: Path
    replayed: bool


def _digest(value: object) -> str:
    raw = value if isinstance(value, bytes) else _canonical_bytes(value)  # type: ignore[arg-type]
    return hashlib.sha256(raw).hexdigest()


def command_authorization_sha256(
    *,
    run_spec_sha256: str,
    invocation_id: str,
    stage: WorkflowStage,
    attempt: object,
    expected_commit: object,
    input_text: object,
    role: str,
) -> str:
    """Derive rather than trust the provider authorization carried by a command."""
    return _digest(
        {
            "format": "awf.runtime-v2.remote-authorization.v1",
            "run_spec_sha256": run_spec_sha256,
            "invocation_id": invocation_id,
            "stage": stage.value,
            "attempt": attempt,
            "expected_commit": expected_commit,
            "input_sha256": _digest(str(input_text).encode("utf-8")),
            "role": role,
        }
    )


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WorkerError("worker journal is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise WorkerError("worker journal is not an object")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(8)}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_worker_command(
    *,
    envelope_bytes: bytes,
    local_binding: RoleBinding,
    state_root: str | Path,
) -> PreparedWorkerCommand:
    """Validate exact command/binding identity and durably reserve it before provider I/O."""
    envelope = CommandEnvelope.decode(envelope_bytes)
    payload = envelope.payload
    required = {
        "run_spec",
        "authorization_sha256",
        "stage",
        "attempt",
        "input_text",
        "expected_commit",
        "provider_executable",
        "provider_args",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise WorkerError("fresh worker command fields are invalid")
    spec = FreshRunSpec.from_mapping(payload["run_spec"])
    if spec.sha256 != envelope.run_spec_sha256:
        raise WorkerError("worker command RunSpec hash drifted")
    try:
        stage = WorkflowStage(payload["stage"])
    except (TypeError, ValueError) as exc:
        raise WorkerError("worker command Stage is invalid") from exc
    if stage not in {WorkflowStage.IMPLEMENT, WorkflowStage.REVIEW, WorkflowStage.REWORK}:
        raise WorkerError("worker command Stage is not remotely executable")
    role = "reviewer" if stage is WorkflowStage.REVIEW else "coder"
    expected_binding = spec.reviewer if role == "reviewer" else spec.coder
    if local_binding != expected_binding or local_binding.role != role:
        raise WorkerError("worker role/tool/model/profile/workspace binding drifted")
    if envelope.target_role != role:
        raise WorkerError("worker command target role drifted")
    authorization = command_authorization_sha256(
        run_spec_sha256=spec.sha256,
        invocation_id=envelope.target_invocation_id,
        stage=stage,
        attempt=payload["attempt"],
        expected_commit=payload["expected_commit"],
        input_text=payload["input_text"],
        role=role,
    )
    if payload["authorization_sha256"] != authorization:
        raise WorkerError("worker command authorization identity drifted")

    root = Path(state_root).expanduser().resolve()
    journal_path = (
        root
        / "runtime-v2"
        / "workers"
        / spec.run_id
        / role
        / f"{envelope.delivery_id.removeprefix('awfv2:')}.json"
    )
    command_sha256 = hashlib.sha256(envelope_bytes).hexdigest()
    if journal_path.exists():
        journal = _strict_json(journal_path.read_bytes())
        if (
            journal.get("format") != WORKER_JOURNAL_FORMAT
            or journal.get("command_sha256") != command_sha256
            or journal.get("delivery_id") != envelope.delivery_id
            or journal.get("run_spec_sha256") != spec.sha256
            or journal.get("profile_sha256") != local_binding.profile_sha256
            or journal.get("authorization_sha256") != authorization
        ):
            raise WorkerError("worker delivery identity conflicts with durable command evidence")
    else:
        journal = {
            "format": WORKER_JOURNAL_FORMAT,
            "run_spec_sha256": spec.sha256,
            "profile_sha256": local_binding.profile_sha256,
            "delivery_id": envelope.delivery_id,
            "command_sha256": command_sha256,
            "authorization_sha256": authorization,
            "launch_intent": None,
            "process": None,
            "result_envelope": None,
            "sent": False,
        }
        _atomic_json(journal_path, journal)
    return PreparedWorkerCommand(
        envelope,
        spec,
        stage,
        role,
        authorization,
        journal_path,
        journal,
    )


def _environment() -> tuple[tuple[str, str], ...]:
    allowed = {
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
        "HOME",
        "LANG",
        "LC_ALL",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "AWF_FINDING_ENABLED",
    }
    values = {key: value for key, value in os.environ.items() if key in allowed}
    values.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return bind_environment(values)


def _git(
    repo: str | Path,
    environment: tuple[tuple[str, str], ...],
    *args: str,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        env=dict(environment),
    )


def _git_text(
    repo: str | Path,
    environment: tuple[tuple[str, str], ...],
    *args: str,
) -> str:
    result = _git(repo, environment, *args)
    if result.returncode:
        raise WorkerError("worker trusted Git observation failed")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _materialize_input(invocation: InvocationSpec) -> None:
    rendered = render_provider_invocation(invocation)
    inputs = list(rendered.file_inputs)
    if invocation.provider == "opencode" and invocation.provider_args == (ATTACH_INPUT,):
        from .contracts import RenderedInputFile

        inputs.append(
            RenderedInputFile(invocation.input_path, invocation.input_text.encode("utf-8"))
        )
    for item in inputs:
        target = Path(item.path)
        if target.is_symlink():
            raise WorkerError("provider input path is redirected")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)


def _persist_stdout(invocation: InvocationSpec, result: ProcessResult) -> None:
    if invocation.role == "reviewer" and invocation.provider == "pi" and result.stdout:
        report = Path(invocation.report_path)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_bytes(result.stdout)


def _postflight_observation(
    workspace: Path,
    paths: tuple[str, ...],
    previously_tracked: frozenset[str],
    environment: tuple[tuple[str, str], ...],
) -> str:
    tracked: list[tuple[str, str]] = []
    untracked: list[tuple[str, str]] = []
    unreadable: list[str] = []
    for name in paths:
        target = workspace / name
        if name in previously_tracked:
            diff = _git(workspace, environment, "diff", "--cached", "--unified=0", "--", name)
            if diff.returncode:
                raise WorkerError("worker tracked secret observation failed")
            text = diff.stdout.decode("utf-8", errors="replace")
            tracked.extend(
                (name, line[1:])
                for line in text.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
        else:
            try:
                raw = target.read_bytes()
            except OSError:
                unreadable.append(name)
                continue
            if len(raw) > 1024 * 1024:
                unreadable.append(name)
            else:
                untracked.append((name, raw.decode("utf-8", errors="replace")))
    return validate_secret_observation(tuple(tracked), tuple(untracked), tuple(unreadable))


def _verification(
    commands: tuple[tuple[str, ...], ...],
    workspace: Path,
    environment: tuple[tuple[str, str], ...],
) -> None:
    for argv in commands:
        completed = subprocess.run(
            list(argv),
            cwd=workspace,
            env=dict(environment),
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise WorkerError("worker frozen postflight verification failed")


def execute_worker_command(
    *,
    envelope_bytes: bytes,
    local_binding: RoleBinding,
    state_root: str | Path,
    python_executable: str,
    launcher: ProviderLauncher | None = None,
) -> WorkerResult:
    """Invoke once after exact reservation, or return the same immutable durable result."""
    prepared = prepare_worker_command(
        envelope_bytes=envelope_bytes,
        local_binding=local_binding,
        state_root=state_root,
    )
    journal = prepared.journal
    if journal.get("result_envelope"):
        result = ResultEnvelope.decode(str(journal["result_envelope"]).encode("utf-8"))
        return WorkerResult(result, prepared.journal_path, True)
    if journal.get("launch_intent"):
        raise WorkerError("worker provider outcome is ambiguous; automatic replay is forbidden")

    payload = prepared.envelope.payload
    environment = _environment()
    expected_commit = str(payload["expected_commit"])
    workspace_root = (
        Path(state_root).expanduser().resolve()
        / "runtime-v2"
        / "worker-workspaces"
        / prepared.run_spec.run_id
        / prepared.role
    )
    workspace = prepare_workspace(
        WorkspaceSpec(
            local_binding.workspace,
            expected_commit,
            str(workspace_root),
            f"{prepared.envelope.target_invocation_id}-",
            environment,
        )
    )
    workspace_path = Path(workspace.path)
    card = workspace_path / prepared.run_spec.task_card
    try:
        card_sha256 = hashlib.sha256(card.read_bytes()).hexdigest()
    except OSError as exc:
        raise WorkerError("worker immutable TaskCard is unavailable") from exc
    if card_sha256 != prepared.run_spec.task_card_sha256:
        raise WorkerError("worker immutable TaskCard digest drifted")
    tracked = frozenset(_git_text(workspace.path, environment, "ls-files").splitlines())
    report = (
        prepared.run_spec.review_report
        if prepared.role == "reviewer"
        else prepared.run_spec.implementation_report
    )
    raw_args = payload["provider_args"]
    if not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args):
        raise WorkerError("worker provider_args are invalid")
    invocation = InvocationSpec(
        invocation_id=prepared.envelope.target_invocation_id,
        run_id=prepared.run_spec.run_id,
        task_id=prepared.run_spec.task_id,
        authorization_sha256=prepared.authorization_sha256,
        role=prepared.role,
        provider=local_binding.agent_tool,
        model=local_binding.model,
        executable=str(payload["provider_executable"]),
        workspace=workspace.path,
        input_path=str(
            workspace_path
            / ".awf"
            / f"runtime-input-{prepared.envelope.target_invocation_id}.md"
        ),
        input_text=str(payload["input_text"]),
        report_path=str(workspace_path / report),
        provider_args=tuple(raw_args),
        environment=environment,
    )
    rendered = render_provider_invocation(invocation)
    _materialize_input(invocation)
    journal["launch_intent"] = {
        "invocation_sha256": invocation.sha256,
        "rendered_sha256": rendered.sha256,
        "workspace_manifest_sha256": workspace.manifest_sha256,
    }
    _atomic_json(prepared.journal_path, journal)
    started = (launcher or SubprocessProviderLauncher()).start(rendered)
    journal["process"] = {"identity_sha256": started.process_identity_sha256}
    _atomic_json(prepared.journal_path, journal)
    process = started.wait()
    Path(invocation.input_path).unlink(missing_ok=True)
    _persist_stdout(invocation, process)
    if process.return_code:
        raise WorkerError("worker provider returned non-zero")

    report_path = workspace_path / report
    if prepared.role == "reviewer":
        validated = parse_review_report(report_path, report)
        result_payload: dict[str, Any] = {
            "kind": "review",
            "report": base64.b64encode(report_path.read_bytes()).decode("ascii"),
            "report_sha256": validated.artifact.sha256,
            "canonical_sha256": validated.review.canonical_sha256,
            "verdict": validated.review.verdict,
            "head": _git_text(workspace.path, environment, "rev-parse", "HEAD^{commit}"),
            "tree": _git_text(workspace.path, environment, "rev-parse", "HEAD^{tree}"),
            "process_identity_sha256": started.process_identity_sha256,
            "workspace_manifest_sha256": freeze_workspace(workspace.path, environment),
        }
    else:
        fact = validate_implementation_report(report_path, report)
        contract = parse_postflight_contract(card, python_executable)
        _verification(contract.verification_commands, workspace_path, environment)
        delta = serialize_workspace_delta(workspace.path, environment)
        raw_paths = _git(
            workspace.path, environment, "diff", "--cached", "--name-only", "-z", "HEAD"
        )
        if raw_paths.returncode:
            raise WorkerError("worker delta path observation failed")
        paths = tuple(
            item.decode("utf-8", errors="strict")
            for item in raw_paths.stdout.split(b"\0")
            if item
        )
        validate_postflight_paths(contract, paths)
        secret = _postflight_observation(workspace_path, paths, tracked, environment)
        diff_check = _git(workspace.path, environment, "diff", "--cached", "--check")
        postflight = postflight_result(paths, secret, diff_check.returncode)
        reset = _git(workspace.path, environment, "reset", "--mixed", "HEAD")
        if reset.returncode:
            raise WorkerError("worker result workspace reset failed")
        result_payload = {
            "kind": "coder",
            "report": base64.b64encode(report_path.read_bytes()).decode("ascii"),
            "report_sha256": fact.sha256,
            "postflight_sha256": postflight.observation_sha256,
            "base_tree": delta.base_tree,
            "model_tree": delta.model_tree,
            "patch": base64.b64encode(delta.patch).decode("ascii"),
            "patch_sha256": delta.patch_sha256,
            "process_identity_sha256": started.process_identity_sha256,
            "workspace_manifest_sha256": freeze_workspace(workspace.path, environment),
        }
    if len(_canonical_bytes(result_payload)) > _MAX_RESULT_BYTES:
        raise WorkerError("worker result exceeds the command/result envelope bound")
    result = ResultEnvelope.create(
        run_id=prepared.run_spec.run_id,
        task_id=prepared.run_spec.task_id,
        run_spec_sha256=prepared.run_spec.sha256,
        source_role=prepared.role,
        target_role="architect",
        route="result:awf-runtime-v2-result-v1",
        source_invocation_id=prepared.envelope.target_invocation_id,
        source_authorization_sha256=prepared.authorization_sha256,
        target_invocation_id=f"source-{prepared.envelope.target_invocation_id}",
        causation_delivery_id=prepared.envelope.delivery_id,
        payload=result_payload,
    )
    journal["result_envelope"] = result.encode().decode("utf-8")
    journal["result_sha256"] = _digest(result.encode())
    _atomic_json(prepared.journal_path, journal)
    return WorkerResult(result, prepared.journal_path, False)


def mark_worker_result_sent(path: Path, envelope: ResultEnvelope) -> None:
    journal = _strict_json(path.read_bytes())
    if journal.get("result_envelope") != envelope.encode().decode("utf-8"):
        raise WorkerError("worker sent-result identity drifted")
    journal["sent"] = True
    _atomic_json(path, journal)
