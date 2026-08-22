"""Stage-blind execution-host boundary for fresh Runtime v2 commands."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import FreshRunSpec, RoleBinding, _canonical_bytes
from .ports import WorkflowStage
from .transport import CommandEnvelope

WORKER_JOURNAL_FORMAT = "awf.runtime-v2.worker-journal.v1"


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
