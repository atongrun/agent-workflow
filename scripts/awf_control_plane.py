#!/usr/bin/env python3
"""Durable operations-surface control plane for Agent Workflow.

This module deliberately lives outside ``src/agent_workflow``.  It records the
small amount of mutable run state that a trusted runner needs, while the stable
Workflow core remains stateless and provider-neutral.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

LEDGER_FORMAT = "awf.run-ledger.v1"
PACKET_FORMAT = "awf.context-packet.v1"
AUTHORITY_FORMAT = "awf.authority-manifest.v1"
MAX_PACKET_BYTES = 32 * 1024
TERMINAL_STATES = {"completed", "failed", "blocked", "cancelled", "rejected"}
SAFE_OPERATIONS = {"diagnose", "endpoint_discovery", "listener_restart"}
FORBIDDEN_OPERATIONS = {
    "credentials",
    "destructive",
    "historical_event",
    "ack",
    "requeue",
    "redispatch",
    "ci_bypass",
    "trust_gate_bypass",
}
DEFAULT_ROUTES = {
    "task:awf-impl": ["coder"],
    "task:awf-impl-v2": ["coder"],
    "task:awf-impl-v3": ["coder"],
    "task:awf-review": ["reviewer"],
    "task:awf-review-v2": ["reviewer"],
    "task:awf-review-v3": ["reviewer"],
    "task:awf-rework": ["coder"],
    "task:awf-rework-v2": ["coder"],
    "task:awf-rework-v3": ["coder"],
}


class ControlPlaneDenied(RuntimeError):
    """A trusted preflight denial that must happen before model launch."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    with temp.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    """Serialize gate transitions; the lock is never part of the packet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl

        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    except ImportError:
        pass
    # Windows fallback: bounded exclusive-create lock.  A stale lock is removed
    # only after a bounded age, never as a general cleanup operation.
    for _ in range(200):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - path.stat().st_mtime > 60:
                path.unlink()
            else:
                time.sleep(0.01)
    else:
        raise ControlPlaneDenied("control-plane lock timeout")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def default_state_root() -> Path:
    if os.name == "nt":
        value = os.environ.get("LOCALAPPDATA")
        if not value:
            raise ControlPlaneDenied("LOCALAPPDATA is required for the control plane")
        return Path(value) / "agent-workflow"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "agent-workflow"


def _safe_text(value: object, field: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ControlPlaneDenied(f"context packet field {field} is invalid or oversized")
    return value


def build_context_packet(
    *,
    run_id: str,
    taskcard: str,
    frozen_base: str,
    branch: str,
    pull_request: str = "",
    phase: str = "",
    transition: str = "",
    evidence: list[str] | None = None,
    prohibited_actions: list[str] | None = None,
    authority_manifest: dict[str, object] | None = None,
    next_action: str,
    stage: str,
    current_stage_evidence_commit: str = "",
    ledger_sequence: int = 0,
) -> dict[str, object]:
    """Build a bounded, credential-free recovery packet."""
    if not run_id or not taskcard or not frozen_base or not branch or not stage or not next_action:
        raise ControlPlaneDenied(
            "context packet requires run, TaskCard, base, branch, stage, next action"
        )
    values = {
        "format": PACKET_FORMAT,
        "run_id": _safe_text(run_id, "run_id", 256),
        "taskcard": _safe_text(taskcard, "taskcard"),
        "frozen_base": _safe_text(frozen_base, "frozen_base", 128),
        "branch": _safe_text(branch, "branch"),
        "pull_request": _safe_text(pull_request, "pull_request"),
        "phase": _safe_text(phase, "phase"),
        "transition": _safe_text(transition, "transition"),
        "evidence": list(evidence or [])[:32],
        "prohibited_actions": list(prohibited_actions or [])[:32],
        "authority_manifest": dict(authority_manifest or {}),
        "next_action": _safe_text(next_action, "next_action"),
        "stage": _safe_text(stage, "stage", 128),
        "current_stage_evidence_commit": _safe_text(
            current_stage_evidence_commit or frozen_base,
            "current_stage_evidence_commit",
            128,
        ),
        "ledger_sequence": ledger_sequence,
        "created_at": _now(),
    }
    for key in ("evidence", "prohibited_actions"):
        if not all(
            isinstance(item, str) and len(item.encode("utf-8")) <= 512 for item in values[key]
        ):
            raise ControlPlaneDenied(f"context packet {key} contains invalid evidence")
    authority = values["authority_manifest"]
    if not isinstance(authority, dict) or set(authority) != {"sha256", "allowed_operations"}:
        raise ControlPlaneDenied("context packet authority manifest binding is invalid")
    if not isinstance(authority["sha256"], str) or not isinstance(
        authority["allowed_operations"], list
    ):
        raise ControlPlaneDenied("context packet authority manifest binding is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", authority["sha256"]) or any(
        item not in SAFE_OPERATIONS for item in authority["allowed_operations"]
    ):
        raise ControlPlaneDenied("context packet authority manifest binding is unsafe")
    if len(_canonical(values).encode("utf-8")) > MAX_PACKET_BYTES:
        raise ControlPlaneDenied("context packet exceeds bounded size")
    values["packet_sha256"] = _sha(values)
    return values


def verify_context_packet(packet: dict[str, object]) -> None:
    if packet.get("format") != PACKET_FORMAT or not isinstance(packet.get("packet_sha256"), str):
        raise ControlPlaneDenied("context packet format or checksum is invalid")
    body = {key: value for key, value in packet.items() if key != "packet_sha256"}
    if packet["packet_sha256"] != _sha(body):
        raise ControlPlaneDenied("context packet checksum mismatch")
    if len(_canonical(packet).encode("utf-8")) > MAX_PACKET_BYTES:
        raise ControlPlaneDenied("context packet exceeds bounded size")


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    run_id: str
    sequence: int
    ledger_path: Path
    packet_path: Path


class RunLedger:
    """Versioned JSON ledger with atomic transitions and recovery verification."""

    def __init__(self, state_root: Path, run_id: str):
        self.state_root = Path(state_root).resolve()
        self.run_id = _safe_text(run_id, "run_id", 256)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.run_id):
            raise ControlPlaneDenied("run ID contains unsafe path characters")
        self.run_dir = self.state_root / "control-plane" / "runs" / self.run_id
        self.ledger_path = self.run_dir / "ledger.json"
        self.packet_path = self.run_dir / "context-packet.json"
        self.summary_path = self.run_dir / "summary.json"
        self.lock_path = self.run_dir / ".lock"

    def _load(self) -> dict[str, object] | None:
        if not self.ledger_path.exists():
            return None
        try:
            value = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ControlPlaneDenied("run ledger is unreadable or invalid JSON") from exc
        if not isinstance(value, dict) or value.get("format") != LEDGER_FORMAT:
            raise ControlPlaneDenied("run ledger format is invalid")
        return value

    def _save(self, ledger: dict[str, object]) -> None:
        _atomic_write(self.ledger_path, ledger)

    def recover(self) -> tuple[dict[str, object], dict[str, object]]:
        ledger = self._load()
        if ledger is None:
            raise ControlPlaneDenied("run ledger/context packet is missing")
        packet = ledger.get("context_packet")
        if not isinstance(packet, dict):
            raise ControlPlaneDenied("run ledger has no embedded context packet")
        verify_context_packet(packet)
        if packet.get("run_id") != self.run_id or packet.get("ledger_sequence") != ledger.get(
            "sequence"
        ):
            raise ControlPlaneDenied("ledger and context packet are inconsistent")
        if ledger.get("packet_sha256") != packet.get("packet_sha256"):
            raise ControlPlaneDenied("ledger does not bind the current context packet")
        return ledger, packet

    def initialize(
        self, packet: dict[str, object], *, stage: str, max_attempts: int, rework_budget: int
    ) -> None:
        verify_context_packet(packet)
        if packet.get("run_id") != self.run_id:
            raise ControlPlaneDenied("context packet run ID does not match ledger")
        if not 1 <= max_attempts <= 100 or not 0 <= rework_budget <= 100:
            raise ControlPlaneDenied("attempt/rework budgets must be non-negative and bounded")
        with _lock(self.lock_path):
            existing = self._load()
            if existing is not None:
                _, current_packet = self.recover()
                immutable = (
                    "run_id",
                    "taskcard",
                    "frozen_base",
                    "branch",
                    "authority_manifest",
                )
                if any(current_packet.get(key) != packet.get(key) for key in immutable):
                    raise ControlPlaneDenied("run already exists with a different context packet")
                return
            ledger = {
                "format": LEDGER_FORMAT,
                "run_id": self.run_id,
                "sequence": 0,
                "stage": stage,
                "terminal_state": "",
                "attempts": 0,
                "reworks": 0,
                "max_attempts": max_attempts,
                "rework_budget": rework_budget,
                "events": [],
                "decisions": [],
                "transitions": [],
                "packet_sha256": packet["packet_sha256"],
                "context_packet": packet,
                "updated_at": _now(),
            }
            self._save(ledger)
            _atomic_write(self.packet_path, packet)

    def _terminal_summary(self, ledger: dict[str, object]) -> dict[str, object]:
        return {
            "format": "awf.run-summary.v1",
            "run_id": self.run_id,
            "sequence": ledger["sequence"],
            "terminal_state": ledger["terminal_state"],
            "terminal": ledger["terminal"],
            "context_packet_sha256": ledger["packet_sha256"],
            "updated_at": ledger["updated_at"],
        }

    def mark_terminal(
        self,
        *,
        terminal_state: str,
        terminal: dict[str, object],
    ) -> dict[str, object]:
        """Persist one idempotent terminal decision and its operator summary."""
        if terminal_state not in TERMINAL_STATES:
            raise ControlPlaneDenied("terminal state is invalid")
        if not isinstance(terminal, dict) or len(_canonical(terminal).encode("utf-8")) > 64 * 1024:
            raise ControlPlaneDenied("terminal evidence is invalid or oversized")
        with _lock(self.lock_path):
            ledger = self._load()
            if ledger is None:
                raise ControlPlaneDenied("run ledger/context packet is missing")
            current_state = str(ledger.get("terminal_state", ""))
            if current_state:
                if current_state != terminal_state or ledger.get("terminal") != terminal:
                    raise ControlPlaneDenied("run already has a different terminal decision")
                _atomic_write(self.summary_path, self._terminal_summary(ledger))
                return ledger

            sequence = int(ledger.get("sequence", 0)) + 1
            packet = ledger.get("context_packet")
            if not isinstance(packet, dict):
                raise ControlPlaneDenied("run ledger has no embedded context packet")
            packet = {
                **packet,
                "ledger_sequence": sequence,
                "next_action": "stop",
                "transition": f"terminal:{terminal_state}",
                "updated_at": _now(),
            }
            packet["packet_sha256"] = _sha(
                {key: value for key, value in packet.items() if key != "packet_sha256"}
            )
            ledger = {
                **ledger,
                "sequence": sequence,
                "terminal_state": terminal_state,
                "terminal": terminal,
                "packet_sha256": packet["packet_sha256"],
                "context_packet": packet,
                "updated_at": _now(),
            }
            _atomic_write(self.packet_path, packet)
            self._save(ledger)
            _atomic_write(self.summary_path, self._terminal_summary(ledger))
            self.recover()
            return ledger

    def finalize_merge(
        self,
        *,
        pull_request: int,
        base_sha: str,
        head_sha: str,
        ci_conclusion: str,
        merge_commit: str,
    ) -> dict[str, object]:
        """Attach CI and merge evidence to a completed PASS without a new sequence."""
        if (
            pull_request < 1
            or not re.fullmatch(r"[0-9a-f]{40,64}", base_sha)
            or not re.fullmatch(r"[0-9a-f]{40,64}", head_sha)
            or not re.fullmatch(r"[0-9a-f]{40,64}", merge_commit)
            or not ci_conclusion
        ):
            raise ControlPlaneDenied("merge evidence is invalid")
        with _lock(self.lock_path):
            ledger = self._load()
            if ledger is None:
                raise ControlPlaneDenied("run ledger/context packet is missing")
            terminal = ledger.get("terminal")
            if (
                ledger.get("terminal_state") != "completed"
                or not isinstance(terminal, dict)
                or terminal.get("verdict") != "PASS"
            ):
                raise ControlPlaneDenied("only a completed PASS can record merge evidence")
            expected_pr = {
                "number": pull_request,
                "base_sha": base_sha,
                "head_sha": head_sha,
            }
            if terminal.get("pull_request") != expected_pr:
                raise ControlPlaneDenied("merge evidence does not match terminal PR provenance")
            expected_ci = {"status": "completed", "conclusion": ci_conclusion}
            expected_merge = {"status": "merged", "commit": merge_commit}
            current_ci = terminal.get("ci")
            current_merge = terminal.get("merge")
            if current_ci == expected_ci and current_merge == expected_merge:
                _atomic_write(self.summary_path, self._terminal_summary(ledger))
                return ledger
            if current_ci != {"status": "not_recorded", "conclusion": ""} or current_merge != {
                "status": "not_merged",
                "commit": "",
            }:
                raise ControlPlaneDenied("run already has different CI or merge evidence")
            terminal = {**terminal, "ci": expected_ci, "merge": expected_merge}
            ledger = {**ledger, "terminal": terminal, "updated_at": _now()}
            self._save(ledger)
            _atomic_write(self.summary_path, self._terminal_summary(ledger))
            return ledger

    def pre_invocation_gate(
        self,
        *,
        event_id: int,
        event_type: str,
        role: str,
        delivery_id: str,
        payload_sha256: str,
        stage: str,
        route_override: str = "",
        attempt: int = 1,
        rework: bool = False,
        active_routes: dict[str, list[str]] | None = None,
        terminal_state: str = "",
        current_stage_evidence_commit: str = "",
    ) -> GateDecision:
        """Atomically authorize exactly one model attempt before process start."""
        with _lock(self.lock_path):
            ledger = self._load()
            if ledger is None:
                return self._deny(
                    "run_ledger_missing", event_id, event_type, role, delivery_id, payload_sha256
                )
            if event_id < 1 or not delivery_id or not payload_sha256:
                return self._deny(
                    "invalid_event_metadata",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            routes = active_routes if active_routes is not None else DEFAULT_ROUTES
            compatible = routes.get(event_type, [])
            if len(compatible) != 1 or compatible[0] != role:
                return self._deny(
                    "no_unique_compatible_route",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            if route_override and route_override != role:
                return self._deny(
                    "route_override_mismatch",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            current_terminal = str(ledger.get("terminal_state") or terminal_state)
            if current_terminal in TERMINAL_STATES:
                return self._deny(
                    "terminal_state",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            if terminal_state and terminal_state in TERMINAL_STATES:
                return self._deny(
                    "terminal_state",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            events = ledger.setdefault("events", [])
            if not isinstance(events, list):
                raise ControlPlaneDenied("run ledger events are invalid")
            for previous in events:
                if isinstance(previous, dict) and previous.get("delivery_id") == delivery_id:
                    if previous.get("payload_sha256") == payload_sha256:
                        self._append_decision(
                            ledger,
                            status="replay",
                            reason="duplicate_event",
                            event_id=event_id,
                            event_type=event_type,
                            role=role,
                            delivery_id=delivery_id,
                            payload_sha256=payload_sha256,
                        )
                        self._save(ledger)
                        return GateDecision(
                            False,
                            "duplicate_event",
                            self.run_id,
                            int(ledger.get("sequence", 0)),
                            self.ledger_path,
                            self.packet_path,
                        )
                    reason = "delivery_id_reused"
                    return self._deny(
                        reason,
                        event_id,
                        event_type,
                        role,
                        delivery_id,
                        payload_sha256,
                        ledger=ledger,
                    )
            current_stage = str(ledger.get("stage"))
            rework_transition = stage == "rework" and current_stage in {"implement", "rework"}
            review_transition = stage == "review" and current_stage == "implement"
            if stage and current_stage != stage and not rework_transition and not review_transition:
                return self._deny(
                    "stage_mismatch",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            max_attempts = int(ledger.get("max_attempts", 1))
            budget = int(ledger.get("rework_budget", 0))
            stage_attempts = ledger.setdefault("stage_attempts", {})
            if not isinstance(stage_attempts, dict):
                raise ControlPlaneDenied("run ledger stage attempts are invalid")
            if attempt < 1 or attempt > max_attempts:
                return self._deny(
                    "attempt_budget_exceeded",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            if int(stage_attempts.get(stage, 0)) >= max_attempts:
                return self._deny(
                    "attempt_budget_exceeded",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            if rework and int(ledger.get("reworks", 0)) >= budget:
                return self._deny(
                    "rework_budget_exceeded",
                    event_id,
                    event_type,
                    role,
                    delivery_id,
                    payload_sha256,
                    ledger=ledger,
                )
            previous_stage = current_stage
            sequence = int(ledger.get("sequence", 0)) + 1
            if rework:
                ledger["reworks"] = int(ledger.get("reworks", 0)) + 1
            ledger["attempts"] = int(ledger.get("attempts", 0)) + 1
            stage_attempts[stage] = int(stage_attempts.get(stage, 0)) + 1
            ledger["sequence"] = sequence
            ledger["stage"] = stage
            event = {
                "event_id": event_id,
                "event_type": event_type,
                "role": role,
                "delivery_id": delivery_id,
                "payload_sha256": payload_sha256,
                "stage": stage,
                "route": route_override or role,
                "attempt": attempt,
                "status": "authorized",
                "authorized_at": _now(),
            }
            events.append(event)
            self._append_decision(
                ledger,
                status="authorized",
                reason="authorized",
                event_id=event_id,
                event_type=event_type,
                role=role,
                delivery_id=delivery_id,
                payload_sha256=payload_sha256,
            )
            ledger["transitions"] = [
                *list(ledger.get("transitions", [])),
                {
                    "sequence": sequence,
                    "from": previous_stage,
                    "to": stage,
                    "event_type": event_type,
                },
            ]
            ledger["updated_at"] = _now()
            packet = ledger.get("context_packet")
            if not isinstance(packet, dict):
                raise ControlPlaneDenied("run ledger has no embedded context packet")
            packet = {
                **packet,
                "ledger_sequence": sequence,
                "transition": event_type,
                "stage": stage,
                "current_stage_evidence_commit": _safe_text(
                    current_stage_evidence_commit
                    or packet.get("current_stage_evidence_commit")
                    or packet.get("frozen_base"),
                    "current_stage_evidence_commit",
                    128,
                ),
                "updated_at": _now(),
            }
            packet["packet_sha256"] = _sha(
                {key: value for key, value in packet.items() if key != "packet_sha256"}
            )
            ledger["packet_sha256"] = packet["packet_sha256"]
            ledger["context_packet"] = packet
            # The packet mirror may safely lead the ledger after a crash; the
            # atomically replaced ledger is the source of truth for authorization.
            _atomic_write(self.packet_path, packet)
            self._save(ledger)
            self.recover()
            return GateDecision(
                True, "authorized", self.run_id, sequence, self.ledger_path, self.packet_path
            )

    def _append_decision(
        self,
        ledger: dict[str, object],
        *,
        status: str,
        reason: str,
        event_id: int,
        event_type: str,
        role: str,
        delivery_id: str,
        payload_sha256: str,
    ) -> None:
        decisions = ledger.setdefault("decisions", [])
        if not isinstance(decisions, list):
            raise ControlPlaneDenied("run ledger decisions are invalid")
        decisions.append(
            {
                "decision_id": len(decisions) + 1,
                "status": status,
                "reason": reason,
                "event_id": event_id,
                "event_type": event_type,
                "role": role,
                "delivery_id": delivery_id,
                "payload_sha256": payload_sha256,
                "recorded_at": _now(),
            }
        )
        ledger["updated_at"] = _now()

    def _deny(
        self,
        reason: str,
        event_id: int,
        event_type: str,
        role: str,
        delivery_id: str,
        payload_sha256: str,
        *,
        ledger: dict[str, object] | None = None,
    ) -> GateDecision:
        sequence = int((ledger or {}).get("sequence", 0))
        if ledger is None:
            ledger = self._load()
        if isinstance(ledger, dict):
            self._append_decision(
                ledger,
                status="rejected",
                reason=reason,
                event_id=event_id,
                event_type=event_type,
                role=role,
                delivery_id=delivery_id,
                payload_sha256=payload_sha256,
            )
            events = ledger.setdefault("events", [])
            if isinstance(events, list) and not any(
                isinstance(e, dict) and e.get("delivery_id") == delivery_id for e in events
            ):
                events.append(
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "role": role,
                        "delivery_id": delivery_id,
                        "payload_sha256": payload_sha256,
                        "status": "rejected",
                        "reason": reason,
                        "rejected_at": _now(),
                    }
                )
            self._save(ledger)
        return GateDecision(
            False, reason, self.run_id, sequence, self.ledger_path, self.packet_path
        )


def load_authority_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlPlaneDenied("authority manifest is unreadable or invalid JSON") from exc
    if not isinstance(value, dict) or value.get("format") != AUTHORITY_FORMAT:
        raise ControlPlaneDenied("authority manifest format is invalid")
    allowed = value.get("allowed_operations", [])
    if not isinstance(allowed, list) or any(item not in SAFE_OPERATIONS for item in allowed):
        raise ControlPlaneDenied("authority manifest contains an unsafe operation")
    if set(allowed) & FORBIDDEN_OPERATIONS:
        raise ControlPlaneDenied("authority manifest cannot authorize forbidden operations")
    forbidden = value.get("forbidden_operations", [])
    if (
        not isinstance(forbidden, list)
        or not all(isinstance(item, str) for item in forbidden)
        or not FORBIDDEN_OPERATIONS.issubset(forbidden)
    ):
        raise ControlPlaneDenied("authority manifest omits a mandatory hard stop")
    return value


def authority_manifest_binding(manifest: dict[str, object]) -> dict[str, object]:
    """Return the bounded authority facts embedded in each recovery packet."""
    allowed = manifest.get("allowed_operations", [])
    if not isinstance(allowed, list):
        raise ControlPlaneDenied("authority manifest allowed operations are invalid")
    return {
        "sha256": _sha(manifest),
        "allowed_operations": sorted(str(item) for item in allowed),
    }


def authorize_operation(manifest: dict[str, object], operation: str) -> bool:
    if operation in FORBIDDEN_OPERATIONS or operation not in SAFE_OPERATIONS:
        raise ControlPlaneDenied(f"operation is not pre-authorized: {operation}")
    allowed = manifest.get("allowed_operations", [])
    if operation not in allowed:
        raise ControlPlaneDenied(f"operation is absent from authority manifest: {operation}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awf_control_plane")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("recover")
    inspect.add_argument("--state-root", type=Path, default=default_state_root())
    inspect.add_argument("--run-id", required=True)
    merge = sub.add_parser("finalize-merge")
    merge.add_argument("--state-root", type=Path, default=default_state_root())
    merge.add_argument("--run-id", required=True)
    merge.add_argument("--pull-request", required=True, type=int)
    merge.add_argument("--base-sha", required=True)
    merge.add_argument("--head-sha", required=True)
    merge.add_argument("--ci-conclusion", required=True)
    merge.add_argument("--merge-commit", required=True)
    auth = sub.add_parser("authorize")
    auth.add_argument("--manifest", type=Path, required=True)
    auth.add_argument("operation")
    args = parser.parse_args(argv)
    try:
        if args.command == "recover":
            ledger, packet = RunLedger(args.state_root, args.run_id).recover()
            print(
                json.dumps(
                    {"ledger": ledger, "context_packet": packet},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "finalize-merge":
            ledger = RunLedger(args.state_root, args.run_id).finalize_merge(
                pull_request=args.pull_request,
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                ci_conclusion=args.ci_conclusion,
                merge_commit=args.merge_commit,
            )
            print(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            manifest = load_authority_manifest(args.manifest)
            authorize_operation(manifest, args.operation)
            print("AUTHORIZED")
        return 0
    except ControlPlaneDenied as exc:
        print(f"awf_control_plane: denied: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
