#!/usr/bin/env python3
"""Bounded Dogfood Finding capture, transport, and durable ingest.

This operations module deliberately owns a state namespace separate from the
Workflow delivery outbox.  Models may propose one observation; trusted code
validates, identifies, transports, and durably stores it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

try:
    from awf_config import ConfigError, default_config_path, load_config
    from awf_control_plane import ControlPlaneDenied, _atomic_write, _lock
    from awf_executor import DEVNULL, ExecutionFailure
    from awf_executor import run as run_command
except ModuleNotFoundError:  # package import in tests
    from .awf_config import ConfigError, default_config_path, load_config
    from .awf_control_plane import ControlPlaneDenied, _atomic_write, _lock
    from .awf_executor import DEVNULL, ExecutionFailure
    from .awf_executor import run as run_command

from agent_workflow.state_root import state_root_binding

FINDING_FORMAT = "awf.finding-candidate.v1"
IDENTITY_FORMAT = "awf.finding-occurrence-identity.v1"
OCCURRENCE_FORMAT = "awf.finding-occurrence.v1"
OUTBOX_FORMAT = "awf.feedback-outbox.v1"
INGEST_FORMAT = "awf.feedback-ingest.v1"
REJECTION_FORMAT = "awf.feedback-rejection.v1"
EVENT_TYPE = "feedback:awf-finding-v1"
REPORTER_IDENTITY = "awf-reporter"

MARKER_STEM = b"<!-- awf-dogfood-finding-v1"
MARKER = MARKER_STEM + b"\n"
ENVELOPE_PREFIX = b"\n" + MARKER
ENVELOPE_SUFFIX = b"\n-->\n"
CRLF_ENVELOPE_PREFIX = b"\r\n" + MARKER_STEM + b"\r\n"
CRLF_ENVELOPE_SUFFIX = b"\r\n-->\r\n"
MAX_ENVELOPE_BYTES = 4096
MAX_FINAL_REPORT_BYTES = 16 * 1024
MAX_COMBINED_REPORT_BYTES = MAX_FINAL_REPORT_BYTES + MAX_ENVELOPE_BYTES

KINDS = frozenset({"bug", "reliability", "diagnostic", "usability"})
COMPONENTS = frozenset(
    {
        "adapter",
        "artifact",
        "configuration",
        "control_plane",
        "dispatch",
        "node",
        "postflight",
        "preflight",
        "recovery",
        "routing",
        "transport",
    }
)
EXACT_CANDIDATE_KEYS = frozenset({"kind", "component", "summary", "observed", "expected"})
EXACT_OCCURRENCE_KEYS = frozenset(
    {
        "format",
        "occurrence_id",
        "input_delivery_id",
        "source_role",
        "source_tool",
        "awf_version",
        "candidate",
    }
)
TEXT_LIMITS = {"summary": 200, "observed": 1024, "expected": 1024}
SOURCE_ROLES = frozenset({"coder", "reviewer"})
SOURCE_TOOLS = frozenset({"opencode", "codex", "pi"})
_SHA256_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")

_SAFETY_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN\s+(?:\S+\s+)?PRIVATE\s+KEY-----", re.I)),
    ("authenticated_url", re.compile(r"https?://[^/:@\s]+:[^/@\s]+@", re.I)),
    ("url", re.compile(r"https?://", re.I)),
    ("github_token", re.compile(r"gh[puosr]_[A-Za-z0-9_]{36,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("windows_absolute_path", re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s]")),
    (
        "posix_absolute_path",
        re.compile(r"(?<![A-Za-z0-9._-])/(?!/)[A-Za-z0-9._~-]+(?:/[^\s,;:]+)+"),
    ),
    (
        "environment_value",
        re.compile(r"(?i)(?:^|\s)(?:[A-Z][A-Z0-9_]{2,}|token|secret|password|api[_-]?key)=[^\s]+"),
    ),
    ("raw_prompt", re.compile(r"(?i)(?:system|developer|user)\s+prompt\s*:|<system>|<developer>")),
    (
        "raw_log",
        re.compile(
            r"(?i)(?:\btraceback \(most recent call last\)|\bstack trace\b|\bdebug\b|\bfatal\b)"
        ),
    ),
    ("raw_diff", re.compile(r"(?:diff --git|@@\s+-\d|^\+\+\+\s|^---\s)", re.M)),
    ("source_code", re.compile(r"```|~~~|\b(?:class|def|function)\s+[A-Za-z_]\w*\s*[({:]")),
)


class FindingContractError(RuntimeError):
    """The model used the reserved Finding syntax incorrectly."""


class FeedbackStateError(RuntimeError):
    """Feedback state is unavailable, ambiguous, or corrupt."""


@dataclass(frozen=True)
class FindingExtraction:
    report_bytes: bytes
    candidate: dict[str, str] | None
    candidate_sha256: str | None


@dataclass(frozen=True)
class CaptureResult:
    status: str
    occurrence_id: str = ""
    reason: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FindingContractError(f"duplicate JSON key '{key}'")
        result[key] = value
    return result


def _strict_json_object(raw: str, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except FindingContractError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise FindingContractError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise FindingContractError(f"{label} must be a JSON object")
    return value


def _validate_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FindingContractError(f"Finding field '{field}' must be a non-empty string")
    if value != value.strip():
        raise FindingContractError(f"Finding field '{field}' must not have outer whitespace")
    normalized = unicodedata.normalize("NFC", value)
    if value != normalized:
        raise FindingContractError(f"Finding field '{field}' must be NFC-normalized")
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value):
        raise FindingContractError(f"Finding field '{field}' contains a control character")
    if len(value.encode("utf-8")) > TEXT_LIMITS[field]:
        raise FindingContractError(f"Finding field '{field}' exceeds its byte limit")
    return value


def normalize_candidate(value: Mapping[str, object]) -> dict[str, str]:
    if frozenset(value) != EXACT_CANDIDATE_KEYS:
        raise FindingContractError("Finding candidate keys do not match the v1 contract")
    kind = value.get("kind")
    component = value.get("component")
    if kind not in KINDS:
        raise FindingContractError("Finding kind is not allowed")
    if component not in COMPONENTS:
        raise FindingContractError("Finding component is not allowed")
    return {
        "kind": str(kind),
        "component": str(component),
        "summary": _validate_text(value.get("summary"), "summary"),
        "observed": _validate_text(value.get("observed"), "observed"),
        "expected": _validate_text(value.get("expected"), "expected"),
    }


def extract_finding(raw: bytes) -> FindingExtraction:
    """Recognize exactly one complete EOF-anchored envelope and preserve its prefix."""
    marker_count = raw.count(MARKER_STEM)
    if marker_count == 0:
        return FindingExtraction(raw, None, None)
    if marker_count != 1:
        raise FindingContractError("Report contains more than one reserved Finding marker")
    envelope_parts = next(
        (
            (prefix, suffix)
            for prefix, suffix in (
                (ENVELOPE_PREFIX, ENVELOPE_SUFFIX),
                (CRLF_ENVELOPE_PREFIX, CRLF_ENVELOPE_SUFFIX),
            )
            if raw.find(prefix) >= 0 and raw.endswith(suffix)
        ),
        None,
    )
    if envelope_parts is None:
        raise FindingContractError("reserved Finding marker is not a complete EOF envelope")
    prefix, suffix = envelope_parts
    start = raw.find(prefix)
    envelope = raw[start:]
    if len(envelope) > MAX_ENVELOPE_BYTES:
        raise FindingContractError("Finding envelope exceeds 4096 bytes")
    json_bytes = raw[start + len(prefix) : -len(suffix)]
    try:
        json_text = json_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise FindingContractError("Finding envelope must be strict UTF-8") from exc
    candidate = normalize_candidate(_strict_json_object(json_text, label="Finding candidate"))
    return FindingExtraction(raw[:start], candidate, _sha256_bytes(envelope))


def transport_safety_reason(candidate: Mapping[str, str]) -> str | None:
    text = "\n".join(candidate[field] for field in sorted(EXACT_CANDIDATE_KEYS))
    for label, detector in _SAFETY_DETECTORS:
        if detector.search(text):
            return label
    return None


def build_occurrence(
    candidate: Mapping[str, str],
    *,
    input_delivery_id: str,
    source_role: str,
    source_tool: str,
    awf_version: str,
) -> dict[str, object]:
    if not input_delivery_id or len(input_delivery_id.encode("utf-8")) > 512:
        raise FindingContractError("input delivery identity is missing or oversized")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in input_delivery_id):
        raise FindingContractError("input delivery identity contains a control character")
    if source_role not in SOURCE_ROLES or source_tool not in SOURCE_TOOLS:
        raise FindingContractError("Finding source role/tool is not allowed")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]{0,32})?", awf_version):
        raise FindingContractError("Agent Workflow version is invalid")
    normalized = normalize_candidate(candidate)
    identity = {
        "format": IDENTITY_FORMAT,
        "input_delivery_id": input_delivery_id,
        "candidate_index": 0,
        "candidate": normalized,
    }
    return {
        "format": OCCURRENCE_FORMAT,
        "occurrence_id": _sha256_json(identity),
        "input_delivery_id": input_delivery_id,
        "source_role": source_role,
        "source_tool": source_tool,
        "awf_version": awf_version,
        "candidate": normalized,
    }


def validate_occurrence(value: Mapping[str, object]) -> dict[str, object]:
    if frozenset(value) != EXACT_OCCURRENCE_KEYS:
        raise FindingContractError("Finding occurrence keys do not match the v1 contract")
    for field in (
        "format",
        "occurrence_id",
        "input_delivery_id",
        "source_role",
        "source_tool",
        "awf_version",
    ):
        if not isinstance(value.get(field), str):
            raise FindingContractError(f"Finding occurrence field '{field}' must be a string")
    if not isinstance(value.get("candidate"), dict):
        raise FindingContractError("Finding occurrence candidate must be an object")
    occurrence = build_occurrence(
        value["candidate"],
        input_delivery_id=value["input_delivery_id"],
        source_role=value["source_role"],
        source_tool=value["source_tool"],
        awf_version=value["awf_version"],
    )
    if value.get("format") != OCCURRENCE_FORMAT:
        raise FindingContractError("Finding occurrence format is invalid")
    if value.get("occurrence_id") != occurrence["occurrence_id"]:
        raise FindingContractError("Finding occurrence identity does not match its contents")
    unsafe_reason = transport_safety_reason(occurrence["candidate"])
    if unsafe_reason:
        raise FindingContractError(
            f"Finding occurrence contains prohibited {unsafe_reason} material"
        )
    return occurrence


def _feedback_root(state_root: Path) -> Path:
    return state_root / "feedback"


def _digest_from_id(occurrence_id: str) -> str:
    if not _SHA256_ID_RE.fullmatch(occurrence_id):
        raise FeedbackStateError("occurrence ID is not a SHA-256 identity")
    return occurrence_id.removeprefix("sha256:")


def _load_record(path: Path, *, label: str) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = _strict_json_object(raw, label=label)
    except (OSError, UnicodeError, FindingContractError) as exc:
        raise FeedbackStateError(f"{label} is corrupt") from exc
    return value


def _validate_outbox_record(value: Mapping[str, object]) -> dict[str, object]:
    required_keys = {
        "format",
        "status",
        "occurrence",
        "occurrence_sha256",
        "created_at",
        "updated_at",
    }
    valid_keys = {frozenset(required_keys), frozenset({*required_keys, "state_root_sha256"})}
    if frozenset(value) not in valid_keys or value.get("format") != OUTBOX_FORMAT:
        raise FeedbackStateError("Feedback Outbox record format is invalid")
    if "state_root_sha256" in value and not _SHA256_ID_RE.fullmatch(
        str(value.get("state_root_sha256", ""))
    ):
        raise FeedbackStateError("Feedback Outbox state-root binding is invalid")
    if value.get("status") not in {"pending", "sent"}:
        raise FeedbackStateError("Feedback Outbox record status is invalid")
    raw_occurrence = value.get("occurrence")
    if not isinstance(raw_occurrence, dict):
        raise FeedbackStateError("Feedback Outbox occurrence is invalid")
    try:
        occurrence = validate_occurrence(raw_occurrence)
    except FindingContractError as exc:
        raise FeedbackStateError("Feedback Outbox occurrence is invalid") from exc
    if value.get("occurrence_sha256") != _sha256_json(occurrence):
        raise FeedbackStateError("Feedback Outbox occurrence hash is invalid")
    timestamps = (value.get("created_at"), value.get("updated_at"))
    if not all(isinstance(item, str) and item for item in timestamps):
        raise FeedbackStateError("Feedback Outbox timestamps are invalid")
    return occurrence


def _validate_occurrence_path(path: Path, occurrence: Mapping[str, object]) -> None:
    digest = _digest_from_id(str(occurrence["occurrence_id"]))
    if path.stem != digest:
        raise FeedbackStateError("Feedback state path does not match its occurrence identity")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        raise FeedbackStateError("reporter durable ingest requires POSIX directory fsync")
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _strict_atomic_write(path: Path, value: dict[str, object]) -> None:
    """Commit reporter state only when file and containing directory are durable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def queue_occurrence(state_root: Path, occurrence: Mapping[str, object]) -> Path:
    checked = validate_occurrence(occurrence)
    digest = _digest_from_id(str(checked["occurrence_id"]))
    root = _feedback_root(state_root)
    path = root / "outbox" / f"{digest}.json"
    with _lock(root / ".lock"):
        if path.exists():
            existing = _load_record(path, label="Feedback Outbox record")
            if _validate_outbox_record(existing) != checked:
                raise FeedbackStateError("Feedback Outbox occurrence conflicts with existing state")
            root_binding = existing.get("state_root_sha256", "")
            if root_binding and root_binding != state_root_binding(state_root):
                raise FeedbackStateError(
                    "Feedback Outbox state-root binding conflicts with location"
                )
            if not root_binding:
                _atomic_write(
                    path,
                    {**existing, "state_root_sha256": state_root_binding(state_root)},
                )
            return path
        now = _now()
        _atomic_write(
            path,
            {
                "format": OUTBOX_FORMAT,
                "status": "pending",
                "state_root_sha256": state_root_binding(state_root),
                "occurrence": checked,
                "occurrence_sha256": _sha256_json(checked),
                "created_at": now,
                "updated_at": now,
            },
        )
    return path


def _write_rejection_best_effort(
    state_root: Path,
    *,
    reason: str,
    candidate_sha256: str,
) -> None:
    digest = candidate_sha256.removeprefix("sha256:")
    try:
        _atomic_write(
            _feedback_root(state_root) / "rejected" / f"{digest}.json",
            {
                "format": REJECTION_FORMAT,
                "status": "source_rejected",
                "reason": reason,
                "candidate_sha256": candidate_sha256,
            },
        )
    except OSError:
        return


def _atomic_write_report(path: Path, content: bytes) -> None:
    temp = path.with_name(f".{path.name}.feedback-{os.getpid()}-{time.time_ns()}")
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def capture_report_finding(
    report_path: Path,
    state_root: Path | Callable[[], Path] | None,
    *,
    input_delivery_id: str,
    source_role: str,
    source_tool: str,
    awf_version: str,
    warn: Callable[[str], None] | None = None,
) -> CaptureResult:
    raw = report_path.read_bytes()
    extraction = extract_finding(raw)
    if extraction.candidate is None:
        return CaptureResult("absent")
    if callable(state_root):
        try:
            state_root = state_root()
        except FeedbackStateError as exc:
            if warn is not None:
                warn(f"Finding state is unavailable: {type(exc).__name__}")
            state_root = None
    reason = transport_safety_reason(extraction.candidate)
    if reason:
        if state_root is not None:
            _write_rejection_best_effort(
                state_root,
                reason=reason,
                candidate_sha256=str(extraction.candidate_sha256),
            )
        _atomic_write_report(report_path, extraction.report_bytes)
        return CaptureResult("source_rejected", reason=reason)
    occurrence = build_occurrence(
        extraction.candidate,
        input_delivery_id=input_delivery_id,
        source_role=source_role,
        source_tool=source_tool,
        awf_version=awf_version,
    )
    if state_root is None:
        if warn is not None:
            warn("Finding was stripped but not queued: FeedbackStateUnavailable")
        _atomic_write_report(report_path, extraction.report_bytes)
        return CaptureResult("queue_failed")
    try:
        queue_occurrence(state_root, occurrence)
    except (ControlPlaneDenied, FeedbackStateError, OSError) as exc:
        if warn is not None:
            warn(f"Finding was stripped but not queued: {type(exc).__name__}")
        _atomic_write_report(report_path, extraction.report_bytes)
        return CaptureResult("queue_failed")
    _atomic_write_report(report_path, extraction.report_bytes)
    return CaptureResult("queued", occurrence_id=str(occurrence["occurrence_id"]))


def feedback_status(state_root: Path) -> dict[str, int]:
    counts = {"pending": 0, "sent": 0, "rejected": 0, "corrupt": 0}
    outbox = _feedback_root(state_root) / "outbox"
    for path in sorted(outbox.glob("*.json")) if outbox.is_dir() else []:
        try:
            record = _load_record(path, label="Feedback Outbox record")
            occurrence = _validate_outbox_record(record)
            _validate_occurrence_path(path, occurrence)
            root_binding = record.get("state_root_sha256", "")
            if root_binding and root_binding != state_root_binding(state_root):
                raise FeedbackStateError(
                    "Feedback Outbox state-root binding conflicts with location"
                )
            counts[str(record["status"])] += 1
        except (FeedbackStateError, FindingContractError):
            counts["corrupt"] += 1
    rejected = _feedback_root(state_root) / "rejected"
    counts["rejected"] = len(list(rejected.glob("*.json"))) if rejected.is_dir() else 0
    return counts


def _mark_sent(path: Path, occurrence: Mapping[str, object]) -> None:
    root = path.parent.parent
    with _lock(root / ".lock"):
        record = _load_record(path, label="Feedback Outbox record")
        checked = _validate_outbox_record(record)
        _validate_occurrence_path(path, checked)
        root_binding = record.get("state_root_sha256", "")
        if root_binding and root_binding != state_root_binding(root.parent):
            raise FeedbackStateError("Feedback Outbox state-root binding conflicts with location")
        if checked != occurrence:
            raise FeedbackStateError("Feedback Outbox changed while sending")
        record["status"] = "sent"
        record["updated_at"] = _now()
        _atomic_write(path, record)


def flush_feedback(
    state_root: Path,
    *,
    config_path: Path,
    limit: int = 20,
    runner: Callable[..., object] = run_command,
) -> tuple[int, int]:
    if limit < 1 or limit > 1000:
        raise FeedbackStateError("flush limit must be between 1 and 1000")
    config = load_config(config_path, runner=runner)
    url = config.get("AGENT_BUS_URL", "")
    bus = config.get("AWF_BUS_BIN", "agent-bus")
    if not url:
        raise FeedbackStateError("AGENT_BUS_URL is required to flush feedback")
    sent = 0
    failed = 0
    outbox = _feedback_root(state_root) / "outbox"
    paths = sorted(outbox.glob("*.json")) if outbox.is_dir() else []
    for path in paths:
        if sent + failed >= limit:
            break
        record = _load_record(path, label="Feedback Outbox record")
        occurrence = _validate_outbox_record(record)
        _validate_occurrence_path(path, occurrence)
        if record.get("status") != "pending":
            continue
        role = str(occurrence["source_role"])
        token = config.get(f"AWF_{role.upper()}_TOKEN", "")
        if not token:
            failed += 1
            continue
        environment = dict(os.environ)
        environment.update(
            {
                "AGENT_BUS_URL": url,
                "AGENT_BUS_TOKEN": token,
                "AGENT_BUS_AGENT": role,
            }
        )
        argv = [
            bus,
            "send",
            "--from",
            role,
            "--to",
            REPORTER_IDENTITY,
            "--type",
            EVENT_TYPE,
            "--payload",
            canonical_json(occurrence),
        ]
        try:
            completed = runner(
                argv,
                env=environment,
                stdin=DEVNULL,
                allow_shell_wrapper=True,
                secrets=(token,),
            )
        except ExecutionFailure:
            failed += 1
            continue
        if getattr(completed, "returncode", 1) != 0:
            failed += 1
            continue
        _mark_sent(path, occurrence)
        sent += 1
    return sent, failed


def ingest_occurrence(state_root: Path, payload: str) -> tuple[str, Path]:
    occurrence = validate_occurrence(_strict_json_object(payload, label="Finding occurrence"))
    digest = _digest_from_id(str(occurrence["occurrence_id"]))
    root = _feedback_root(state_root)
    path = root / "ingested" / f"{digest}.json"
    with _lock(root / ".ingest.lock"):
        if path.exists():
            existing = _load_record(path, label="Feedback ingest record")
            exact_keys = {
                "format",
                "status",
                "occurrence",
                "occurrence_sha256",
                "ingested_at",
            }
            if (
                set(existing) != exact_keys
                or existing.get("format") != INGEST_FORMAT
                or existing.get("status") != "ingested"
                or existing.get("occurrence") != occurrence
                or existing.get("occurrence_sha256") != _sha256_json(occurrence)
                or not isinstance(existing.get("ingested_at"), str)
                or not existing.get("ingested_at")
            ):
                raise FeedbackStateError("existing Feedback ingest state is corrupt or conflicting")
            _fsync_directory(path.parent)
            return "duplicate", path
        _strict_atomic_write(
            path,
            {
                "format": INGEST_FORMAT,
                "status": "ingested",
                "occurrence": occurrence,
                "occurrence_sha256": _sha256_json(occurrence),
                "ingested_at": _now(),
            },
        )
    return "ingested", path


def default_state_root() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise FeedbackStateError("LOCALAPPDATA is required for feedback state")
        return Path(local) / "agent-workflow"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "agent-workflow"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awf feedback")
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--state-root", type=Path, default=None)
    status_parser.add_argument("--json", action="store_true")
    flush_parser = commands.add_parser("flush")
    flush_parser.add_argument("--state-root", type=Path, default=None)
    flush_parser.add_argument("--config", type=Path, default=default_config_path())
    flush_parser.add_argument("--limit", type=int, default=20)
    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("--state-root", type=Path, default=None)
    ingest_parser.add_argument("--payload-json", required=True)
    args = parser.parse_args(argv)
    try:
        state_root = args.state_root or default_state_root()
        if args.command == "status":
            counts = feedback_status(state_root)
            if args.json:
                print(canonical_json(counts))
            else:
                print(" ".join(f"{key}={counts[key]}" for key in counts))
            return 1 if counts["corrupt"] else 0
        if args.command == "flush":
            sent, failed = flush_feedback(
                state_root,
                config_path=args.config,
                limit=args.limit,
            )
            print(f"sent={sent} failed={failed}")
            return 1 if failed else 0
        status, path = ingest_occurrence(state_root, args.payload_json)
        print(f"status={status} occurrence={path.stem}")
        return 0
    except (
        ConfigError,
        ControlPlaneDenied,
        FeedbackStateError,
        FindingContractError,
        OSError,
    ) as exc:
        print(f"awf feedback: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
