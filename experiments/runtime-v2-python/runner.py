#!/usr/bin/env python3
"""Disposable Runtime v2 Python shared-slice runner.

This is an experiment-local command surface for RTS-020. It intentionally does
not import, wrap, or select the installed ``awf`` package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


TASK_ID = "runtime-v2-rts-020-python-shared-slice"
BRANCH = f"codex/{TASK_ID}"
ALLOWED_DELTA = ["result.txt"]
FORMAT = "awf.runtime-v2-python-slice.v1"
SAFE_CHILD_ENV_KEYS = ("LANG", "LC_ALL", "PATH", "PYTHONIOENCODING", "SYSTEMROOT", "WINDIR")


class StateError(RuntimeError):
    def __init__(self, outcome: str, legal_next_action: str, source: str) -> None:
        super().__init__(source)
        self.outcome = outcome
        self.legal_next_action = legal_next_action
        self.source = source


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"format": FORMAT, "payload": payload, "checksum": _digest(payload)}
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _loads_json_object(
    text: str, path: Path, outcome: str, legal_next_action: str
) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except Exception as exc:  # noqa: BLE001 - corrupt local state must fail closed.
        raise StateError(
            outcome,
            legal_next_action,
            f"cannot read {path.name}: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise StateError(outcome, legal_next_action, f"{path.name} is not a JSON object")
    return value


def _read_envelope(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - missing/corrupt state must fail closed.
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"cannot read {path.name}: {exc}",
        ) from exc
    envelope = _loads_json_object(
        text, path, "DENY_BEFORE_PROVIDER", "preserve files and diagnose exact run identity"
    )
    payload = envelope.get("payload")
    if (
        envelope.get("format") != FORMAT
        or not isinstance(payload, dict)
        or envelope.get("checksum") != _digest(payload)
    ):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"checksum mismatch in {path.name}",
        )
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - provider artifacts are trusted-input checked here.
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            f"cannot read artifact {path.name}: {exc}",
        ) from exc
    return _loads_json_object(
        text,
        path,
        "HANDLER_FAILURE_NO_ACK",
        "record failure/ambiguity and preserve the same delivery evidence",
    )


def _child_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in SAFE_CHILD_ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _git_stdout(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _configure_repo(repo: Path) -> None:
    _git(repo, "config", "user.email", "runtime-v2-python@example.invalid")
    _git(repo, "config", "user.name", "Runtime V2 Python Slice")
    remotes = _git_stdout(repo, "remote")
    for remote in [line for line in remotes.splitlines() if line.strip()]:
        _git(repo, "remote", "remove", remote)


def _clone_without_remote(source: Path, destination: Path, commit: str) -> None:
    if destination.exists():
        return
    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(source), str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(destination, "checkout", "--detach", commit)
    _configure_repo(destination)


def _tree(repo: Path) -> str:
    return _git_stdout(repo, "rev-parse", "HEAD^{tree}")


def _head(repo: Path) -> str:
    return _git_stdout(repo, "rev-parse", "HEAD")


def _status_paths(repo: Path) -> list[str]:
    output = _git_stdout(repo, "status", "--porcelain")
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        paths.append(line[3:])
    return paths


def _copy_allowed_file(source: Path, destination: Path, relative: str) -> None:
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / relative, target)


def _run_dir(state_root: Path, run_id: str) -> Path:
    return state_root / run_id


def _spec_path(run_dir: Path) -> Path:
    return run_dir / "runspec.json"


def _run_path(run_dir: Path) -> Path:
    return run_dir / "run.json"


def _journal_path(run_dir: Path, invocation_id: str) -> Path:
    return run_dir / "invocations" / f"{invocation_id}.json"


def _counter_path(run_dir: Path) -> Path:
    return run_dir / "provider-counts.json"


def _has_state_files(run_dir: Path, excluded: set[str] | None = None) -> bool:
    excluded = excluded or set()
    if not run_dir.exists():
        return False
    return any(child.name not in excluded for child in run_dir.iterdir())


def _counter(run_dir: Path) -> dict[str, Any]:
    path = _counter_path(run_dir)
    if not path.exists():
        return {"implement": 0, "review": 0, "calls": []}
    try:
        return _loads_json_object(
            path.read_text(encoding="utf-8"),
            path,
            "EXTERNAL_OBSERVATION_UNKNOWN",
            "inspect exact provider-count evidence",
        )
    except StateError:
        return {"implement": "corrupt", "review": "corrupt", "calls": []}


def _compiled_spec(repo: Path, provider: Path, run_id: str) -> dict[str, Any]:
    source_head = _head(repo)
    return {
        "task_id": TASK_ID,
        "branch": BRANCH,
        "run_id": run_id,
        "repository": str(repo.resolve()),
        "source_head": source_head,
        "source_tree": _tree(repo),
        "allowed_delta": ALLOWED_DELTA,
        "provider_command": [sys.executable, str(provider.resolve())],
        "synthetic_external": [
            "provider intelligence",
            "delivery observation",
            "downstream intent",
            "timestamps",
            "GitHub-shaped fields",
        ],
    }


def _ensure_spec(run_dir: Path, repo: Path, provider: Path, run_id: str) -> dict[str, Any]:
    compiled = _compiled_spec(repo, provider, run_id)
    path = _spec_path(run_dir)
    if not path.exists():
        if _has_state_files(run_dir):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "RunSpec missing while other run state exists",
            )
        _atomic_write(path, compiled)
        return compiled
    existing = _read_envelope(path)
    if _digest(existing) != _digest(compiled):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve the run and diagnose the exact immutable contract binding",
            "compiled RunSpec drift",
        )
    return existing


def _expected_journal_paths(run_dir: Path, invocation_id: str) -> tuple[Path, Path]:
    if invocation_id == "implement-1":
        return (
            run_dir / "workspaces" / "implement-1",
            run_dir / "artifacts" / "implementation-report.json",
        )
    if invocation_id == "review-1":
        return (run_dir / "trusted-repo", run_dir / "artifacts" / "review-report.json")
    raise StateError(
        "DENY_BEFORE_PROVIDER",
        "preserve files and diagnose exact run identity",
        f"unknown invocation identity {invocation_id}",
    )


def _validate_run_identity(run: dict[str, Any], spec: dict[str, Any]) -> None:
    expected = {
        "run_id": spec["run_id"],
        "task_id": spec["task_id"],
        "spec_digest": _digest(spec),
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"RunStore {key} drift",
            )


def _expected_authorizations(phase: str) -> list[dict[str, str]] | None:
    implement = {"invocation_id": "implement-1", "role": "implement"}
    review = {"invocation_id": "review-1", "role": "review"}
    if phase in {"initialized", "prepared_without_authorization"}:
        return []
    if phase in {
        "implement_authorized",
        "implement_launch_intent",
        "implement_started",
        "implement_result",
        "implement_committed",
        "review_handoff_intent",
    }:
        return [implement]
    if phase in {"review_authorized", "review_result", "completed"}:
        return [implement, review]
    return None


def _validate_authorizations(run: dict[str, Any]) -> None:
    authorizations = run.get("authorizations")
    if not isinstance(authorizations, list):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "RunStore authorizations are not a list",
        )
    exact = _expected_authorizations(str(run.get("phase")))
    if exact is not None and authorizations != exact:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "RunStore authorization set drift",
        )
    seen: set[tuple[str, str]] = set()
    allowed = {("implement-1", "implement"), ("review-1", "review")}
    for item in authorizations:
        if not isinstance(item, dict):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "RunStore authorization entry is invalid",
            )
        pair = (str(item.get("invocation_id")), str(item.get("role")))
        if pair not in allowed or pair in seen:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "RunStore authorization identity drift",
            )
        seen.add(pair)


def _validate_run_phase_bindings(run: dict[str, Any], spec: dict[str, Any]) -> None:
    _validate_run_identity(run, spec)
    _validate_authorizations(run)


def _validate_journal_identity(
    payload: dict[str, Any],
    spec: dict[str, Any],
    run_dir: Path,
    invocation_id: str,
    role: str,
) -> None:
    workspace, artifact = _expected_journal_paths(run_dir, invocation_id)
    expected = {
        "invocation_id": invocation_id,
        "role": role,
        "spec_digest": _digest(spec),
        "workspace": str(workspace),
        "artifact": str(artifact),
        "provider_command_digest": _digest(spec["provider_command"]),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                f"InvocationJournal {invocation_id} {key} drift",
            )
    _validate_journal_state(payload, spec, run_dir)


def _provider_argv(
    spec: dict[str, Any],
    run_dir: Path,
    payload: dict[str, Any],
    role: str,
    mode: str,
) -> list[str]:
    return [
        *spec["provider_command"],
        "--role",
        role,
        "--workspace",
        payload["workspace"],
        "--artifact",
        payload["artifact"],
        "--counter",
        str(_counter_path(run_dir)),
        "--mode",
        mode,
    ]


def _validate_launch_binding(payload: dict[str, Any], spec: dict[str, Any], run_dir: Path) -> None:
    launch_intent = payload.get("launch_intent")
    if not isinstance(launch_intent, dict):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "InvocationJournal launch intent missing",
        )
    mode = launch_intent.get("mode")
    if not isinstance(mode, str):
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "InvocationJournal launch mode missing",
        )
    expected = _provider_argv(spec, run_dir, payload, str(payload["role"]), mode)
    if launch_intent.get("argv") != expected:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "InvocationJournal launch argv drift",
        )


def _validate_journal_state(payload: dict[str, Any], spec: dict[str, Any], run_dir: Path) -> None:
    state = payload.get("state")
    if state not in {"prepared", "launch_intent", "started", "result", "validated"}:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            f"InvocationJournal invalid state {state}",
        )
    has_launch = payload.get("launch_intent") is not None
    has_started = payload.get("started") is not None
    has_result = payload.get("result") is not None
    has_validated = payload.get("validated") is not None
    expected_presence = {
        "prepared": (False, False, False, False),
        "launch_intent": (True, False, False, False),
        "started": (True, True, False, False),
        "result": (True, True, True, False),
        "validated": (True, True, True, True),
    }
    if (has_launch, has_started, has_result, has_validated) != expected_presence[state]:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "InvocationJournal phase consistency drift",
        )
    if has_launch:
        _validate_launch_binding(payload, spec, run_dir)


def _load_run(run_dir: Path) -> dict[str, Any] | None:
    path = _run_path(run_dir)
    if not path.exists():
        return None
    return _read_envelope(path)


class RunStore:
    """The single writer for workflow phase, authorization, handoff, and terminal facts."""

    def __init__(self, run_dir: Path, spec: dict[str, Any]) -> None:
        self.run_dir = run_dir
        self.spec = spec
        self.path = _run_path(run_dir)

    def load(self) -> dict[str, Any]:
        current = _load_run(self.run_dir)
        if current is not None:
            _validate_run_phase_bindings(current, self.spec)
            return current
        if _has_state_files(self.run_dir, excluded={"runspec.json"}):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "RunStore missing while other run state exists",
            )
        payload = {
            "run_id": self.spec["run_id"],
            "task_id": self.spec["task_id"],
            "spec_digest": _digest(self.spec),
            "phase": "initialized",
            "authorizations": [],
            "handoff_intent": None,
            "terminal": None,
            "trusted_commit": None,
            "trusted_tree": None,
            "stop": None,
        }
        self.save(payload)
        return payload

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        _validate_run_phase_bindings(payload, self.spec)
        _atomic_write(self.path, payload)
        return payload

    def authorize(self, payload: dict[str, Any], invocation_id: str, role: str) -> dict[str, Any]:
        _validate_run_phase_bindings(payload, self.spec)
        journal = _read_envelope(_journal_path(self.run_dir, invocation_id))
        _validate_journal_identity(journal, self.spec, self.run_dir, invocation_id, role)
        if journal.get("state") != "prepared":
            raise StateError(
                "OWNER_DECISION_REQUIRED",
                "preserve the consumed authorization/budget and deny automatic provider replay",
                "journal is not prepared before authorization",
            )
        payload = dict(payload)
        authorizations = list(payload.get("authorizations", []))
        authorizations.append({"invocation_id": invocation_id, "role": role})
        payload["authorizations"] = authorizations
        payload["phase"] = f"{role}_authorized"
        return self.save(payload)

    def phase(self, payload: dict[str, Any], phase: str, **facts: Any) -> dict[str, Any]:
        _validate_run_phase_bindings(payload, self.spec)
        payload = dict(payload)
        payload["phase"] = phase
        payload.update(facts)
        return self.save(payload)


class InvocationJournal:
    """The single per-invocation API for process intent, observations, and results."""

    def __init__(self, run_dir: Path, spec: dict[str, Any], invocation_id: str, role: str) -> None:
        self.run_dir = run_dir
        self.spec = spec
        self.invocation_id = invocation_id
        self.role = role
        self.path = _journal_path(run_dir, invocation_id)

    def read(self) -> dict[str, Any]:
        payload = _read_envelope(self.path)
        _validate_journal_identity(payload, self.spec, self.run_dir, self.invocation_id, self.role)
        return payload

    def prepare(self, workspace: Path, artifact: Path) -> dict[str, Any]:
        payload = {
            "invocation_id": self.invocation_id,
            "role": self.role,
            "spec_digest": _digest(self.spec),
            "workspace": str(workspace),
            "artifact": str(artifact),
            "provider_command_digest": _digest(self.spec["provider_command"]),
            "state": "prepared",
            "prepared_is_launch_intent": False,
            "launch_intent": None,
            "started": None,
            "result": None,
            "validated": None,
        }
        _atomic_write(self.path, payload)
        return payload

    def update(self, **facts: Any) -> dict[str, Any]:
        payload = dict(self.read())
        payload.update(facts)
        _atomic_write(self.path, payload)
        return payload

    def launch(self, command: list[str], mode: str) -> dict[str, Any]:
        provider_command = self.spec["provider_command"]
        if _digest(command[: len(provider_command)]) != _digest(provider_command):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "provider command binding drift",
            )
        return self.update(state="launch_intent", launch_intent={"argv": command, "mode": mode})

    def started(self, pid: int) -> dict[str, Any]:
        return self.update(state="started", started={"pid": pid})

    def result(self, returncode: int) -> dict[str, Any]:
        return self.update(state="result", result={"returncode": returncode})

    def validated(self, artifact_sha256: str) -> dict[str, Any]:
        return self.update(state="validated", validated={"artifact_sha256": artifact_sha256})


def _invocation(
    run_dir: Path, spec: dict[str, Any], invocation_id: str, role: str
) -> InvocationJournal:
    return InvocationJournal(run_dir, spec, invocation_id, role)


def _invoke_provider(
    journal: InvocationJournal,
    spec: dict[str, Any],
    role: str,
    mode: str = "normal",
) -> dict[str, Any]:
    payload = journal.read()
    command = _provider_argv(spec, journal.run_dir, payload, role, mode)
    journal.launch(command, mode)
    process = subprocess.Popen(command, cwd=payload["workspace"], env=_child_env())
    journal.started(process.pid)
    return_code = process.wait()
    return journal.result(return_code)


def _prepare_implement(run_dir: Path, spec: dict[str, Any]) -> InvocationJournal:
    journal = _invocation(run_dir, spec, "implement-1", "implement")
    if journal.path.exists():
        return journal
    workspace = run_dir / "workspaces" / "implement-1"
    _clone_without_remote(Path(spec["repository"]), workspace, spec["source_head"])
    journal.prepare(workspace, run_dir / "artifacts" / "implementation-report.json")
    return journal


def _prepare_review(run_dir: Path, spec: dict[str, Any]) -> InvocationJournal:
    journal = _invocation(run_dir, spec, "review-1", "review")
    if journal.path.exists():
        return journal
    workspace = run_dir / "trusted-repo"
    journal.prepare(workspace, run_dir / "artifacts" / "review-report.json")
    return journal


def _validate_implementation(run_dir: Path, spec: dict[str, Any]) -> tuple[Path, str]:
    workspace, artifact_sha = _validate_implementation_evidence(run_dir, spec, None, False)
    journal = _invocation(run_dir, spec, "implement-1", "implement")
    journal.validated(artifact_sha)
    return workspace, artifact_sha


def _validate_implementation_evidence(
    run_dir: Path,
    spec: dict[str, Any],
    run: dict[str, Any] | None,
    require_validated: bool,
) -> tuple[Path, str]:
    journal = _invocation(run_dir, spec, "implement-1", "implement")
    payload = journal.read()
    if payload.get("state") not in {"result", "validated"}:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "implement journal lacks durable result",
        )
    if require_validated and payload.get("state") != "validated":
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "implement journal is not validated",
        )
    result = payload.get("result") or {}
    if result.get("returncode") != 0:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "implement provider returned non-zero",
        )
    artifact = Path(payload["artifact"])
    report = _read_json(artifact)
    if report.get("artifact_type") != "ImplementationReport":
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "missing valid ImplementationReport",
        )
    changed = report.get("changed_files")
    if changed != ALLOWED_DELTA:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "implementation changed files outside the allowlist",
        )
    workspace = Path(payload["workspace"])
    if sorted(_status_paths(workspace)) != ALLOWED_DELTA:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "workspace delta does not match allowed paths",
        )
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    validated = payload.get("validated")
    if validated is not None and validated.get("artifact_sha256") != artifact_sha:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "implement journal artifact hash drift",
        )
    if run is not None and run.get("implementation_report_sha256") != artifact_sha:
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "implementation report hash drift",
        )
    return workspace, artifact_sha


def _import_and_commit(run_dir: Path, spec: dict[str, Any], workspace: Path) -> tuple[str, str]:
    trusted = run_dir / "trusted-repo"
    _clone_without_remote(Path(spec["repository"]), trusted, spec["source_head"])
    for relative in ALLOWED_DELTA:
        _copy_allowed_file(workspace, trusted, relative)
    if sorted(_status_paths(trusted)) != ALLOWED_DELTA:
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve exact workspace/evidence for owner decision",
            "trusted import delta does not match allowed paths",
        )
    _git(trusted, "add", *ALLOWED_DELTA)
    _git(trusted, "commit", "-m", "Apply RTS-020 disposable implementation")
    return _head(trusted), _tree(trusted)


def _validate_review(run_dir: Path, spec: dict[str, Any]) -> str:
    artifact_sha = _validate_review_evidence(run_dir, spec, None, False)
    journal = _invocation(run_dir, spec, "review-1", "review")
    journal.validated(artifact_sha)
    return artifact_sha


def _validate_review_evidence(
    run_dir: Path,
    spec: dict[str, Any],
    run: dict[str, Any] | None,
    require_validated: bool,
) -> str:
    journal = _invocation(run_dir, spec, "review-1", "review")
    payload = journal.read()
    if payload.get("state") not in {"result", "validated"}:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "review journal lacks durable result",
        )
    if require_validated and payload.get("state") != "validated":
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "review journal is not validated",
        )
    result = payload.get("result") or {}
    if result.get("returncode") != 0:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "review provider returned non-zero",
        )
    artifact = Path(payload["artifact"])
    report = _read_json(artifact)
    if report.get("artifact_type") != "ReviewReport" or report.get("verdict") != "PASS":
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "missing normalized PASS ReviewReport",
        )
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    validated = payload.get("validated")
    if validated is not None and validated.get("artifact_sha256") != artifact_sha:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "review journal artifact hash drift",
        )
    if run is not None and run.get("review_report_sha256") != artifact_sha:
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "review report hash drift",
        )
    return artifact_sha


def _verify_trusted_identity(run_dir: Path, run: dict[str, Any]) -> None:
    trusted = run_dir / "trusted-repo"
    if not trusted.exists() or _head(trusted) != run.get("trusted_commit"):
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "trusted HEAD drift",
        )
    if _tree(trusted) != run.get("trusted_tree"):
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "trusted tree drift",
        )
    if _status_paths(trusted):
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "trusted workspace dirty",
        )


def _validate_implement_result_phase(
    run_dir: Path, spec: dict[str, Any], run: dict[str, Any]
) -> None:
    _validate_run_phase_bindings(run, spec)
    _validate_implementation_evidence(run_dir, spec, None, False)


def _validate_implement_committed_phase(
    run_dir: Path, spec: dict[str, Any], run: dict[str, Any]
) -> None:
    _validate_run_phase_bindings(run, spec)
    _validate_implementation_evidence(run_dir, spec, run, True)
    _verify_trusted_identity(run_dir, run)


def _validate_review_result_phase(run_dir: Path, spec: dict[str, Any], run: dict[str, Any]) -> None:
    _validate_run_phase_bindings(run, spec)
    _validate_implement_committed_phase(run_dir, spec, run)
    _validate_review_evidence(run_dir, spec, None, False)


def _validate_terminal_phase(run_dir: Path, spec: dict[str, Any], run: dict[str, Any]) -> None:
    _validate_run_phase_bindings(run, spec)
    _validate_implement_committed_phase(run_dir, spec, run)
    _validate_review_evidence(run_dir, spec, run, True)
    terminal = run.get("terminal")
    if not isinstance(terminal, dict) or terminal.get("outcome") != "completed":
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "terminal evidence drift",
        )


def _mark_failure(store: RunStore, run: dict[str, Any], error: StateError) -> dict[str, Any]:
    return store.phase(
        run,
        "blocked",
        outcome=error.outcome,
        blocker={"owner": "owner", "source": error.source},
        legal_next_action=error.legal_next_action,
        terminal=None,
    )


def _error_status(run_dir: Path, run_id: str, error: StateError) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "task_id": TASK_ID,
        "phase": "state_drift",
        "outcome": error.outcome,
        "blocker": {"owner": "owner", "source": error.source},
        "provider_invocation_observation": {
            "counts": _counter(run_dir),
            "journals": _journal_observations(run_dir),
        },
        "terminal": None,
        "legal_next_action": error.legal_next_action,
        "prohibited_actions": ["provider start", "mutation", "guessed repair"],
    }


def _should_persist_failure(error: StateError) -> bool:
    return error.outcome == "HANDLER_FAILURE_NO_ACK"


def _continue(
    run_dir: Path, spec: dict[str, Any], run: dict[str, Any], mode: str = "normal"
) -> dict[str, Any]:
    store = RunStore(run_dir, spec)
    while True:
        phase = run["phase"]
        if phase == "initialized":
            journal = _prepare_implement(run_dir, spec)
            run = store.authorize(run, journal.invocation_id, "implement")
        elif phase == "implement_authorized":
            journal = _invocation(run_dir, spec, "implement-1", "implement")
            if not journal.path.exists():
                raise StateError(
                    "OWNER_DECISION_REQUIRED",
                    "preserve the consumed authorization/budget and deny automatic provider replay",
                    "authorized invocation is missing its prepared journal",
                )
            payload = journal.read()
            if payload.get("state") == "prepared":
                _invoke_provider(journal, spec, "implement", mode=mode)
                run = store.phase(run, "implement_result")
            elif payload.get("state") in {"launch_intent", "started"}:
                raise StateError(
                    "AMBIGUOUS_NO_REPLAY",
                    "preserve exact process/workspace/evidence for owner decision",
                    "implement launch/start has no recoverable result",
                )
            elif payload.get("state") in {"result", "validated"}:
                run = store.phase(run, "implement_result")
            else:
                raise StateError(
                    "OWNER_DECISION_REQUIRED",
                    "preserve program and state evidence; use only a previously proven "
                    "compatible program",
                    f"unknown implement journal state {payload.get('state')}",
                )
        elif phase == "implement_launch_intent":
            _invocation(run_dir, spec, "implement-1", "implement").read()
            raise StateError(
                "AMBIGUOUS_NO_REPLAY",
                "preserve exact process/workspace/evidence for owner decision",
                "launch intent has no recoverable result",
            )
        elif phase == "implement_started":
            _invocation(run_dir, spec, "implement-1", "implement").read()
            raise StateError(
                "AMBIGUOUS_NO_REPLAY",
                "preserve exact process/workspace/evidence for owner decision",
                "process start has no durable result",
            )
        elif phase == "implement_result":
            workspace, artifact_sha = _validate_implementation(run_dir, spec)
            commit, tree = _import_and_commit(run_dir, spec, workspace)
            run = store.phase(
                run,
                "implement_committed",
                implementation_report_sha256=artifact_sha,
                trusted_commit=commit,
                trusted_tree=tree,
            )
        elif phase == "implement_committed":
            _validate_implement_committed_phase(run_dir, spec, run)
            run = store.phase(
                run,
                "review_handoff_intent",
                handoff_intent={
                    "kind": "synthetic-local-review",
                    "trusted_commit": run["trusted_commit"],
                    "trusted_tree": run["trusted_tree"],
                },
            )
        elif phase == "review_handoff_intent":
            journal = _prepare_review(run_dir, spec)
            run = store.authorize(run, journal.invocation_id, "review")
        elif phase == "review_authorized":
            journal = _invocation(run_dir, spec, "review-1", "review")
            payload = journal.read()
            if payload.get("state") == "prepared":
                _invoke_provider(journal, spec, "review")
                run = store.phase(run, "review_result")
            elif payload.get("state") in {"launch_intent", "started"}:
                raise StateError(
                    "AMBIGUOUS_NO_REPLAY",
                    "preserve exact process/workspace/evidence for owner decision",
                    "review launch/start has no recoverable result",
                )
            elif payload.get("state") in {"result", "validated"}:
                run = store.phase(run, "review_result")
            else:
                raise StateError(
                    "OWNER_DECISION_REQUIRED",
                    "preserve program and state evidence; use only a previously proven "
                    "compatible program",
                    f"unknown review journal state {payload.get('state')}",
                )
        elif phase == "review_result":
            _validate_review_result_phase(run_dir, spec, run)
            review_sha = _validate_review(run_dir, spec)
            _verify_trusted_identity(run_dir, run)
            run = store.phase(
                run,
                "completed",
                review_report_sha256=review_sha,
                terminal={
                    "outcome": "completed",
                    "synthetic_external": True,
                    "unequal_lifecycle_evidence": True,
                },
            )
            return run
        elif phase == "completed":
            _validate_terminal_phase(run_dir, spec, run)
            return run
        elif phase in {"blocked", "stopped"}:
            return run
        elif phase == "prepared_without_authorization":
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "commit exact RunStore authorization before launch",
                "prepared journal is not launch intent",
            )
        else:
            raise StateError(
                "OWNER_DECISION_REQUIRED",
                "preserve program and state evidence; use only a previously proven compatible "
                "program",
                f"unknown phase {phase}",
            )


def _create_store(run_dir: Path, spec: dict[str, Any]) -> tuple[RunStore, dict[str, Any]]:
    store = RunStore(run_dir, spec)
    return store, store.load()


def _inject_fault(run_dir: Path, spec: dict[str, Any], fault: str) -> dict[str, Any]:
    store, run = _create_store(run_dir, spec)
    if run["phase"] != "initialized":
        return run
    if fault == "auth_prepared_only":
        _prepare_implement(run_dir, spec)
        return store.phase(run, "prepared_without_authorization")
    if fault == "auth_without_journal":
        return store.phase(
            run,
            "implement_authorized",
            authorizations=[{"invocation_id": "implement-1", "role": "implement"}],
        )
    if fault in {"auth_authorized_prepared", "duplicate_pre_start"}:
        journal = _prepare_implement(run_dir, spec)
        return store.authorize(run, journal.invocation_id, "implement")
    if fault == "auth_launch_no_result":
        journal = _prepare_implement(run_dir, spec)
        run = store.authorize(run, journal.invocation_id, "implement")
        journal.launch(
            _provider_argv(spec, run_dir, journal.read(), "implement", "normal"), "normal"
        )
        return store.phase(run, "implement_launch_intent")
    if fault == "start_result":
        journal = _prepare_implement(run_dir, spec)
        run = store.authorize(run, journal.invocation_id, "implement")
        journal.launch(
            _provider_argv(spec, run_dir, journal.read(), "implement", "normal"), "normal"
        )
        journal.started(424242)
        return store.phase(run, "implement_started")
    if fault == "review_launch_no_result":
        run = _continue_until_review_authorized(run_dir, spec, run)
        journal = _invocation(run_dir, spec, "review-1", "review")
        journal.launch(_provider_argv(spec, run_dir, journal.read(), "review", "normal"), "normal")
        return run
    if fault == "review_started_no_result":
        run = _continue_until_review_authorized(run_dir, spec, run)
        journal = _invocation(run_dir, spec, "review-1", "review")
        journal.launch(_provider_argv(spec, run_dir, journal.read(), "review", "normal"), "normal")
        journal.started(525252)
        return run
    if fault == "review_result_recover":
        run = _continue_until_review_authorized(run_dir, spec, run)
        journal = _invocation(run_dir, spec, "review-1", "review")
        _invoke_provider(journal, spec, "review")
        return run
    if fault == "artifact":
        return _continue(run_dir, spec, run, mode="invalid-artifact")
    if fault == "result_validate":
        journal = _prepare_implement(run_dir, spec)
        run = store.authorize(run, journal.invocation_id, "implement")
        _invoke_provider(journal, spec, "implement")
        return store.phase(run, "implement_result")
    if fault == "effect_intent":
        journal = _prepare_implement(run_dir, spec)
        run = store.authorize(run, journal.invocation_id, "implement")
        _invoke_provider(journal, spec, "implement")
        run = store.phase(run, "implement_result")
        workspace, artifact_sha = _validate_implementation(run_dir, spec)
        commit, tree = _import_and_commit(run_dir, spec, workspace)
        return store.phase(
            run,
            "implement_committed",
            implementation_report_sha256=artifact_sha,
            trusted_commit=commit,
            trusted_tree=tree,
        )
    if fault == "duplicate_terminal":
        return _continue(run_dir, spec, run)
    if fault == "state_drift":
        _atomic_write(_run_path(run_dir), run)
        path = _spec_path(run_dir)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["source_head"] = "0" * 40
        path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return run
    if fault == "runspec_rechecksum_drift":
        drifted = dict(spec)
        drifted["source_head"] = "0" * 40
        _atomic_write(_spec_path(run_dir), drifted)
        return run
    if fault == "journal_rechecksum_drift":
        journal = _prepare_implement(run_dir, spec)
        run = store.authorize(run, journal.invocation_id, "implement")
        drifted = dict(_read_envelope(journal.path))
        drifted["role"] = "review"
        _atomic_write(journal.path, drifted)
        return run
    if fault == "git_drift":
        run = _continue_until_review_result(run_dir, spec, run)
        trusted = run_dir / "trusted-repo"
        (trusted / "result.txt").write_text("drifted after review\n", encoding="utf-8")
        _git(trusted, "add", "result.txt")
        _git(trusted, "commit", "-m", "Inject trusted git drift")
        return run
    raise SystemExit(f"unknown fault injection: {fault}")


def _continue_until_review_authorized(
    run_dir: Path, spec: dict[str, Any], run: dict[str, Any]
) -> dict[str, Any]:
    store = RunStore(run_dir, spec)
    while run["phase"] != "review_authorized":
        if run["phase"] == "initialized":
            journal = _prepare_implement(run_dir, spec)
            run = store.authorize(run, journal.invocation_id, "implement")
        elif run["phase"] == "implement_authorized":
            journal = _invocation(run_dir, spec, "implement-1", "implement")
            _invoke_provider(journal, spec, "implement")
            run = store.phase(run, "implement_result")
        elif run["phase"] == "implement_result":
            workspace, artifact_sha = _validate_implementation(run_dir, spec)
            commit, tree = _import_and_commit(run_dir, spec, workspace)
            run = store.phase(
                run,
                "implement_committed",
                implementation_report_sha256=artifact_sha,
                trusted_commit=commit,
                trusted_tree=tree,
            )
        elif run["phase"] == "implement_committed":
            run = store.phase(
                run,
                "review_handoff_intent",
                handoff_intent={
                    "kind": "synthetic-local-review",
                    "trusted_commit": run["trusted_commit"],
                    "trusted_tree": run["trusted_tree"],
                },
            )
        elif run["phase"] == "review_handoff_intent":
            journal = _prepare_review(run_dir, spec)
            run = store.authorize(run, journal.invocation_id, "review")
        else:
            return run
    return run


def _continue_until_review_result(
    run_dir: Path, spec: dict[str, Any], run: dict[str, Any]
) -> dict[str, Any]:
    store = RunStore(run_dir, spec)
    while run["phase"] != "review_result":
        if run["phase"] == "initialized":
            journal = _prepare_implement(run_dir, spec)
            run = store.authorize(run, journal.invocation_id, "implement")
        elif run["phase"] == "implement_authorized":
            journal = _invocation(run_dir, spec, "implement-1", "implement")
            _invoke_provider(journal, spec, "implement")
            run = store.phase(run, "implement_result")
        elif run["phase"] == "implement_result":
            workspace, artifact_sha = _validate_implementation(run_dir, spec)
            commit, tree = _import_and_commit(run_dir, spec, workspace)
            run = store.phase(
                run,
                "implement_committed",
                implementation_report_sha256=artifact_sha,
                trusted_commit=commit,
                trusted_tree=tree,
            )
        elif run["phase"] == "implement_committed":
            run = store.phase(
                run,
                "review_handoff_intent",
                handoff_intent={
                    "kind": "synthetic-local-review",
                    "trusted_commit": run["trusted_commit"],
                    "trusted_tree": run["trusted_tree"],
                },
            )
        elif run["phase"] == "review_handoff_intent":
            journal = _prepare_review(run_dir, spec)
            run = store.authorize(run, journal.invocation_id, "review")
        elif run["phase"] == "review_authorized":
            journal = _invocation(run_dir, spec, "review-1", "review")
            _invoke_provider(journal, spec, "review")
            run = store.phase(run, "review_result")
        else:
            return run
    return run


def _journal_observations(run_dir: Path) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    invocations = run_dir / "invocations"
    if not invocations.exists():
        return observations
    for path in sorted(invocations.glob("*.json")):
        try:
            payload = _read_envelope(path)
        except StateError:
            observations[path.stem] = {"state": "corrupt"}
            continue
        observations[path.stem] = {
            "role": payload.get("role"),
            "state": payload.get("state"),
            "has_launch_intent": bool(payload.get("launch_intent")),
            "has_started": bool(payload.get("started")),
            "has_result": bool(payload.get("result")),
            "has_validated": bool(payload.get("validated")),
        }
    return observations


def _assert_no_active_or_invalid_journals(run_dir: Path, spec: dict[str, Any]) -> None:
    invocations = run_dir / "invocations"
    if not invocations.exists():
        return
    roles = {"implement-1": "implement", "review-1": "review"}
    for path in sorted(invocations.glob("*.json")):
        invocation_id = path.stem
        role = roles.get(invocation_id)
        if role is None:
            raise StateError(
                "DENY_BEFORE_MUTATION",
                "preserve process/lease records and diagnose exact identity",
                f"unknown journal {invocation_id}",
            )
        try:
            payload = _read_envelope(path)
            _validate_journal_identity(payload, spec, run_dir, invocation_id, role)
        except StateError as exc:
            raise StateError(
                "DENY_BEFORE_MUTATION",
                "preserve process/lease records and diagnose exact identity",
                exc.source,
            ) from exc
        if payload.get("state") in {"launch_intent", "started"}:
            raise StateError(
                "DENY_BEFORE_MUTATION",
                "preserve process/lease records and diagnose exact identity",
                f"active invocation {invocation_id}",
            )


def _status_from_run(run_dir: Path, run_id: str, run: dict[str, Any] | None) -> dict[str, Any]:
    if run is None:
        return {
            "run_id": run_id,
            "task_id": TASK_ID,
            "phase": "unknown",
            "outcome": "EXTERNAL_OBSERVATION_UNKNOWN",
            "blocker": {"owner": "status", "source": "run state is absent"},
            "provider_invocation_observation": {},
            "terminal": None,
            "legal_next_action": "create a separately authorized run or inspect the state root",
            "prohibited_actions": ["status mutation", "provider start", "guessed repair"],
        }
    phase = run.get("phase")
    outcome = run.get("outcome")
    legal_next_action = run.get("legal_next_action")
    blocker = run.get("blocker")
    if phase == "completed":
        try:
            spec = _read_envelope(_spec_path(run_dir))
            _validate_terminal_phase(run_dir, spec, run)
            outcome = "TERMINAL_IDEMPOTENT"
            legal_next_action = "status or exact stop only"
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            legal_next_action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "stopped":
        outcome = "TERMINAL_IDEMPOTENT"
        legal_next_action = "none"
        blocker = None
    elif phase == "prepared_without_authorization":
        outcome = "DENY_BEFORE_PROVIDER"
        legal_next_action = "commit exact RunStore authorization before launch"
        blocker = {"owner": "runstore", "source": "prepared journal is not launch intent"}
    elif phase in {"implement_authorized", "review_authorized"}:
        invocation_id = "implement-1" if phase == "implement_authorized" else "review-1"
        role = "implement" if phase == "implement_authorized" else "review"
        try:
            spec = _read_envelope(_spec_path(run_dir))
            journal = _read_envelope(_journal_path(run_dir, invocation_id))
            _validate_journal_identity(journal, spec, run_dir, invocation_id, role)
            if journal.get("state") == "prepared":
                outcome = "SAFE_CONTINUE"
                legal_next_action = "invoke once after exact gates and journal revalidation"
                blocker = None
            elif journal.get("state") in {"result", "validated"}:
                outcome = "SAFE_CONTINUE"
                legal_next_action = (
                    "skip provider and run frozen postflight against exact durable workspace"
                    if role == "implement"
                    else "skip provider and validate the durable review result"
                )
                blocker = None
            else:
                outcome = "AMBIGUOUS_NO_REPLAY"
                legal_next_action = "preserve exact process/workspace/evidence for owner decision"
                blocker = {"owner": "journal", "source": "authorized invocation is past prepared"}
        except StateError as exc:
            if "InvocationJournal" in exc.source:
                outcome = exc.outcome
                legal_next_action = exc.legal_next_action
            else:
                outcome = "OWNER_DECISION_REQUIRED"
                legal_next_action = (
                    "preserve the consumed authorization/budget and deny automatic provider replay"
                )
            blocker = {"owner": "owner", "source": exc.source}
    elif phase in {"implement_launch_intent", "implement_started"}:
        try:
            spec = _read_envelope(_spec_path(run_dir))
            _invocation(run_dir, spec, "implement-1", "implement").read()
            outcome = "AMBIGUOUS_NO_REPLAY"
            legal_next_action = "preserve exact process/workspace/evidence for owner decision"
            blocker = {"owner": "journal", "source": "launch/start lacks recoverable result"}
        except StateError as exc:
            outcome = exc.outcome
            legal_next_action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "implement_result":
        try:
            spec = _read_envelope(_spec_path(run_dir))
            _validate_implement_result_phase(run_dir, spec, run)
            outcome = "SAFE_CONTINUE"
            legal_next_action = (
                "skip provider and run frozen postflight against exact durable workspace"
            )
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            legal_next_action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "implement_committed":
        try:
            spec = _read_envelope(_spec_path(run_dir))
            _validate_implement_committed_phase(run_dir, spec, run)
            outcome = "SAFE_CONTINUE"
            legal_next_action = "revalidate exact effects and persist one local review intent"
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            legal_next_action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "review_result":
        try:
            spec = _read_envelope(_spec_path(run_dir))
            _validate_review_result_phase(run_dir, spec, run)
            outcome = "SAFE_CONTINUE"
            legal_next_action = "revalidate exact Git/workspace identity and persist terminal"
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            legal_next_action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "blocked":
        outcome = outcome or "OWNER_DECISION_REQUIRED"
        legal_next_action = legal_next_action or "preserve evidence for owner decision"
        blocker = blocker or {"owner": "owner", "source": "blocked"}
    terminal_fact = run.get("terminal")
    if blocker is not None and outcome in {"DENY_BEFORE_PROVIDER", "DENY_BEFORE_MUTATION"}:
        terminal_fact = None
    return {
        "run_id": run_id,
        "task_id": run.get("task_id", TASK_ID),
        "spec_digest": run.get("spec_digest"),
        "phase": phase,
        "outcome": outcome,
        "blocker": blocker,
        "provider_invocation_observation": {
            "counts": _counter(run_dir),
            "journals": _journal_observations(run_dir),
        },
        "terminal": terminal_fact,
        "legal_next_action": legal_next_action,
        "prohibited_actions": [
            "status mutation",
            "guessed repair",
            "provider replay without exact durable authorization",
            "remote Git/GitHub/ACK/lifecycle claim",
        ],
    }


def _status(state_root: Path, run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(state_root, run_id)
    try:
        spec = None
        spec_exists = _spec_path(run_dir).exists()
        run_exists = _run_path(run_dir).exists()
        if not spec_exists and _has_state_files(run_dir):
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "RunSpec missing while other run state exists",
            )
        if spec_exists and not run_exists:
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "RunStore missing while RunSpec exists",
            )
        if spec_exists:
            spec = _read_envelope(_spec_path(run_dir))
        run = _load_run(run_dir)
        if run is not None and spec is not None:
            _validate_run_phase_bindings(run, spec)
        return _status_from_run(run_dir, run_id, run)
    except StateError as exc:
        return {
            "run_id": run_id,
            "task_id": TASK_ID,
            "phase": "state_drift",
            "outcome": exc.outcome,
            "blocker": {"owner": "owner", "source": exc.source},
            "provider_invocation_observation": {
                "counts": _counter(run_dir),
                "journals": _journal_observations(run_dir),
            },
            "terminal": None,
            "legal_next_action": exc.legal_next_action,
            "prohibited_actions": ["provider start", "mutation", "guessed repair"],
        }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    state_root = Path(args.state_root)
    repo = Path(args.repo)
    provider = Path(args.provider)
    run_dir = _run_dir(state_root, args.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        spec = _ensure_spec(run_dir, repo, provider, args.run_id)
        existing = _load_run(run_dir)
        if existing is not None:
            _validate_run_identity(existing, spec)
        if existing and existing.get("phase") in {"completed", "blocked", "stopped"}:
            return _status_from_run(run_dir, args.run_id, existing)
        if args.fault:
            try:
                run = _inject_fault(run_dir, spec, args.fault)
            except StateError as exc:
                if not _should_persist_failure(exc):
                    return _error_status(run_dir, args.run_id, exc)
                store = RunStore(run_dir, spec)
                run = _load_run(run_dir) or store.load()
                run = _mark_failure(store, run, exc)
        else:
            store, run = _create_store(run_dir, spec)
            try:
                run = _continue(run_dir, spec, run)
            except StateError as exc:
                if not _should_persist_failure(exc):
                    return _error_status(run_dir, args.run_id, exc)
                run = _mark_failure(store, run, exc)
        return _status(Path(args.state_root), args.run_id)
    except StateError as exc:
        return _error_status(run_dir, args.run_id, exc)


def _stop(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = _run_dir(Path(args.state_root), args.run_id)
    try:
        spec = _read_envelope(_spec_path(run_dir))
        run = _load_run(run_dir)
        if run is None:
            raise StateError(
                "EXTERNAL_OBSERVATION_UNKNOWN",
                "inspect the exact experiment state root",
                "run is absent",
            )
        _validate_run_identity(run, spec)
        _assert_no_active_or_invalid_journals(run_dir, spec)
        stopped = dict(run)
        stopped["phase"] = "stopped"
        stopped["stop"] = {
            "kind": "exact-local-stop",
            "unequal_lifecycle_evidence": True,
            "native_manager": False,
        }
        stopped["terminal"] = run.get("terminal") or {"outcome": "stopped"}
        _atomic_write(_run_path(run_dir), stopped)
        return _status_from_run(run_dir, args.run_id, stopped)
    except StateError as exc:
        return {
            "run_id": args.run_id,
            "task_id": TASK_ID,
            "phase": "stop_denied",
            "outcome": exc.outcome,
            "blocker": {"owner": "owner", "source": exc.source},
            "provider_invocation_observation": {
                "counts": _counter(run_dir),
                "journals": _journal_observations(run_dir),
            },
            "terminal": None,
            "legal_next_action": exc.legal_next_action,
            "prohibited_actions": [
                "cross-run stop",
                "service-manager claim",
                "guessed process kill",
            ],
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--state-root", required=True)
    run.add_argument("--repo", required=True)
    run.add_argument("--provider", required=True)
    run.add_argument("--run-id", default=TASK_ID)
    run.add_argument("--fault", default="")
    status = sub.add_parser("status")
    status.add_argument("--state-root", required=True)
    status.add_argument("--run-id", default=TASK_ID)
    stop = sub.add_parser("stop")
    stop.add_argument("--state-root", required=True)
    stop.add_argument("--run-id", default=TASK_ID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        result = _run(args)
    elif args.command == "status":
        result = _status(Path(args.state_root), args.run_id)
    else:
        result = _stop(args)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
