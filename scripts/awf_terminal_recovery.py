#!/usr/bin/env python3
"""Authorize and execute one exact terminal-event recovery.

Normal Agent Workflow listeners must never ACK, requeue, or redispatch historical
events. This operator-only command handles the narrower case where a completed
model stage has durable checkpoint evidence but its original Agent Bus event is
terminally failed. It binds one authorization to the existing run, event,
delivery, payload, source commit, and checkpoint bytes before permitting one
same-event requeue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from awf_config import ConfigError, default_config_path, load_config, native_executable
from awf_executor import ExecutionFailure
from awf_executor import run as run_command
from awf_network import add_url_host_to_no_proxy

FORMAT = "awf.terminal-recovery-authorization.v1"
CHECKPOINT_FORMAT = "awf.recovery-checkpoint.v1"
LEDGER_FORMAT = "awf.run-ledger.v1"
SAFE_PHASES = {"model_imported", "pr_tuple_verified", "outbox_prepared"}
SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")


class RecoveryDenied(RuntimeError):
    """A fail-closed operator recovery denial."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    if path.is_symlink() or not path.is_file():
        raise RecoveryDenied(f"{label} must be a regular file")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryDenied(f"{label} is unreadable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise RecoveryDenied(f"{label} must be a JSON object")
    return value, raw


def _atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def checkpoint_path(state_root: Path, role: str, delivery_id: str) -> Path:
    digest = hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()
    return state_root / "checkpoint" / role / f"{digest}.json"


def authorization_path(state_root: Path, event_id: int) -> Path:
    return state_root / "terminal-recovery" / f"event-{event_id}.json"


def _authorization_binding(record: dict[str, object]) -> dict[str, object]:
    return {
        key: record.get(key)
        for key in (
            "format",
            "action",
            "run_id",
            "event_id",
            "role",
            "delivery_id",
            "payload_sha256",
            "source_commit",
            "reason",
            "evidence",
        )
    }


def _binding_sha256(record: dict[str, object]) -> str:
    return _sha256_bytes(_canonical(_authorization_binding(record)))


def _matching_ledger_event(
    ledger: dict[str, object],
    *,
    event_id: int,
    role: str,
    delivery_id: str,
    payload_sha256: str,
) -> None:
    events = ledger.get("events")
    if not isinstance(events, list):
        raise RecoveryDenied("run ledger events are invalid")
    matches = [
        item
        for item in events
        if isinstance(item, dict)
        and item.get("event_id") == event_id
        and item.get("role") == role
        and item.get("delivery_id") == delivery_id
        and item.get("payload_sha256") == payload_sha256
        and item.get("status") == "authorized"
    ]
    if len(matches) != 1:
        raise RecoveryDenied("run ledger does not authorize the exact terminal event")


def validate_evidence(
    *,
    state_root: Path,
    run_id: str,
    event_id: int,
    role: str,
    delivery_id: str,
    payload_sha256: str,
    source_commit: str,
) -> dict[str, object]:
    if event_id < 1 or role not in {"coder", "reviewer"}:
        raise RecoveryDenied("event identity is invalid")
    if not delivery_id.startswith("awf:") or not SHA256_RE.fullmatch(payload_sha256):
        raise RecoveryDenied("delivery identity is invalid")
    if not COMMIT_RE.fullmatch(source_commit):
        raise RecoveryDenied("source commit is invalid")

    ledger_path = state_root / "control-plane" / "runs" / run_id / "ledger.json"
    ledger, ledger_raw = _read_json(ledger_path, "run ledger")
    if ledger.get("format") != LEDGER_FORMAT or ledger.get("run_id") != run_id:
        raise RecoveryDenied("run ledger identity is invalid")
    if ledger.get("terminal_state"):
        raise RecoveryDenied("run ledger is already terminal")
    _matching_ledger_event(
        ledger,
        event_id=event_id,
        role=role,
        delivery_id=delivery_id,
        payload_sha256=payload_sha256,
    )

    path = checkpoint_path(state_root, role, delivery_id)
    checkpoint, checkpoint_raw = _read_json(path, "recovery checkpoint")
    expected = {
        "format": CHECKPOINT_FORMAT,
        "role": role,
        "input_delivery_id": delivery_id,
        "input_payload_sha256": payload_sha256,
        "source_commit": source_commit,
    }
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise RecoveryDenied("recovery checkpoint identity does not match the request")
    if checkpoint.get("phase") not in SAFE_PHASES:
        raise RecoveryDenied("recovery checkpoint has not crossed a safe completed-model boundary")
    facts = checkpoint.get("facts")
    if not isinstance(facts, dict):
        raise RecoveryDenied("recovery checkpoint facts are invalid")
    if facts.get("model_event_id") != event_id:
        raise RecoveryDenied("recovery checkpoint model event does not match")
    if not SHA256_RE.fullmatch(str(facts.get("model_manifest_sha256", ""))):
        raise RecoveryDenied("recovery checkpoint model manifest is invalid")
    report_sha256 = str(facts.get("review_report_sha256", ""))
    if role == "reviewer" and not re.fullmatch(r"[0-9a-f]{64}", report_sha256):
        raise RecoveryDenied("reviewer checkpoint is missing its trusted report hash")
    workspace = facts.get("model_workspace")
    if not isinstance(workspace, str) or not Path(workspace).is_dir():
        raise RecoveryDenied("durable model workspace is unavailable")

    return {
        "ledger_path": str(ledger_path.resolve()),
        "ledger_sha256": _sha256_bytes(ledger_raw),
        "checkpoint_path": str(path.resolve()),
        "checkpoint_sha256": _sha256_bytes(checkpoint_raw),
        "checkpoint_phase": checkpoint["phase"],
        "model_workspace": str(Path(workspace).resolve()),
        "model_manifest_sha256": facts["model_manifest_sha256"],
        "review_report_sha256": report_sha256,
    }


def prepare_authorization(
    *,
    state_root: Path,
    run_id: str,
    event_id: int,
    role: str,
    delivery_id: str,
    payload_sha256: str,
    source_commit: str,
    reason: str,
) -> Path:
    if not reason.strip() or len(reason.encode("utf-8")) > 512:
        raise RecoveryDenied("operator reason is required and must be bounded")
    evidence = validate_evidence(
        state_root=state_root,
        run_id=run_id,
        event_id=event_id,
        role=role,
        delivery_id=delivery_id,
        payload_sha256=payload_sha256,
        source_commit=source_commit,
    )
    path = authorization_path(state_root, event_id)
    record: dict[str, object] = {
        "format": FORMAT,
        "action": "requeue_same_event",
        "status": "authorized",
        "attempts": 0,
        "run_id": run_id,
        "event_id": event_id,
        "role": role,
        "delivery_id": delivery_id,
        "payload_sha256": payload_sha256,
        "source_commit": source_commit,
        "reason": reason.strip(),
        "evidence": evidence,
    }
    record["binding_sha256"] = _binding_sha256(record)
    if path.exists():
        existing, _ = _read_json(path, "terminal recovery authorization")
        comparable = {key: value for key, value in existing.items() if key != "updated_at"}
        if comparable != record:
            raise RecoveryDenied("a different terminal recovery authorization already exists")
        return path
    record["updated_at"] = time.time()
    _atomic_write(path, record)
    return path


def _load_authorization(state_root: Path, event_id: int) -> tuple[Path, dict[str, object]]:
    path = authorization_path(state_root, event_id)
    record, _ = _read_json(path, "terminal recovery authorization")
    if record.get("format") != FORMAT or record.get("event_id") != event_id:
        raise RecoveryDenied("terminal recovery authorization identity is invalid")
    if record.get("binding_sha256") != _binding_sha256(record):
        raise RecoveryDenied("terminal recovery authorization checksum is invalid")
    return path, record


def execute_requeue(*, state_root: Path, event_id: int, config_path: Path) -> Path:
    path, record = _load_authorization(state_root, event_id)
    if record.get("status") == "requeued":
        return path
    if record.get("status") != "authorized" or record.get("attempts") != 0:
        raise RecoveryDenied("terminal recovery authorization is no longer executable")

    evidence = validate_evidence(
        state_root=state_root,
        run_id=str(record["run_id"]),
        event_id=event_id,
        role=str(record["role"]),
        delivery_id=str(record["delivery_id"]),
        payload_sha256=str(record["payload_sha256"]),
        source_commit=str(record["source_commit"]),
    )
    if evidence != record.get("evidence"):
        raise RecoveryDenied("terminal recovery evidence changed after authorization")

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise RecoveryDenied(f"strict operations configuration is invalid: {exc}") from exc
    token_key = f"AWF_{str(record['role']).upper()}_TOKEN"
    token = config.get(token_key, "")
    url = config.get("AGENT_BUS_URL", "")
    if not token or not url:
        raise RecoveryDenied("terminal recovery role configuration is incomplete")

    attempting = {**record, "status": "attempting", "attempts": 1, "updated_at": time.time()}
    _atomic_write(path, attempting)
    environment = dict(os.environ)
    environment.update(
        {
            "AGENT_BUS_URL": url,
            "AGENT_BUS_TOKEN": token,
            "AGENT_BUS_AGENT": str(record["role"]),
        }
    )
    add_url_host_to_no_proxy(environment, url)
    bus = native_executable(config.get("AWF_BUS_BIN", "agent-bus"))
    try:
        result = run_command(
            [bus, "requeue", str(event_id)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            allow_shell_wrapper=True,
            secrets=(token,),
        )
    except ExecutionFailure as exc:
        ambiguous = {
            **attempting,
            "status": "ambiguous",
            "failure": exc.diagnostic.kind,
            "updated_at": time.time(),
        }
        _atomic_write(path, ambiguous)
        raise RecoveryDenied("terminal event requeue outcome is ambiguous") from exc
    if result.returncode != 0:
        ambiguous = {
            **attempting,
            "status": "ambiguous",
            "failure": f"exit-{result.returncode}",
            "updated_at": time.time(),
        }
        _atomic_write(path, ambiguous)
        raise RecoveryDenied("terminal event requeue outcome is ambiguous")
    completed = {**attempting, "status": "requeued", "updated_at": time.time()}
    _atomic_write(path, completed)
    return path


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--event-id", type=int, required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awf_terminal_recovery")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    _common(prepare)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--role", choices=("coder", "reviewer"), required=True)
    prepare.add_argument("--delivery-id", required=True)
    prepare.add_argument("--payload-sha256", required=True)
    prepare.add_argument("--source-commit", required=True)
    prepare.add_argument("--reason", required=True)
    requeue = commands.add_parser("requeue")
    _common(requeue)
    requeue.add_argument("--config", type=Path, default=default_config_path())
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            path = prepare_authorization(
                state_root=args.state_root.resolve(),
                run_id=args.run_id,
                event_id=args.event_id,
                role=args.role,
                delivery_id=args.delivery_id,
                payload_sha256=args.payload_sha256,
                source_commit=args.source_commit,
                reason=args.reason,
            )
            print(f"AUTHORIZED {path}")
        else:
            path = execute_requeue(
                state_root=args.state_root.resolve(),
                event_id=args.event_id,
                config_path=args.config.resolve(),
            )
            print(f"REQUEUED {path}")
        return 0
    except RecoveryDenied as exc:
        print(f"awf_terminal_recovery: denied: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
