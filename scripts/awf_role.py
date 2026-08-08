#!/usr/bin/env python3
"""awf_role — cross-platform Agent Workflow role handler.

This replaces the bash role handlers (roles/coder.sh, roles/reviewer.sh) and the
local executor (executors/local.sh). It is invoked by a role listener as the
Agent Bus `--on` handler when a stage event arrives:

    python awf_role.py coder    --event-id ID --branch B --card C --commit H --tool T --report R
    python awf_role.py reviewer --event-id ID --branch B --card C ... --report R --base BASE

Why Python instead of bash: the Agent Bus handler-template compatibility
contract historically exposed Windows cmd and POSIX shell differences. Python
runs identically on macOS and Windows, so business execution no longer depends
on the launch shell dialect.

Design:
  - Named arguments (not positional) so stage-to-stage field order can never drift.
  - Per-listener config comes from the environment (set by awf_listen.py):
      AWF_SCRIPT_DIR, AWF_REPO_DIR, AWF_TOOL, AWF_MODEL, AWF_BASE, AWF_NO_PUSH,
      AGENT_BUS_URL, AWF_BUS_BIN, AWF_<ROLE>_TOKEN, AWF_OPENCODE_BIN, AWF_PI_BIN
  - The card/prompt travel as FILES (never inlined into a shell string).
  - External commands cross awf_executor as argv with shell=False.
    Windows npm .cmd shims require a safe PowerShell companion; .bat is rejected.
  - Exit 0 == success -> the agent-bus listener ACKs the event.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agent_adapters.codex import (
    render_reviewer_invocation as render_codex_reviewer_invocation,
)
from agent_adapters.opencode import (
    render_executor_argv as render_opencode_executor_argv,
)
from agent_adapters.opencode import (
    render_reviewer_argv as render_opencode_reviewer_argv,
)
from agent_adapters.pi import (
    render_reviewer_argv as render_pi_reviewer_argv,
)
from awf_artifact_contract import ArtifactContractError, validate_stage_artifact_contract
from awf_control_plane import (
    DEFAULT_ROUTES,
    ControlPlaneDenied,
    RunLedger,
    authority_manifest_binding,
    build_context_packet,
    load_authority_manifest,
)
from awf_delivery import canonical_payload_sha256, make_delivery_id
from awf_executor import (
    DEVNULL,
    PIPE,
    CompletedProcess,
    ExecutionFailure,
)
from awf_executor import (
    run as run_command,
)
from awf_executor import (
    start as start_command,
)
from awf_taskcard import (
    ReviewerSelectionContract,
    TaskCardContractError,
    reviewer_selection_contract,
)


def log(msg: str) -> None:
    print(f"[awf_role] {msg}", flush=True)


def die(msg: str, code: int = 1):
    print(f"awf_role: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        die(f"missing required environment variable {name}")
    return val or ""


def child_env() -> dict[str, str]:
    """Environment for spawned children: inherit-and-augment, never replace.

    A bare ``env={}`` breaks Windows DLL loading, and a service/cmd.exe context can
    strip variables git needs. So we always start from the full parent environment and
    only *add* what we require. ``PYTHONUTF8=1`` makes child Python processes decode as
    UTF-8 (no-op on POSIX; stops gbk crashes on Windows).
    """
    e = dict(os.environ)
    e.setdefault("PYTHONUTF8", "1")
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


def workflow_state_directory(
    *,
    os_name: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the per-user Agent Workflow state root outside Git checkouts."""
    platform = os_name or os.name
    values = os.environ if environ is None else environ
    if platform == "nt":
        local_app_data = values.get("LOCALAPPDATA")
        if not local_app_data:
            die("LOCALAPPDATA is required for durable handler evidence on Windows")
        root = Path(local_app_data)
    else:
        xdg_state_home = values.get("XDG_STATE_HOME")
        root = Path(xdg_state_home) if xdg_state_home else (home or Path.home()) / ".local/state"
    return root / "agent-workflow"


def event_run_directory(
    event_id: int,
    *,
    os_name: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the event-scoped OS state directory, always outside the checkout."""
    return (
        workflow_state_directory(os_name=os_name, environ=environ, home=home)
        / "runs"
        / f"event-{event_id}"
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunEvidence:
    """Append durable phase records and atomically publish the latest run result."""

    def __init__(
        self,
        event_id: int,
        role: str,
        *,
        state_root: Path | None = None,
    ) -> None:
        self.event_id = event_id
        self.role = role
        if state_root is not None:
            self.state_dir = Path(state_root)
            self.run_dir = self.state_dir / f"event-{event_id}"
        else:
            self.run_dir = event_run_directory(event_id)
            self.state_dir = (
                self.run_dir.parent.parent
                if self.run_dir.parent.name == "runs"
                else self.run_dir.parent
            )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.run_dir / "handler.log"
        self.result_path = self.run_dir / "result.json"
        self.state: dict[str, object] = {
            "event_id": event_id,
            "role": role,
            "handler_pid": os.getpid(),
            "postflight_started": False,
            "postflight_status": "not_started",
        }

    def record(self, phase: str, **fields: object) -> None:
        """Persist one non-sensitive phase record and the latest aggregate state."""
        timestamp = _utc_now()
        if phase == "handler_exit":
            self.state["last_phase_before_exit"] = self.state.get("last_phase")
        self.state.update(fields)
        self.state["last_phase"] = phase
        self.state["updated_at"] = timestamp
        if "started_at" not in self.state:
            self.state["started_at"] = timestamp

        entry = {
            "time": timestamp,
            "event_id": self.event_id,
            "role": self.role,
            "phase": phase,
            **fields,
        }
        with self.log_path.open("a", encoding="utf-8", newline="\n") as log_file:
            log_file.write(json.dumps(entry, sort_keys=True) + "\n")
            log_file.flush()
            os.fsync(log_file.fileno())

        temp_path = self.result_path.with_name(f"result.json.tmp-{os.getpid()}")
        with temp_path.open("w", encoding="utf-8", newline="\n") as result_file:
            json.dump(self.state, result_file, indent=2, sort_keys=True)
            result_file.write("\n")
            result_file.flush()
            os.fsync(result_file.fileno())
        os.replace(temp_path, self.result_path)


def record(evidence: RunEvidence | None, phase: str, **fields: object) -> None:
    if evidence is not None:
        evidence.record(phase, **fields)


_INPUT_TYPES = {
    "task:awf-impl": ("architect", "coder"),
    "task:awf-impl-v2": ("architect", "coder"),
    "task:awf-impl-v3": ("architect", "coder"),
    "task:awf-review": ("coder", "reviewer"),
    "task:awf-review-v2": ("coder", "reviewer"),
    "task:awf-review-v3": ("coder", "reviewer"),
    "task:awf-rework": ("reviewer", "coder"),
    "task:awf-rework-v2": ("reviewer", "coder"),
    "task:awf-rework-v3": ("reviewer", "coder"),
    "decision:awf-ready": ("reviewer", "architect"),
    "decision:awf-ready-v2": ("reviewer", "architect"),
    "decision:awf-ready-v3": ("reviewer", "architect"),
    "decision:awf-blocked": ("reviewer", "architect"),
    "decision:awf-blocked-v2": ("reviewer", "architect"),
    "decision:awf-blocked-v3": ("reviewer", "architect"),
}

_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})/[A-Za-z0-9_.-]{1,100}$")
_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PROVENANCE_FIELDS = (
    "provenance_version",
    "upstream_repo",
    "base_ref",
    "base_sha",
    "head_repo",
    "head_ref",
    "head_sha",
    "pull_request",
)


def _is_v3(a: argparse.Namespace) -> bool:
    return str(getattr(a, "input_type", "")).endswith("-v3")


def validate_repo_slug(value: str, label: str) -> str:
    if not _REPO_SLUG_RE.fullmatch(value) or value.endswith((".git", ".", "/")):
        die(f"{label} must be an owner/repository GitHub slug")
    return value


def validate_remote_name(value: str, label: str) -> str:
    if not _REMOTE_NAME_RE.fullmatch(value):
        die(f"{label} is invalid")
    return value


def validate_git_ref(repo: str, value: str, label: str) -> str:
    if (
        not value
        or value.startswith("-")
        or value.startswith("refs/")
        or any(char.isspace() for char in value)
        or git(repo, "check-ref-format", "--branch", value) != 0
    ):
        die(f"{label} is invalid")
    return value


def validate_remote_url(url: str, expected_repo: str, label: str) -> None:
    if not url:
        die(f"{label} is missing")
    parsed = urlsplit(url)
    expected_path = f"/{expected_repo}.git"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {expected_path, expected_path.removesuffix(".git")}
    ):
        die(f"{label} is not a canonical credential-free GitHub HTTPS URL")


def validate_remote_binding(repo: str, remote: str, expected_repo: str) -> None:
    validate_remote_name(remote, "configured remote name")
    validate_repo_slug(expected_repo, "configured repository")
    fetch_url = git_out(repo, "remote", "get-url", remote)
    validate_remote_url(fetch_url, expected_repo, f"configured remote {remote!r} fetch URL")
    push_urls = git_out(repo, "remote", "get-url", "--push", "--all", remote).splitlines()
    if push_urls != [fetch_url]:
        die(f"configured remote {remote!r} push URL must equal its validated fetch URL")
    validate_remote_url(push_urls[0], expected_repo, f"configured remote {remote!r} push URL")


def trusted_remote_config(
    repo: str,
    *,
    upstream_remote: str = "",
    head_remote: str = "",
) -> dict[str, str]:
    config = {
        "upstream_repo": env("AWF_UPSTREAM_REPO", required=True),
        "upstream_remote": upstream_remote or env("AWF_UPSTREAM_REMOTE", "upstream"),
        "head_repo": env("AWF_HEAD_REPO", required=True),
        "head_remote": head_remote or env("AWF_HEAD_REMOTE", "fork"),
        "base_ref": env("AWF_BASE_REF", "main"),
    }
    validate_repo_slug(config["upstream_repo"], "configured upstream repository")
    validate_repo_slug(config["head_repo"], "configured contribution repository")
    if config["upstream_repo"].casefold() == config["head_repo"].casefold():
        die("upstream and contribution repositories must be distinct")
    if config["upstream_remote"] == config["head_remote"]:
        die("upstream and contribution remote names must be distinct")
    validate_remote_binding(repo, config["upstream_remote"], config["upstream_repo"])
    validate_remote_binding(repo, config["head_remote"], config["head_repo"])
    validate_git_ref(repo, config["base_ref"], "configured base ref")
    return config


def provenance_from_args(
    a: argparse.Namespace,
    repo: str,
    *,
    require_pr: bool,
) -> dict[str, object]:
    if not _is_v3(a):
        die("PR provenance is only defined for v3 Workflow routes")
    values: dict[str, object] = {field: getattr(a, field, "") for field in _PROVENANCE_FIELDS}
    if values["provenance_version"] != "awf.pr-provenance.v1":
        die("PR provenance version is missing or unsupported")
    validate_repo_slug(str(values["upstream_repo"]), "provenance upstream repository")
    validate_repo_slug(str(values["head_repo"]), "provenance head repository")
    validate_git_ref(repo, str(values["base_ref"]), "provenance base ref")
    validate_git_ref(repo, str(values["head_ref"]), "provenance head ref")
    for field in ("base_sha", "head_sha"):
        value = str(values[field])
        if not _FULL_COMMIT_RE.fullmatch(value):
            die(f"provenance {field} must be a full lowercase Git commit ID")
    try:
        pull_request = int(values["pull_request"] or 0)
    except (TypeError, ValueError):
        die("provenance pull request must be an integer")
    if pull_request < (1 if require_pr else 0):
        die("review provenance requires a positive pull request number")
    values["pull_request"] = pull_request
    config = trusted_remote_config(
        repo,
        upstream_remote=str(getattr(a, "upstream_remote", "")),
        head_remote=str(getattr(a, "head_remote", "")),
    )
    for field in ("upstream_repo", "head_repo", "base_ref"):
        if values[field] != config[field]:
            die(f"provenance {field} does not match trusted local configuration")
    if str(values["head_ref"]) != a.branch:
        die("provenance head ref must match the Workflow branch")
    if str(values["head_sha"]) != a.commit:
        die("provenance head SHA must match the Workflow commit")
    return {**values, **config}


def provenance_payload(provenance: dict[str, object]) -> dict[str, object]:
    return {field: provenance[field] for field in _PROVENANCE_FIELDS}


def input_payload(a: argparse.Namespace, role: str) -> dict[str, object]:
    """Reconstruct the metadata-free payload delivered to a role handler."""
    input_type = getattr(a, "input_type", "")
    expected = _INPUT_TYPES.get(input_type)
    if expected is None or expected[1] != role:
        die(f"unsupported Workflow input type {input_type!r} for role {role}")
    payload: dict[str, object] = {
        "task_id": a.branch.rsplit("/", 1)[-1],
        "branch": a.branch,
        "card": a.card,
        "commit": a.commit,
        "tool": a.tool,
        "model": a.model,
        "report": a.report,
    }
    if input_type in {
        "task:awf-rework",
        "task:awf-rework-v2",
        "task:awf-rework-v3",
        "decision:awf-ready",
        "decision:awf-ready-v2",
        "decision:awf-ready-v3",
        "decision:awf-blocked",
        "decision:awf-blocked-v2",
        "decision:awf-blocked-v3",
    }:
        try:
            feedback = json.loads(getattr(a, "review_feedback", ""))
        except json.JSONDecodeError:
            die("structured review feedback must be valid JSON")
        if not isinstance(feedback, dict):
            die("structured review feedback must be a JSON object")
        payload["review_report_path"] = a.review_report
        payload["review_report"] = feedback
    else:
        payload["review_report"] = a.review_report
    if _is_v3(a):
        payload.update({field: getattr(a, field, "") for field in _PROVENANCE_FIELDS})
    return payload


def validate_input_delivery(
    a: argparse.Namespace,
    role: str,
    evidence: RunEvidence | None,
) -> dict[str, object]:
    delivery_id = getattr(a, "delivery_id", "")
    payload_sha256 = getattr(a, "payload_sha256", "")
    input_type = getattr(a, "input_type", "")
    source_event_id = getattr(a, "source_event_id", 0)
    if not delivery_id and not payload_sha256 and not input_type:
        event_id = evidence.event_id if evidence is not None else 0
        return {
            "key": f"legacy-event-{event_id}",
            "delivery_id": "",
            "payload_sha256": "",
            "source_event_id": event_id,
        }
    if not (delivery_id and payload_sha256 and input_type):
        die("Workflow delivery metadata must be provided together")
    if not isinstance(source_event_id, int) or source_event_id < 0:
        die("Workflow source event ID must be a non-negative integer")
    expected_roles = _INPUT_TYPES.get(input_type)
    if expected_roles is None or expected_roles[1] != role:
        die(f"unsupported Workflow input type {input_type!r} for role {role}")
    payload = input_payload(a, role)
    actual_hash = canonical_payload_sha256(payload)
    if actual_hash != payload_sha256:
        die("Workflow input payload hash mismatch")
    expected_delivery = make_delivery_id(
        expected_roles[0], input_type, actual_hash, source_event_id
    )
    if delivery_id != expected_delivery:
        die("Workflow delivery ID does not match its bound input")
    return {
        "key": delivery_id,
        "delivery_id": delivery_id,
        "payload_sha256": actual_hash,
        "source_event_id": source_event_id,
    }


def validate_delivery_selection(
    a: argparse.Namespace,
    input_context: dict[str, object],
    *,
    tool: str,
    model: str,
) -> None:
    """Keep effective execution identity bound to an integrity-checked delivery."""
    if not input_context["delivery_id"]:
        return
    for field, effective in (("tool", tool), ("model", model)):
        if effective != getattr(a, field, ""):
            die(f"Workflow delivery {field} selection mismatch")


def _control_plane_enabled() -> bool:
    """The listener enables this gate; legacy direct handlers remain testable."""
    return os.environ.get("AWF_CONTROL_PLANE", "0") == "1"


def pre_invocation_gate(
    a: argparse.Namespace, role: str, evidence: RunEvidence | None
) -> object | None:
    """Persist and atomically authorize the stage before any model adapter call."""
    if not _control_plane_enabled():
        return None
    event_type = getattr(a, "input_type", "") or (
        "task:awf-review-v2" if role == "reviewer" else "task:awf-impl-v2"
    )
    task_id = a.branch.rsplit("/", 1)[-1]
    run_id = getattr(a, "run_id", "") or os.environ.get("AWF_RUN_ID") or f"task-{task_id}"
    stage = (
        getattr(a, "stage", "")
        or os.environ.get("AWF_STAGE")
        or ("review" if role == "reviewer" else "rework" if "rework" in event_type else "implement")
    )
    state_root = (
        evidence.state_dir
        if evidence is not None
        else Path(
            os.environ.get("AWF_STATE_ROOT", str(Path.home() / ".local/state/agent-workflow"))
        )
    )
    ledger = RunLedger(state_root, run_id)
    frozen_base = a.commit
    if ledger.ledger_path.exists():
        _, current_packet = ledger.recover()
        frozen_base = str(current_packet["frozen_base"])
    authority_path = Path(
        os.environ.get(
            "AWF_AUTHORITY_MANIFEST",
            str(Path(__file__).resolve().parent / "authority-manifest.example.json"),
        )
    )
    try:
        authority = authority_manifest_binding(load_authority_manifest(authority_path))
    except ControlPlaneDenied as exc:
        record(evidence, "pre_invocation_rejected", reason=str(exc))
        die(f"pre-invocation gate denied: {exc}")
    packet = build_context_packet(
        run_id=run_id,
        taskcard=a.card,
        frozen_base=frozen_base,
        branch=a.branch,
        pull_request=str(getattr(a, "pull_request", "")),
        phase=getattr(a, "phase", ""),
        transition=event_type,
        evidence=[str(getattr(a, "report", ""))],
        prohibited_actions=[
            "read historical event payloads",
            "ACK/requeue/redispatch preserved events",
            "credentials, destructive operations, or trust-gate bypass",
        ],
        authority_manifest=authority,
        next_action=f"run trusted {role} preflight for {event_type}",
        stage=stage,
        current_stage_evidence_commit=a.commit,
    )
    try:
        ledger.initialize(
            packet,
            stage=stage,
            max_attempts=int(
                getattr(a, "max_attempts", 1) or os.environ.get("AWF_MAX_ATTEMPTS", "1")
            ),
            rework_budget=int(
                getattr(a, "rework_budget", 1) or os.environ.get("AWF_REWORK_BUDGET", "1")
            ),
        )
        active_raw = os.environ.get("AWF_ACTIVE_ROUTE_TYPES", "")
        active_routes = DEFAULT_ROUTES
        if active_raw:
            active_routes = {item: [role] for item in active_raw.split(",") if item}
        decision = ledger.pre_invocation_gate(
            event_id=evidence.event_id if evidence is not None else int(getattr(a, "event_id", 1)),
            event_type=event_type,
            role=role,
            delivery_id=getattr(a, "delivery_id", "")
            or f"legacy-event-{getattr(a, 'event_id', 0)}",
            payload_sha256=getattr(a, "payload_sha256", "") or "legacy",
            stage=stage,
            route_override=getattr(a, "route_override", ""),
            attempt=int(getattr(a, "attempt", 1) or 1),
            rework="rework" in event_type,
            active_routes=active_routes,
            terminal_state=getattr(a, "terminal_state", ""),
            current_stage_evidence_commit=a.commit,
        )
    except ControlPlaneDenied as exc:
        record(evidence, "pre_invocation_rejected", reason=str(exc))
        die(f"pre-invocation gate denied: {exc}")
    if not decision.allowed and decision.reason != "duplicate_event":
        record(evidence, "pre_invocation_rejected", reason=decision.reason)
        die(f"pre-invocation gate denied: {decision.reason}")
    if decision.reason == "duplicate_event":
        record(evidence, "pre_invocation_replay", control_plane_sequence=decision.sequence)
    else:
        record(evidence, "pre_invocation_authorized", control_plane_sequence=decision.sequence)
    return decision


def delivery_state_path(
    evidence: RunEvidence,
    category: str,
    delivery_key: str,
) -> Path:
    if category not in {"checkpoint", "outbox", "inbox"}:
        die(f"invalid delivery state category {category!r}")
    digest = hashlib.sha256(delivery_key.encode("utf-8")).hexdigest()
    return evidence.state_dir / category / evidence.role / f"{digest}.json"


def delivery_has_durable_state(
    evidence: RunEvidence | None,
    input_context: dict[str, object],
) -> bool:
    """Return whether this delivery must use the durable replay path."""
    if evidence is None:
        return False
    delivery_key = str(input_context["key"])
    delivery_id = str(input_context["delivery_id"])
    return any(
        path.exists()
        for path in (
            delivery_state_path(evidence, "checkpoint", delivery_key),
            delivery_state_path(evidence, "outbox", delivery_key),
            delivery_state_path(evidence, "inbox", delivery_id),
        )
    )


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    with temp_path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp_path, path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _load_delivery_record(path: Path, label: str) -> dict[str, object] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        die(f"{label} state must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        die(f"{label} state is unreadable or invalid JSON")
    if not isinstance(value, dict):
        die(f"{label} state must be a JSON object")
    return value


_CODER_RECOVERY_PHASES = (
    "model_not_started",
    "model_started",
    "model_completed",
    "postflight_completed",
    "model_imported",
    "commit_created",
    "fork_sha_verified",
    "pr_tuple_verified",
    "outbox_prepared",
    "outbox_sent",
)
_REVIEWER_RECOVERY_PHASES = (
    "model_not_started",
    "model_started",
    "model_completed",
    "model_imported",
    "pr_tuple_verified",
    "outbox_prepared",
    "outbox_sent",
)
_RECOVERY_PHASES_BY_ROLE = {
    "coder": _CODER_RECOVERY_PHASES,
    "reviewer": _REVIEWER_RECOVERY_PHASES,
}


def _checkpoint_immutable(record_value: dict[str, object]) -> dict[str, object]:
    return {
        key: record_value.get(key)
        for key in (
            "format",
            "role",
            "input_key",
            "input_delivery_id",
            "input_payload_sha256",
            "input_source_event_id",
            "branch",
            "source_commit",
            "provenance",
        )
    }


def validate_recovery_checkpoint(record_value: dict[str, object]) -> None:
    if record_value.get("format") != "awf.recovery-checkpoint.v1":
        die("recovery checkpoint format is invalid")
    role = record_value.get("role")
    phases = _RECOVERY_PHASES_BY_ROLE.get(str(role))
    if phases is None:
        die("recovery checkpoint role is invalid")
    phase = record_value.get("phase")
    if phase not in phases:
        die("recovery checkpoint phase is invalid")
    if record_value.get("phase_index") != phases.index(str(phase)):
        die("recovery checkpoint phase index is inconsistent")
    for field in (
        "input_key",
        "input_delivery_id",
        "input_payload_sha256",
        "branch",
        "source_commit",
    ):
        if not isinstance(record_value.get(field), str) or not record_value[field]:
            die(f"recovery checkpoint {field} is invalid")
    if not isinstance(record_value.get("input_source_event_id"), int):
        die("recovery checkpoint source event ID is invalid")
    provenance = record_value.get("provenance")
    if not isinstance(provenance, dict):
        die("recovery checkpoint is missing PR provenance")
    if provenance.get("provenance_version") != "awf.pr-provenance.v1":
        die("recovery checkpoint PR provenance is invalid")
    facts = record_value.get("facts")
    if not isinstance(facts, dict):
        die("recovery checkpoint facts are invalid")


def begin_recovery_checkpoint(
    evidence: RunEvidence,
    input_context: dict[str, object],
    *,
    role: str,
    branch: str,
    source_commit: str,
    provenance: dict[str, object],
) -> tuple[Path, dict[str, object]]:
    path = delivery_state_path(evidence, "checkpoint", str(input_context["key"]))
    record_value: dict[str, object] = {
        "format": "awf.recovery-checkpoint.v1",
        "role": role,
        "input_key": input_context["key"],
        "input_delivery_id": input_context["delivery_id"],
        "input_payload_sha256": input_context["payload_sha256"],
        "input_source_event_id": input_context["source_event_id"],
        "branch": branch,
        "source_commit": source_commit,
        "provenance": provenance_payload(provenance),
        "phase": "model_not_started",
        "phase_index": 0,
        "facts": {},
        "updated_at": _utc_now(),
    }
    validate_recovery_checkpoint(record_value)
    existing = _load_delivery_record(path, "recovery checkpoint")
    if existing is not None:
        validate_recovery_checkpoint(existing)
        if _checkpoint_immutable(existing) != _checkpoint_immutable(record_value):
            die("existing recovery checkpoint does not match the current Workflow input")
        return path, existing
    _atomic_write_json(path, record_value)
    record(evidence, "recovery_checkpoint", recovery_phase="model_not_started")
    return path, record_value


def advance_recovery_checkpoint(
    evidence: RunEvidence,
    path: Path,
    record_value: dict[str, object],
    phase: str,
    **facts: object,
) -> dict[str, object]:
    validate_recovery_checkpoint(record_value)
    phases = _RECOVERY_PHASES_BY_ROLE[str(record_value["role"])]
    if phase not in phases:
        die("recovery checkpoint phase is invalid")
    current_index = int(record_value["phase_index"])
    next_index = phases.index(phase)
    if next_index < current_index or next_index > current_index + 1:
        die("recovery checkpoint transition is not monotonic")
    existing_facts = dict(record_value["facts"])
    if any(key in existing_facts and existing_facts[key] != value for key, value in facts.items()):
        die("recovery checkpoint replay tried to alter completed phase facts")
    if next_index == current_index:
        if not facts:
            return record_value
        updated = {
            **record_value,
            "facts": {**existing_facts, **facts},
            "updated_at": _utc_now(),
        }
        validate_recovery_checkpoint(updated)
        _atomic_write_json(path, updated)
        record(evidence, "recovery_checkpoint", recovery_phase=phase)
        return updated
    merged_facts = {**existing_facts, **facts}
    updated = {
        **record_value,
        "phase": phase,
        "phase_index": next_index,
        "facts": merged_facts,
        "updated_at": _utc_now(),
    }
    validate_recovery_checkpoint(updated)
    _atomic_write_json(path, updated)
    record(evidence, "recovery_checkpoint", recovery_phase=phase)
    return updated


def increment_postflight_attempt(
    evidence: RunEvidence,
    path: Path,
    record_value: dict[str, object],
) -> dict[str, object]:
    """Record a recoverable postflight retry without advancing stage or rework budgets."""
    validate_recovery_checkpoint(record_value)
    current = _load_delivery_record(path, "recovery checkpoint")
    if current is None:
        die("recovery checkpoint disappeared before postflight")
    validate_recovery_checkpoint(current)
    if _checkpoint_immutable(current) != _checkpoint_immutable(record_value):
        die("recovery checkpoint changed before postflight")
    if current.get("phase") != "model_completed":
        die("postflight attempts can only be recorded after model completion")
    facts = dict(current["facts"])
    attempts = int(facts.get("postflight_attempts", 0)) + 1
    updated = {
        **current,
        "facts": {**facts, "postflight_attempts": attempts},
        "updated_at": _utc_now(),
    }
    validate_recovery_checkpoint(updated)
    _atomic_write_json(path, updated)
    record(
        evidence,
        "recovery_checkpoint",
        recovery_phase="model_completed",
        postflight_attempts=attempts,
    )
    return updated


def recovery_model_policy(checkpoint: dict[str, object]) -> str:
    """Return the only permitted model action for a validated checkpoint."""
    validate_recovery_checkpoint(checkpoint)
    phase = str(checkpoint["phase"])
    if phase == "model_not_started":
        return "invoke_once"
    if phase == "model_started":
        return "recover_or_fail"
    return "skip"


def recover_legacy_publication_checkpoint(
    evidence: RunEvidence,
    input_context: dict[str, object],
    *,
    branch: str,
    source_commit: str,
    provenance: dict[str, object],
) -> tuple[Path, dict[str, object]] | None:
    """Import pre-checkpoint v3 publication evidence without repeating its model."""
    if not evidence.log_path.is_file():
        return None
    try:
        entries = [
            json.loads(line)
            for line in evidence.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        die("legacy recovery evidence is unreadable or invalid JSON")
    candidates = [
        item
        for item in entries
        if isinstance(item, dict)
        and item.get("event_id") == evidence.event_id
        and item.get("role") == "coder"
    ]
    postflight = next(
        (item for item in candidates if item.get("phase") == "postflight_pass"),
        None,
    )
    commits = [
        item
        for item in candidates
        if item.get("phase") == "commit" and item.get("commit_status") == "pass"
    ]
    remote = next(
        (item for item in candidates if item.get("phase") == "remote_sha_verified"),
        None,
    )
    imported_tree = postflight.get("imported_tree") if isinstance(postflight, dict) else None
    commit_sha = commits[-1].get("commit_sha") if commits else None
    remote_sha = remote.get("remote_sha") if isinstance(remote, dict) else None
    if (
        not isinstance(imported_tree, str)
        or not _FULL_COMMIT_RE.fullmatch(imported_tree)
        or not isinstance(commit_sha, str)
        or not _FULL_COMMIT_RE.fullmatch(commit_sha)
        or (remote is not None and remote_sha != commit_sha)
    ):
        return None
    required = [
        ("postflight_pass", "imported_tree", imported_tree),
        ("commit", "commit_sha", commit_sha),
    ]
    if remote is not None:
        required.append(("remote_sha_verified", "remote_sha", commit_sha))
    required.append(("fork_pr_rejected", "reason", "fork_push_or_pr_verification_failed"))
    position = -1
    for phase, field, expected in required:
        position = next(
            (
                index
                for index in range(position + 1, len(entries))
                if isinstance(entries[index], dict)
                and entries[index].get("event_id") == evidence.event_id
                and entries[index].get("role") == "coder"
                and entries[index].get("phase") == phase
                and entries[index].get(field) == expected
            ),
            -1,
        )
        if position < 0:
            return None
    path, checkpoint = begin_recovery_checkpoint(
        evidence,
        input_context,
        role="coder",
        branch=branch,
        source_commit=source_commit,
        provenance=provenance,
    )
    checkpoint = advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_started",
        model_workspace="legacy-durable-evidence",
    )
    checkpoint = advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_completed",
        model_workspace="legacy-durable-evidence",
    )
    checkpoint = advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "postflight_completed",
        postflight_attempts=1,
    )
    checkpoint = advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_imported",
        imported_tree=imported_tree,
        legacy_recovered=True,
    )
    checkpoint = advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "commit_created",
        commit_sha=commit_sha,
    )
    if remote is not None:
        checkpoint = advance_recovery_checkpoint(
            evidence,
            path,
            checkpoint,
            "fork_sha_verified",
            head_sha=commit_sha,
        )
    record(
        evidence,
        "legacy_recovery_checkpoint_imported",
        recovery_phase=str(checkpoint["phase"]),
    )
    return path, checkpoint


def recover_legacy_reviewer_checkpoint(
    evidence: RunEvidence,
    input_context: dict[str, object],
    *,
    branch: str,
    source_commit: str,
    provenance: dict[str, object],
) -> tuple[Path, dict[str, object]] | None:
    """Import one completed pre-checkpoint reviewer process without rerunning it."""
    if not evidence.log_path.is_file():
        return None
    try:
        entries = [
            json.loads(line)
            for line in evidence.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        die("legacy reviewer recovery evidence is unreadable or invalid JSON")
    candidates = [
        item
        for item in entries
        if isinstance(item, dict)
        and item.get("event_id") == evidence.event_id
        and item.get("role") == "reviewer"
    ]
    start_index = next(
        (
            index
            for index in range(len(candidates) - 1, -1, -1)
            if candidates[index].get("phase") == "opencode_start"
        ),
        -1,
    )
    if start_index < 0:
        return None
    start = candidates[start_index]
    exit_record = next(
        (item for item in candidates[start_index + 1 :] if item.get("phase") == "opencode_exit"),
        None,
    )
    model_workspace = start.get("opencode_cwd")
    if (
        not isinstance(exit_record, dict)
        or exit_record.get("opencode_rc") != 0
        or not isinstance(model_workspace, str)
        or not model_workspace
    ):
        return None
    workspace = Path(model_workspace).resolve()
    try:
        workspace.relative_to(evidence.run_dir.resolve())
    except ValueError:
        die("legacy reviewer workspace is outside the durable event state")
    if workspace.is_symlink() or not workspace.is_dir():
        die("legacy reviewer workspace is unavailable")
    manifest_sha256 = durable_model_manifest_sha256(str(workspace))
    path, checkpoint = begin_recovery_checkpoint(
        evidence,
        input_context,
        role="reviewer",
        branch=branch,
        source_commit=source_commit,
        provenance=provenance,
    )
    facts = {
        "model_workspace": str(workspace),
        "model_manifest_sha256": manifest_sha256,
        "model_event_id": evidence.event_id,
    }
    checkpoint = advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_started",
        **facts,
    )
    checkpoint = advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_completed",
        **facts,
    )
    record(
        evidence,
        "legacy_recovery_checkpoint_imported",
        recovery_phase="model_completed",
    )
    return path, checkpoint


def reconcile_recovery_checkpoint_with_outbox(
    evidence: RunEvidence,
    input_context: dict[str, object],
    outbox: dict[str, object],
) -> None:
    checkpoint_path = delivery_state_path(
        evidence,
        "checkpoint",
        str(input_context["key"]),
    )
    checkpoint = _load_delivery_record(checkpoint_path, "recovery checkpoint")
    if checkpoint is None:
        return
    validate_recovery_checkpoint(checkpoint)
    expected_bindings = {
        "input_key": input_context["key"],
        "input_delivery_id": input_context["delivery_id"],
        "input_payload_sha256": input_context["payload_sha256"],
        "input_source_event_id": input_context["source_event_id"],
        "branch": outbox.get("branch"),
        "source_commit": outbox.get("source_commit"),
    }
    if any(checkpoint.get(key) != value for key, value in expected_bindings.items()):
        die("outbox does not match its recovery checkpoint input")
    facts = dict(checkpoint["facts"])
    verified_provenance = facts.get("verified_provenance")
    role = checkpoint.get("role")
    action = outbox.get("action")
    expected_evidence_commit = (
        facts.get("head_sha") if role == "coder" else checkpoint.get("source_commit")
    )
    action_matches = (
        action == "coder.review_handoff"
        if role == "coder"
        else isinstance(action, str) and action.startswith("reviewer.")
    )
    if (
        outbox.get("format") != "awf.outbox.v2"
        or not action_matches
        or not isinstance(verified_provenance, dict)
        or outbox.get("provenance") != verified_provenance
        or outbox.get("evidence_commit") != expected_evidence_commit
    ):
        die("outbox does not match its verified recovery provenance")
    delivery_id = outbox.get("delivery_id")
    if checkpoint.get("phase") == "pr_tuple_verified":
        checkpoint = advance_recovery_checkpoint(
            evidence,
            checkpoint_path,
            checkpoint,
            "outbox_prepared",
            outbox_delivery_id=delivery_id,
        )
    elif checkpoint.get("phase") not in {"outbox_prepared", "outbox_sent"}:
        die("outbox does not match its recovery checkpoint phase")
    facts = dict(checkpoint["facts"])
    if facts.get("outbox_delivery_id") != delivery_id:
        die("outbox delivery does not match its recovery checkpoint")
    if outbox.get("status") == "sent":
        advance_recovery_checkpoint(
            evidence,
            checkpoint_path,
            checkpoint,
            "outbox_sent",
            outbox_delivery_id=delivery_id,
        )
    elif checkpoint.get("phase") == "outbox_sent":
        die("sent recovery checkpoint has no durable sent outbox")


def complete_inbox(
    evidence: RunEvidence | None,
    delivery_id: str,
    payload_sha256: str,
) -> None:
    if evidence is None or not delivery_id:
        return
    path = delivery_state_path(evidence, "inbox", delivery_id)
    existing = _load_delivery_record(path, "inbox")
    expected = {
        "format": "awf.inbox.v1",
        "role": evidence.role,
        "delivery_id": delivery_id,
        "payload_sha256": payload_sha256,
        "status": "completed",
    }
    if existing is not None and existing != expected:
        die("Workflow delivery ID was already completed with different input")
    _atomic_write_json(path, expected)


def inbox_completed(
    evidence: RunEvidence | None,
    delivery_id: str,
    payload_sha256: str,
) -> bool:
    if evidence is None or not delivery_id:
        return False
    existing = _load_delivery_record(delivery_state_path(evidence, "inbox", delivery_id), "inbox")
    if existing is None:
        return False
    if (
        existing.get("format") != "awf.inbox.v1"
        or existing.get("role") != evidence.role
        or existing.get("delivery_id") != delivery_id
        or existing.get("payload_sha256") != payload_sha256
        or existing.get("status") != "completed"
    ):
        die("Workflow delivery ID was already used with different input")
    return True


def _append_process_git_config(environment: dict[str, str], key: str, value: str) -> None:
    """Append one Git config entry to the child-only environment."""
    raw_count = environment.get("GIT_CONFIG_COUNT", "0")
    try:
        count = int(raw_count)
    except ValueError:
        die("inherited GIT_CONFIG_COUNT must be an integer")
    environment[f"GIT_CONFIG_KEY_{count}"] = key
    environment[f"GIT_CONFIG_VALUE_{count}"] = value
    environment["GIT_CONFIG_COUNT"] = str(count + 1)


_MODEL_ENV_ALLOWLIST = {
    "ALL_PROXY",
    "APPDATA",
    "COLORTERM",
    "COMSPEC",
    "CURL_CA_BUNDLE",
    "FORCE_COLOR",
    "HOMEDRIVE",
    "HOME",
    "HOMEPATH",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOCALAPPDATA",
    "LOGNAME",
    "NO_COLOR",
    "NO_PROXY",
    "NUMBER_OF_PROCESSORS",
    "OPENCODE_CONFIG",
    "OPENCODE_CONFIG_DIR",
    "OS",
    "PATH",
    "PATHEXT",
    "PI_CODING_AGENT_DIR",
    "PI_CODING_AGENT_SESSION_DIR",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "REQUESTS_CA_BUNDLE",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USER",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
}

_PROXY_ENV_KEYS = {"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"}


def _reject_credential_proxy(key: str, value: str) -> None:
    """Fail closed rather than expose proxy userinfo to an untrusted process."""
    parsed = urlsplit(value if "://" in value else f"//{value}")
    if parsed.username is not None or parsed.password is not None:
        die(f"{key.upper()} must not contain embedded credentials for model subprocesses")


def _model_base_env() -> dict[str, str]:
    """Build a minimal cross-platform environment for untrusted processes."""
    inherited = child_env()
    e: dict[str, str] = {}
    for key, value in inherited.items():
        upper = key.upper()
        if upper in _PROXY_ENV_KEYS:
            _reject_credential_proxy(key, value)
        if upper in _MODEL_ENV_ALLOWLIST or upper.startswith("LC_"):
            e[key] = value
    trusted_root = Path(__file__).resolve().parent.parent
    trusted_text = str(trusted_root)
    path_entries = []
    for entry in e.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if Path(entry).resolve().is_relative_to(trusted_root):
                continue
        except (OSError, RuntimeError):
            pass
        path_entries.append(entry)
    e["PATH"] = os.pathsep.join(path_entries)
    for key, value in list(e.items()):
        if key != "PATH" and trusted_text in value:
            del e[key]
    e.setdefault("PYTHONUTF8", "1")
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


def _prepare_model_git_guard(repo: str) -> tuple[Path, Path]:
    """Copy model-only Git guards outside both trusted and model checkouts."""
    repository = Path(repo).resolve()
    source = Path(__file__).resolve().parent
    guard_root = Path(
        tempfile.mkdtemp(prefix="model-git-guard-", dir=str(repository.parent))
    ).resolve()
    model_bin = guard_root / "model-bin"
    hooks = guard_root / "model-git-hooks"
    model_bin.mkdir()
    hooks.mkdir()
    for relative in ("git", "git.cmd", "model_git_guard.py"):
        shutil.copy2(source / "model-bin" / relative, model_bin / relative)
    shutil.copy2(source / "awf_executor.py", model_bin / "awf_executor.py")
    for relative in ("pre-commit", "pre-push"):
        shutil.copy2(source / "model-git-hooks" / relative, hooks / relative)
    return model_bin, hooks


def model_env(repo: str | None = None) -> dict[str, str]:
    """Environment for model subprocesses: allowlisted runtime state only.

    Keeps only required platform, path, proxy, locale, certificate, and UTF-8
    settings. Runner/Bus metadata, inherited Git config, cloud credentials, model
    provider keys, arbitrary secret variables, and executable injection variables
    never reach untrusted model processes (OpenCode, Codex, Pi).

    OpenCode and Pi configuration-directory pointers are preserved when they resolve
    outside the trusted Workflow repository because those CLIs own provider authentication
    and model catalogs. Pi still runs with ``--no-session``; its settings/config directory
    remains an explicit external runtime dependency rather than Workflow evidence.

    When a repository is supplied, process-scoped Git config denies every transport
    protocol in addition to ordinary commit/push hooks. Trusted postflight commands
    and runner-owned Git writes use separate environments and remain unaffected.
    """
    e = _model_base_env()
    if repo is not None:
        model_bin, hooks = _prepare_model_git_guard(repo)
        if (
            not Path(repo).is_dir()
            or not (hooks / "pre-commit").is_file()
            or not (hooks / "pre-push").is_file()
            or not (model_bin / "git").is_file()
            or not (model_bin / "git.cmd").is_file()
            or not (model_bin / "model_git_guard.py").is_file()
            or not (model_bin / "awf_executor.py").is_file()
        ):
            die("model Git write guard is unavailable")
        _append_process_git_config(e, "core.hooksPath", str(hooks))
        _append_process_git_config(e, "protocol.allow", "never")
        for protocol in ("ext", "file", "git", "http", "https", "ssh"):
            _append_process_git_config(e, f"protocol.{protocol}.allow", "never")
        _append_process_git_config(
            e,
            "remote.origin.pushurl",
            "awf-model-write-denied://origin",
        )
        _append_process_git_config(e, "credential.helper", "")
        e["PATH"] = str(model_bin) + os.pathsep + e.get("PATH", "")
        if os.name == "nt":
            candidates = [Path(sys.base_prefix) / "python.exe"]
        else:
            candidates = [
                Path(sys.base_prefix) / "bin/python3",
                Path(sys.base_prefix) / "bin/python3.12",
            ]
        base_python = next(
            (candidate for candidate in candidates if candidate.is_file()), Path(sys.executable)
        )
        e["AWF_PYTHON"] = str(base_python)
        if os.name == "nt":
            extensions = [part for part in e.get("PATHEXT", "").split(";") if part]
            extensions = [part for part in extensions if part.upper() != ".CMD"]
            e["PATHEXT"] = ";".join([".CMD", *extensions])
        e["AWF_REPO_DIR"] = str(Path(repo).resolve())
        e["PWD"] = str(Path(repo).resolve())
        e["INIT_CWD"] = str(Path(repo).resolve())
        e.pop("OLDPWD", None)
        for key in (
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_DIR",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_WORK_TREE",
        ):
            e.pop(key, None)
        e["GIT_TERMINAL_PROMPT"] = "0"
        e["GCM_INTERACTIVE"] = "Never"
        e["GIT_OPTIONAL_LOCKS"] = "0"
        e["NoDefaultCurrentDirectoryInExePath"] = "1"
    return e


def verification_env() -> dict[str, str]:
    """Credential-free environment for default-locale verification commands."""
    e = model_env()
    e.pop("PYTHONUTF8", None)
    e["PYTHONIOENCODING"] = "utf-8"
    return e


_CAPTURED_STDOUT_MAX_BYTES = 16 * 1024


def read_bounded_stdout(proc, max_bytes: int = _CAPTURED_STDOUT_MAX_BYTES) -> tuple[str, bool]:
    """Drain one text stdout pipe and kill the child if it exceeds the report bound."""
    if proc.stdout is None:
        die("captured model stdout pipe is unavailable")
    chunks: list[str] = []
    size = 0
    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            break
        size += len(chunk.encode("utf-8"))
        if size > max_bytes:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            return "", True
        chunks.append(chunk)
    proc.wait()
    return "".join(chunks), False


def spawn(
    argv: list[str],
    *,
    cwd: str | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    evidence: RunEvidence | None = None,
    tracked_phase: str | None = None,
    stdout_path: str | None = None,
) -> int:
    """Run a command as a real argv (no shell). Handles Windows .cmd/.bat shims.

    Returns the process exit code. ``stdin``, if given, is fed to the process via
    ``input=``. When no explicit input is provided the child receives
    ``subprocess.DEVNULL`` instead of inheriting the handler's stdin, which is
    unreliable (especially on Windows).

    ``env`` defaults to ``child_env()`` (full parent environment). Pass
    ``model_env()`` for model subprocesses to strip credentials.
    """
    if stdout_path is not None and stdin is not None:
        die("captured model stdout cannot be combined with explicit stdin")
    executable = Path(argv[0]).name if argv else "<empty>"
    log(f"exec: {executable} argc={len(argv)}")
    if evidence is not None and tracked_phase is not None:
        started = time.monotonic()
        try:
            proc = start_command(
                argv,
                cwd=cwd,
                stdin=PIPE if stdin is not None else DEVNULL,
                stdout=PIPE if stdout_path is not None else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env or child_env(),
                allow_shell_wrapper=True,
            )
        except ExecutionFailure as exc:
            record(
                evidence,
                f"{tracked_phase}_exit",
                **{
                    f"{tracked_phase}_rc": None,
                    f"{tracked_phase}_duration_seconds": round(time.monotonic() - started, 6),
                    f"{tracked_phase}_spawn_error": type(exc).__name__,
                },
            )
            raise
        record(
            evidence,
            f"{tracked_phase}_start",
            **{
                f"{tracked_phase}_pid": proc.pid,
                f"{tracked_phase}_cwd": str(Path(cwd).resolve()) if cwd else os.getcwd(),
            },
        )
        try:
            if stdout_path is not None:
                stdout_text, stdout_limit_exceeded = read_bounded_stdout(proc)
            else:
                proc.communicate(stdin)
                stdout_text = ""
                stdout_limit_exceeded = False
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            record(
                evidence,
                f"{tracked_phase}_exit",
                **{
                    f"{tracked_phase}_rc": proc.poll(),
                    f"{tracked_phase}_duration_seconds": round(time.monotonic() - started, 6),
                    f"{tracked_phase}_interrupted": True,
                },
            )
            raise
        record(
            evidence,
            f"{tracked_phase}_exit",
            **{
                f"{tracked_phase}_rc": proc.returncode,
                f"{tracked_phase}_duration_seconds": round(time.monotonic() - started, 6),
                **(
                    {f"{tracked_phase}_stdout_limit_exceeded": True}
                    if stdout_limit_exceeded
                    else {}
                ),
            },
        )
        if stdout_limit_exceeded:
            die("captured model stdout exceeds 16 KiB")
        if stdout_path is not None and proc.returncode == 0:
            atomic_write_text(Path(stdout_path), stdout_text or "")
        return proc.returncode
    if stdout_path is not None:
        proc = start_command(
            argv,
            cwd=cwd,
            stdin=DEVNULL,
            stdout=PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env or child_env(),
            allow_shell_wrapper=True,
        )
        stdout_text, stdout_limit_exceeded = read_bounded_stdout(proc)
        if stdout_limit_exceeded:
            die("captured model stdout exceeds 16 KiB")
        if proc.returncode == 0:
            atomic_write_text(Path(stdout_path), stdout_text)
        return proc.returncode
    proc = run_command(
        argv,
        cwd=cwd,
        input=stdin,
        stdin=DEVNULL if stdin is None else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env or child_env(),
        allow_shell_wrapper=True,
    )
    return proc.returncode


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically write trusted UTF-8 text output to one exact path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    with temp_path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp_path, path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def git(repo: str, *args: str) -> int:
    return spawn(["git", "-C", repo, *args])


def git_out(repo: str, *args: str) -> str:
    proc = run_command(
        ["git", "-C", repo, *args],
        text=True,
        capture_output=True,
        stdin=DEVNULL,
        encoding="utf-8",
        errors="replace",
        env=child_env(),
    )
    # Use rstrip to preserve leading space in porcelain format
    # (e.g. " M a.py" — leading space means unmodified in index)
    return proc.stdout.rstrip("\n\r")


_MODEL_GIT_MANIFESTS: dict[str, dict[str, tuple[str, str]]] = {}


def _model_git_manifest(
    workspace: str,
    *,
    include_semantic_index: bool = True,
) -> dict[str, tuple[str, str]]:
    """Hash mutable Git control metadata without invoking model-controlled Git."""
    git_dir = Path(workspace).resolve() / ".git"
    if not git_dir.is_dir():
        die("isolated model workspace Git directory is unavailable")
    manifest: dict[str, tuple[str, str]] = {}
    for path in sorted(git_dir.rglob("*")):
        relative = path.relative_to(git_dir)
        parts = relative.parts
        if parts and parts[0] == "objects" and parts[:2] != ("objects", "info"):
            continue
        # The binary index contains platform-specific stat-cache data.  That
        # cache can change after a read-only checkout/status operation without
        # changing the staged tree, which made durable recovery reject an
        # otherwise identical reviewer workspace on Windows.  Bind the
        # semantic index state below instead of the volatile binary file.
        if relative.as_posix() == "index":
            continue
        name = relative.as_posix()
        if path.is_symlink():
            manifest[name] = ("symlink", os.readlink(path))
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest[name] = ("file", digest)
        elif path.is_dir():
            manifest[name] = ("dir", "")
        else:
            manifest[name] = ("other", "")
    if include_semantic_index:
        staged = git_out(workspace, "ls-files", "--stage", "-z")
        tree = git_out(workspace, "write-tree")
        manifest["index-semantic"] = (
            "git-index",
            hashlib.sha256(staged.encode("utf-8") + b"\0" + tree.encode("ascii")).hexdigest(),
        )
    return manifest


def freeze_model_git_metadata(workspace: str) -> None:
    """Record the trusted pre-model Git control state in runner memory."""
    resolved = str(Path(workspace).resolve())
    _MODEL_GIT_MANIFESTS[resolved] = _model_git_manifest(resolved)


def assert_model_git_metadata(workspace: str) -> None:
    """Reject any model mutation to Git config, refs, index, hooks, or info files."""
    resolved = str(Path(workspace).resolve())
    expected = _MODEL_GIT_MANIFESTS.get(resolved)
    if expected is None:
        die("model process changed isolated workspace Git control metadata")
    expected_control = {key: value for key, value in expected.items() if key != "index-semantic"}
    current_control = _model_git_manifest(resolved, include_semantic_index=False)
    if current_control != expected_control or _model_git_manifest(resolved) != expected:
        die("model process changed isolated workspace Git control metadata")


def durable_model_manifest_sha256(workspace: str) -> str:
    manifest = _model_git_manifest(str(Path(workspace).resolve()))
    serializable = {key: list(value) for key, value in manifest.items()}
    return canonical_payload_sha256(serializable)


def _postflight_was_completed(evidence: RunEvidence) -> bool:
    """Recognize a completed trusted postflight boundary from durable evidence."""
    try:
        entries = [
            json.loads(line)
            for line in evidence.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        die("model recovery evidence is unreadable or invalid JSON")
    return any(
        isinstance(item, dict)
        and item.get("event_id") == evidence.event_id
        and item.get("role") == evidence.role
        and item.get("phase") == "postflight_pass"
        for item in entries
    )


def recover_postflight_manifest(
    evidence: RunEvidence,
    checkpoint_path: Path,
    checkpoint: dict[str, object],
    workspace: str,
) -> tuple[dict[str, object], str]:
    """Persist a legacy postflight manifest only after durable success evidence."""
    facts = dict(checkpoint.get("facts", {}))
    existing = facts.get("postflight_model_manifest_sha256")
    if isinstance(existing, str):
        current = durable_model_manifest_sha256(workspace)
        if current == existing:
            return checkpoint, existing
        # Checkpoints written before semantic index manifests used the raw
        # binary index.  Migrate only a completed reviewer workspace whose
        # dispatched HEAD and preserved ReviewReport still match the durable
        # facts; no model or artifact rewrite is involved.
        report_sha = facts.get("review_report_sha256")
        report_files = sorted(Path(workspace).glob(".awf/artifacts/review-report-*.md"))
        matching_report = any(
            isinstance(report_sha, str)
            and hashlib.sha256(path.read_bytes()).hexdigest() == report_sha
            for path in report_files
        )
        if (
            str(checkpoint.get("phase")) in {"model_imported", "pr_tuple_verified"}
            and git_out(workspace, "rev-parse", "--verify", "HEAD^{commit}")
            == checkpoint.get("source_commit")
            and matching_report
        ):
            migrated_facts = {
                **facts,
                "legacy_postflight_model_manifest_sha256": existing,
                "postflight_model_manifest_sha256": current,
            }
            migrated = {
                **checkpoint,
                "facts": migrated_facts,
                "updated_at": _utc_now(),
            }
            validate_recovery_checkpoint(migrated)
            _atomic_write_json(checkpoint_path, migrated)
            record(
                evidence,
                "recovery_checkpoint",
                recovery_phase=str(checkpoint["phase"]),
                manifest_migration="semantic-index-v1",
            )
            return migrated, current
        return checkpoint, existing
    phases = _RECOVERY_PHASES_BY_ROLE[str(checkpoint["role"])]
    if str(checkpoint["phase"]) == "model_completed":
        original = facts.get("model_manifest_sha256")
        if isinstance(original, str):
            return checkpoint, original
    if phases.index(str(checkpoint["phase"])) < phases.index("model_imported"):
        die("completed model checkpoint is missing its postflight Git manifest")
    if not _postflight_was_completed(evidence):
        die("completed model checkpoint lacks durable postflight success evidence")
    manifest = durable_model_manifest_sha256(workspace)
    checkpoint = advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        str(checkpoint["phase"]),
        postflight_model_manifest_sha256=manifest,
    )
    return checkpoint, manifest


def restore_durable_model_manifest(
    evidence: RunEvidence,
    workspace: str,
    expected_sha256: str,
) -> str:
    resolved = Path(workspace).resolve()
    state_root = evidence.state_dir.resolve()
    if (
        resolved == state_root
        or state_root not in resolved.parents
        or not resolved.name.startswith("model-workspace-")
        or not resolved.is_dir()
        or resolved.is_symlink()
    ):
        die("durable model workspace is outside the Workflow state root")
    manifest = _model_git_manifest(str(resolved))
    serializable = {key: list(value) for key, value in manifest.items()}
    if canonical_payload_sha256(serializable) != expected_sha256:
        die("durable model workspace Git metadata does not match its checkpoint")
    _MODEL_GIT_MANIFESTS[str(resolved)] = manifest
    return str(resolved)


def recover_completed_model_checkpoint(
    evidence: RunEvidence,
    checkpoint_path: Path,
    checkpoint: dict[str, object],
) -> dict[str, object] | None:
    if checkpoint.get("phase") != "model_started":
        return checkpoint
    facts = dict(checkpoint.get("facts", {}))
    workspace = facts.get("model_workspace")
    manifest_sha256 = facts.get("model_manifest_sha256")
    model_event_id = facts.get("model_event_id")
    model_process = facts.get("model_process", "opencode")
    checkpoint_role = checkpoint.get("role")
    if (
        not isinstance(workspace, str)
        or not isinstance(manifest_sha256, str)
        or not isinstance(model_event_id, int)
        or model_process not in {"opencode", "codex", "pi"}
        or checkpoint_role not in _RECOVERY_PHASES_BY_ROLE
        or evidence.role != checkpoint_role
        or not evidence.log_path.is_file()
    ):
        return None
    try:
        entries = [
            json.loads(line)
            for line in evidence.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        die("model recovery evidence is unreadable or invalid JSON")
    started = -1
    completed = -1
    for index, item in enumerate(entries):
        if (
            isinstance(item, dict)
            and item.get("event_id") == model_event_id
            and item.get("role") == checkpoint_role
            and item.get("phase") == f"{model_process}_start"
        ):
            started = index
        if (
            started >= 0
            and index > started
            and isinstance(item, dict)
            and item.get("event_id") == model_event_id
            and item.get("role") == checkpoint_role
            and item.get("phase") == f"{model_process}_exit"
            and item.get(f"{model_process}_rc") == 0
        ):
            completed = index
            break
    if completed < 0:
        return None
    restored = restore_durable_model_manifest(
        evidence,
        workspace,
        manifest_sha256,
    )
    return advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_completed",
        model_workspace=restored,
        model_manifest_sha256=manifest_sha256,
        model_event_id=model_event_id,
        model_process=model_process,
        recovered_from_process_log=True,
    )


def postflight_git_env() -> dict[str, str]:
    """Credential-free environment for Git reads of model-controlled worktrees."""
    e = _model_base_env()
    e["GIT_CONFIG_NOSYSTEM"] = "1"
    e["GIT_CONFIG_GLOBAL"] = os.devnull
    e["GIT_TERMINAL_PROMPT"] = "0"
    e["GCM_INTERACTIVE"] = "Never"
    e["GIT_OPTIONAL_LOCKS"] = "0"
    _append_process_git_config(e, "core.fsmonitor", "false")
    _append_process_git_config(e, "core.hooksPath", os.devnull)
    _append_process_git_config(e, "credential.helper", "")
    _append_process_git_config(e, "core.autocrlf", "true" if os.name == "nt" else "false")
    return e


def postflight_git(workspace: str, *args: str, capture: bool = False) -> CompletedProcess:
    """Run trusted Git plumbing on a frozen model workspace without credentials."""
    return run_command(
        ["git", "-C", workspace, *args],
        stdin=DEVNULL,
        stdout=PIPE if capture else DEVNULL,
        stderr=PIPE if capture else DEVNULL,
        env=postflight_git_env(),
    )


def postflight_git_out(workspace: str, *args: str) -> str:
    """Return credential-free Git output from a model-controlled worktree."""
    proc = postflight_git(workspace, *args, capture=True)
    if proc.returncode != 0:
        die("credential-free model workspace Git read failed")
    return proc.stdout.decode("utf-8", errors="replace").rstrip("\n\r")


def bounded_postflight_git_out(workspace: str, max_bytes: int, *args: str) -> str:
    """Return one credential-free Git read while bounding captured text."""
    proc = start_command(
        ["git", "-C", workspace, *args],
        stdin=DEVNULL,
        stdout=PIPE,
        stderr=DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=postflight_git_env(),
    )
    output, exceeded = read_bounded_stdout(proc, max_bytes=max_bytes)
    if exceeded:
        die(f"credential-free model workspace Git output exceeds {max_bytes} bytes")
    if proc.returncode != 0:
        die("credential-free model workspace Git read failed")
    return output.rstrip("\n\r")


def prepare_model_workspace(
    source_repo: str,
    expected_commit: str,
    *,
    state_dir: Path | None = None,
    workspace_prefix: str = "model-workspace-",
) -> str:
    """Create a fresh no-remote clone for one untrusted model invocation."""
    parent = str(state_dir) if state_dir is not None else None
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=workspace_prefix, dir=parent)).resolve()
    clone = run_command(
        ["git", "clone", "--no-hardlinks", "--no-checkout", source_repo, str(workspace)],
        stdin=DEVNULL,
        capture_output=True,
        env=child_env(),
    )
    if clone.returncode != 0:
        die("failed to create isolated model workspace")
    if git(str(workspace), "remote", "remove", "origin") != 0:
        die("failed to remove model workspace remote")
    if git(str(workspace), "config", "core.logAllRefUpdates", "false") != 0:
        die("failed to disable model workspace reflogs")
    if git(str(workspace), "checkout", "--detach", expected_commit) != 0:
        die("failed to checkout dispatched commit in model workspace")
    git_dir = workspace / ".git"
    logs = git_dir / "logs"
    if logs.exists():
        shutil.rmtree(logs)
    fetch_head = git_dir / "FETCH_HEAD"
    if fetch_head.exists():
        fetch_head.unlink()
    if logs.exists() or fetch_head.exists():
        die("failed to remove model workspace source metadata")
    head = git_out(str(workspace), "rev-parse", "--verify", "HEAD^{commit}")
    if head != expected_commit:
        die("model workspace does not match the dispatched commit")
    if git_out(str(workspace), "remote"):
        die("model workspace must not have a Git remote")
    freeze_model_git_metadata(str(workspace))
    return str(workspace)


def assert_model_workspace_state(workspace: str, expected_commit: str) -> None:
    """Reject model-created refs or remotes before importing any file delta."""
    assert_model_git_metadata(workspace)
    head = git_out(workspace, "rev-parse", "--verify", "HEAD^{commit}")
    if head != expected_commit:
        die("model process changed isolated workspace HEAD")
    if git_out(workspace, "remote"):
        die("model process added a Git remote to the isolated workspace")


def import_model_delta(workspace: str, trusted_repo: str) -> str:
    """Apply the verified workspace tree delta to the trusted checkout."""
    assert_model_git_metadata(workspace)
    staged = postflight_git(workspace, "add", "-A")
    if staged.returncode != 0:
        die("failed to stage the isolated model delta")
    model_tree_proc = postflight_git(workspace, "write-tree", capture=True)
    base_tree_proc = postflight_git(workspace, "rev-parse", "HEAD^{tree}", capture=True)
    if model_tree_proc.returncode != 0 or base_tree_proc.returncode != 0:
        die("failed to resolve isolated model trees")
    model_tree = model_tree_proc.stdout.decode("utf-8", errors="replace").strip()
    base_tree = base_tree_proc.stdout.decode("utf-8", errors="replace").strip()
    if not model_tree or model_tree == base_tree:
        die("isolated model workspace has no importable changes")

    diff = postflight_git(
        workspace,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--cached",
        "--binary",
        "--full-index",
        "HEAD",
        capture=True,
    )
    if diff.returncode != 0 or not diff.stdout:
        die("failed to serialize the isolated model delta")
    applied = run_command(
        ["git", "-C", trusted_repo, "apply", "--index", "--binary", "-"],
        input=diff.stdout,
        stdout=DEVNULL,
        stderr=DEVNULL,
        env=child_env(),
    )
    if applied.returncode != 0:
        die("failed to import the isolated model delta")
    trusted_tree = git_out(trusted_repo, "write-tree")
    if trusted_tree != model_tree:
        die("imported trusted tree does not match the verified model tree")
    return model_tree


def stage_model_artifact(workspace: str, relative_path: str, label: str) -> Path:
    """Force-add one configured artifact even when the target repository ignores it."""
    source = resolve_repo_file(workspace, relative_path, label)
    if not source.is_file():
        die(f"isolated model did not create the requested {label}")
    assert_model_git_metadata(workspace)
    staged = postflight_git(workspace, "add", "-f", "--", relative_path)
    if staged.returncode != 0:
        die(f"failed to stage the isolated {label}")
    freeze_model_git_metadata(workspace)
    return source


def import_model_report(workspace: str, trusted_repo: str, report_path: str) -> Path:
    """Copy the sole reviewer output from an isolated workspace."""
    normalize_machine_review_envelope(workspace, report_path)
    source = stage_model_artifact(workspace, report_path, "ReviewReport")
    delta_paths = _collect_delta_paths(workspace)
    if delta_paths != [report_path]:
        die("isolated reviewer may only create the requested ReviewReport")
    destination = resolve_repo_file(trusted_repo, report_path, "ReviewReport")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination


def mark_artifact_invalid(
    evidence: RunEvidence | None,
    checkpoint_path: Path | None,
    checkpoint: dict[str, object] | None,
    reason: str,
) -> dict[str, object] | None:
    """Persist a bounded same-delivery artifact diagnosis without recovery."""
    if checkpoint is None or checkpoint_path is None:
        return checkpoint
    facts = dict(checkpoint.get("facts", {}))
    attempts = int(facts.get("artifact_correction_attempts", 0))
    if attempts >= 1:
        die(
            "artifact_invalid recovery is exhausted; preserve the bound report SHA and "
            "provenance, then obtain an owner-authorized replacement delivery"
        )
    return advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        str(checkpoint["phase"]),
        artifact_status="artifact_invalid",
        artifact_correction_attempts=attempts + 1,
        artifact_error=reason[:512],
    )


def resolve_review_base(repo: str, base: str) -> str:
    """Resolve a local or origin-qualified reviewer base to one commit."""
    candidates = []
    if "/" not in base:
        candidates.append(f"origin/{base}")
    candidates.append(base)
    for candidate in candidates:
        commit = git_out(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}")
        if commit:
            return commit
    die(f"review base ref does not resolve: {base}")


def push_and_verify_remote_head(repo: str, branch: str) -> str:
    """Push ``branch`` and return HEAD only after the exact remote ref matches it."""
    if git(repo, "push", "-u", "origin", branch) != 0:
        die("push failed (reviewer will not see the changes)")

    remote_ref = f"refs/remotes/origin/{branch}"
    refspec = f"+refs/heads/{branch}:{remote_ref}"
    if git(repo, "fetch", "--no-tags", "origin", refspec) != 0:
        die(f"failed to refresh origin/{branch} after push")

    local_head = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
    remote_head = git_out(repo, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    if not local_head:
        die("failed to resolve local HEAD after push")
    if not remote_head:
        die(f"failed to resolve refreshed origin/{branch} after push")
    if remote_head != local_head:
        die(f"refreshed origin/{branch} does not match local HEAD; reviewer handoff blocked")
    log(f"pushed and verified origin/{branch} at {local_head}")
    return local_head


def _gh_json(repo: str, *args: str) -> object:
    gh = env("AWF_GH_BIN", "gh")
    try:
        completed = run_command(
            [gh, *args],
            cwd=repo,
            env=child_env(),
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except ExecutionFailure:
        die("trusted GitHub CLI operation failed")
    if completed.returncode != 0:
        die("trusted GitHub CLI operation failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        die("trusted GitHub CLI returned invalid JSON")


def _gh_create_pull_request(repo: str, provenance: dict[str, object]) -> int:
    gh = env("AWF_GH_BIN", "gh")
    upstream_repo = str(provenance["upstream_repo"])
    head_owner = str(provenance["head_repo"]).split("/", 1)[0]
    try:
        completed = run_command(
            [
                gh,
                "pr",
                "create",
                "--repo",
                upstream_repo,
                "--base",
                str(provenance["base_ref"]),
                "--head",
                f"{head_owner}:{provenance['head_ref']}",
                "--title",
                f"Agent Workflow contribution: {provenance['head_ref']}",
                "--body",
                "Published by the trusted Agent Workflow runner for independent review.",
            ],
            cwd=repo,
            env=child_env(),
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except ExecutionFailure:
        die("trusted GitHub CLI operation failed")
    if completed.returncode != 0:
        die("trusted GitHub CLI operation failed")
    output = completed.stdout.strip()
    parsed = urlsplit(output)
    path_prefix = f"/{upstream_repo}/pull/"
    number_text = parsed.path.removeprefix(path_prefix)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(path_prefix)
        or "/" in number_text
        or not number_text.isdigit()
        or int(number_text) < 1
    ):
        die("trusted GitHub CLI returned an invalid pull request URL")
    return int(number_text)


def verify_pr_head(
    repo: str,
    provenance: dict[str, object],
    *,
    allow_merged: bool = False,
) -> dict[str, object]:
    pull_request = int(provenance["pull_request"])
    data = _gh_json(
        repo,
        "pr",
        "view",
        str(pull_request),
        "--repo",
        str(provenance["upstream_repo"]),
        "--json",
        "number,state,baseRefName,baseRefOid,headRefName,headRefOid,headRepository,headRepositoryOwner",
    )
    if not isinstance(data, dict):
        die("trusted GitHub CLI returned an invalid pull request")
    head_repository = data.get("headRepository")
    head_owner = data.get("headRepositoryOwner")
    live_head_repo = ""
    if isinstance(head_repository, dict) and isinstance(head_owner, dict):
        name = head_repository.get("name")
        owner = head_owner.get("login")
        if isinstance(name, str) and isinstance(owner, str):
            live_head_repo = f"{owner}/{name}"
    expected = {
        "number": pull_request,
        "baseRefName": provenance["base_ref"],
        "baseRefOid": provenance["base_sha"],
        "headRefName": provenance["head_ref"],
        "headRefOid": provenance["head_sha"],
    }
    for field, value in expected.items():
        if data.get(field) != value:
            die(f"pull request {field} does not match persisted provenance")
    allowed_states = {"OPEN", "MERGED"} if allow_merged else {"OPEN"}
    if data.get("state") not in allowed_states:
        die("pull request state does not match persisted provenance")
    if live_head_repo != provenance["head_repo"]:
        die("pull request head repository does not match persisted provenance")
    return provenance


def ensure_pull_request(
    repo: str,
    provenance: dict[str, object],
) -> dict[str, object]:
    matches = _gh_json(
        repo,
        "pr",
        "list",
        "--repo",
        str(provenance["upstream_repo"]),
        "--state",
        "open",
        "--base",
        str(provenance["base_ref"]),
        "--head",
        str(provenance["head_ref"]),
        "--json",
        "number",
        "--limit",
        "2",
    )
    if not isinstance(matches, list) or len(matches) > 1:
        die("cannot select one matching pull request")
    if not matches:
        matches = [{"number": _gh_create_pull_request(repo, provenance)}]
    if (
        not isinstance(matches, list)
        or len(matches) != 1
        or not isinstance(matches[0], dict)
        or not isinstance(matches[0].get("number"), int)
    ):
        die("pull request creation or lookup did not yield exactly one pull request")
    result = {**provenance, "pull_request": matches[0]["number"]}
    return verify_pr_head(repo, result)


def push_and_verify_fork_head(
    repo: str,
    provenance: dict[str, object],
) -> dict[str, object]:
    head_remote = str(provenance["head_remote"])
    head_ref = str(provenance["head_ref"])
    local_head = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
    if not _FULL_COMMIT_RE.fullmatch(local_head):
        die("failed to resolve local HEAD before fork push")
    if git(repo, "push", "-u", head_remote, f"HEAD:refs/heads/{head_ref}") != 0:
        die("fork push failed; upstream write access is neither required nor tested")
    remote_ref = f"refs/remotes/{head_remote}/{head_ref}"
    refspec = f"+refs/heads/{head_ref}:{remote_ref}"
    if git(repo, "fetch", "--no-tags", head_remote, refspec) != 0:
        die("failed to freshly verify the contribution fork ref")
    remote_head = git_out(repo, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    if remote_head != local_head:
        die("fresh contribution fork SHA does not match trusted local HEAD")
    return {**provenance, "head_sha": local_head}


def push_and_verify_pr_head(
    repo: str,
    provenance: dict[str, object],
) -> dict[str, object]:
    return ensure_pull_request(repo, push_and_verify_fork_head(repo, provenance))


def verify_upstream_base(
    repo: str,
    provenance: dict[str, object],
) -> None:
    upstream_remote = str(provenance["upstream_remote"])
    base_ref = str(provenance["base_ref"])
    base_tracking = f"refs/remotes/{upstream_remote}/{base_ref}"
    if (
        git(
            repo,
            "fetch",
            "--no-tags",
            upstream_remote,
            f"+refs/heads/{base_ref}:{base_tracking}",
        )
        != 0
    ):
        die("cannot fetch the trusted upstream base")
    live_base = git_out(repo, "rev-parse", "--verify", f"{base_tracking}^{{commit}}")
    persisted_base = str(provenance["base_sha"])
    if live_base != persisted_base and (
        git(repo, "merge-base", "--is-ancestor", persisted_base, live_base) != 0
    ):
        die("trusted upstream base diverged from persisted provenance")


def verify_pr_remote_tuple(
    repo: str,
    provenance: dict[str, object],
    *,
    verify_pr: bool,
    allow_merged: bool = False,
) -> None:
    verify_upstream_base(repo, provenance)
    head_remote = str(provenance["head_remote"])
    head_ref = str(provenance["head_ref"])
    head_tracking = f"refs/remotes/{head_remote}/{head_ref}"
    if (
        git(
            repo,
            "fetch",
            "--no-tags",
            head_remote,
            f"+refs/heads/{head_ref}:{head_tracking}",
        )
        != 0
    ):
        die("cannot fetch the trusted contribution head")
    live_head = git_out(repo, "rev-parse", "--verify", f"{head_tracking}^{{commit}}")
    if live_head != provenance["head_sha"]:
        die("trusted contribution head SHA does not match persisted provenance")
    if verify_pr:
        verify_pr_head(repo, provenance, allow_merged=allow_merged)


def fetch_and_checkout_pr_head(
    repo: str,
    provenance: dict[str, object],
    *,
    verify_pr: bool,
    allow_merged: bool = False,
) -> None:
    verify_pr_remote_tuple(
        repo,
        provenance,
        verify_pr=verify_pr,
        allow_merged=allow_merged,
    )
    head_remote = str(provenance["head_remote"])
    head_ref = str(provenance["head_ref"])
    head_tracking = f"refs/remotes/{head_remote}/{head_ref}"
    dirty = git_out(repo, "status", "--porcelain")
    if dirty:
        die("working tree is dirty; commit, stash, or clean it before retrying")
    local_ref = f"refs/heads/{head_ref}"
    if git(repo, "show-ref", "--verify", "--quiet", local_ref) == 0:
        ahead = git_out(repo, "rev-list", "--count", f"{head_tracking}..{head_ref}")
        if not ahead.isdigit() or int(ahead) > 0:
            die("local contribution branch has unpushed commits; refusing to overwrite it")
    if git(repo, "checkout", "-q", "-B", head_ref, head_tracking) != 0:
        die("cannot checkout the exact trusted contribution head")
    if git_out(repo, "rev-parse", "--verify", "HEAD^{commit}") != provenance["head_sha"]:
        die("checked out contribution head does not match persisted provenance")


def fetch_dispatched_commit(repo: str, branch: str, expected_commit: str) -> str:
    """Fetch one legacy delivery without reading or changing the source working tree."""
    if git(repo, "check-ref-format", "--branch", branch) != 0:
        die(f"invalid task branch {branch!r}")
    if not _COMMIT_RE.fullmatch(expected_commit):
        die("event commit must be a 7-64 character hexadecimal Git object ID")
    remote_ref = f"refs/remotes/origin/{branch}"
    refspec = f"+refs/heads/{branch}:{remote_ref}"
    if git(repo, "fetch", "--quiet", "origin", refspec) != 0:
        die("cannot fetch the dispatched task ref from origin")
    resolved_expected = git_out(repo, "rev-parse", "--verify", f"{expected_commit}^{{commit}}")
    remote_head = git_out(repo, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    if not resolved_expected:
        die(f"event commit {expected_commit} is not available after fetch")
    if remote_head != resolved_expected:
        die(
            f"origin/{branch} changed after dispatch; expected {resolved_expected}, "
            f"found {remote_head}"
        )
    return resolved_expected


def prepare_terminal_workspace(
    repo: str,
    branch: str,
    expected_commit: str,
    *,
    provenance: dict[str, object] | None,
    evidence: RunEvidence | None,
) -> str:
    """Materialize one read-only, event-scoped workspace for terminal verification.

    The listener's configured repository is only a trusted object source. Its index,
    branch, and working tree are never inspected or changed, so operator files and a
    coder/reviewer checkout cannot turn a healthy decision into a handler failure.
    """
    state_dir = evidence.run_dir if evidence is not None else None
    parent = str(state_dir) if state_dir is not None else None
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(
        tempfile.mkdtemp(prefix="terminal-workspace-", dir=parent)
    ).resolve()
    clone = run_command(
        ["git", "clone", "--no-hardlinks", "--no-checkout", repo, str(workspace_path)],
        stdin=DEVNULL,
        capture_output=True,
        env=child_env(),
    )
    if clone.returncode != 0:
        die("failed to create isolated terminal workspace")
    workspace = str(workspace_path)
    if git(workspace, "remote", "remove", "origin") != 0:
        die("failed to detach terminal workspace from the source checkout")

    if provenance is not None:
        remote_names = {
            str(provenance["upstream_remote"]),
            str(provenance["head_remote"]),
        }
        for remote_name in sorted(remote_names):
            remote_url = git_out(repo, "remote", "get-url", remote_name)
            if not remote_url or git(workspace, "remote", "add", remote_name, remote_url) != 0:
                die(f"terminal workspace cannot bind trusted remote {remote_name}")
        verify_pr_remote_tuple(workspace, provenance, verify_pr=True, allow_merged=True)
        commit = str(provenance["head_sha"])
    else:
        remote_url = git_out(repo, "remote", "get-url", "origin")
        if not remote_url or git(workspace, "remote", "add", "origin", remote_url) != 0:
            die("terminal workspace cannot bind the legacy origin")
        commit = fetch_dispatched_commit(workspace, branch, expected_commit)

    if git(workspace, "checkout", "--detach", commit) != 0:
        die("failed to checkout terminal decision commit")
    for remote_name in git_out(workspace, "remote").splitlines():
        if remote_name and git(workspace, "remote", "remove", remote_name) != 0:
            die("failed to remove terminal workspace remotes")
    if git(workspace, "config", "core.logAllRefUpdates", "false") != 0:
        die("failed to disable terminal workspace reflogs")
    logs = workspace_path / ".git" / "logs"
    if logs.exists():
        shutil.rmtree(logs)
    fetch_head = workspace_path / ".git" / "FETCH_HEAD"
    if fetch_head.exists():
        fetch_head.unlink()
    if git_out(workspace, "rev-parse", "--verify", "HEAD^{commit}") != commit:
        die("terminal workspace does not match the decision commit")
    if git_out(workspace, "remote"):
        die("terminal workspace must not retain a Git remote")
    freeze_model_git_metadata(workspace)
    record(evidence, "terminal_workspace_ready", workspace=workspace, commit=commit)
    return workspace


def assert_model_git_state(repo: str, branch: str, expected_commit: str) -> None:
    """Fail if an untrusted model changed local HEAD or the dispatched remote ref."""
    expected = git_out(repo, "rev-parse", "--verify", f"{expected_commit}^{{commit}}")
    local_head = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
    if not expected or local_head != expected:
        die("model process changed local HEAD; trusted runner owns commits")

    remote_ref = f"refs/remotes/origin/{branch}"
    refspec = f"+refs/heads/{branch}:{remote_ref}"
    if git(repo, "fetch", "--no-tags", "origin", refspec) != 0:
        die("cannot verify the remote task ref after model execution")
    remote_head = git_out(repo, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    if remote_head != expected:
        die("model process changed the remote task ref; trusted runner owns pushes")


def assert_model_pr_git_state(repo: str, provenance: dict[str, object]) -> None:
    """Fail if a model changed local HEAD or either trusted provenance ref."""
    expected = str(provenance["head_sha"])
    local_head = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
    if local_head != expected:
        die("model process changed local HEAD; trusted runner owns commits")
    fetch_and_checkout_pr_head(repo, provenance, verify_pr=bool(provenance["pull_request"]))


def executor_commit_message(branch: str, tool: str) -> str:
    """Return a git-native Lore message for trusted executor output."""
    return (
        "Deliver the frozen TaskCard through the trusted executor\n\n"
        f"The {tool} model produced the bounded working-tree delta for {branch}. "
        "The trusted runner independently enforced the frozen postflight contract "
        "before recording and publishing this revision.\n\n"
        "Constraint: Scope and verification commands are frozen in the dispatched TaskCard\n"
        "Confidence: high\n"
        "Scope-risk: narrow\n"
        "Reversibility: clean\n"
        "Directive: Review and merge only the exact remote SHA verified by Agent Workflow\n"
        "Tested: All TaskCard postflight commands and delta gates passed in the trusted runner\n"
        "Not-tested: Independent reviewer verdict and repository CI are pending\n"
    )


# ---------------------------------------------------------------------------
# ImplementationReport gate
# ---------------------------------------------------------------------------


def check_report(report_path: str) -> None:
    """Validate the trusted ImplementationReport artifact boundary.

    Called by coder after successful model execution but before git writes,
    and by reviewer after checkout but before model execution.
    Legacy prose reports remain compatible.  When a machine envelope is
    present, it is parsed strictly before the imported-tree checkpoint.
    """
    if not report_path:
        die("--report is required; ImplementationReport must exist before commit or review")
    if not Path(report_path).is_file():
        die(f"ImplementationReport not found: {report_path}")
    try:
        content = Path(report_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        die("ImplementationReport is unreadable")
    if not content.strip() or "\x00" in content:
        die("ImplementationReport is empty or contains NUL")
    envelope = re.findall(
        r"<!--\s*awf-implementation-report\s*(?:\n\s*)?(\{.*?\})\s*-->",
        content,
        re.DOTALL,
    )
    if envelope:
        if len(envelope) != 1:
            die("ImplementationReport must contain exactly one machine envelope")
        try:
            value = json.loads(envelope[0], object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, DuplicateReviewReportKey):
            die("ImplementationReport machine envelope is malformed")
        if not isinstance(value, dict) or set(value) != {
            "summary",
            "changed_files",
            "commands",
            "tests",
            "source_revision",
        }:
            die("ImplementationReport machine envelope has missing or unknown fields")


def check_report_tracked_at_head(repo: str, relative_path: str) -> None:
    """Reject ignored or stale local reports that are absent from the dispatched commit."""
    check_repo_file_tracked_at_head(repo, relative_path, "ImplementationReport")


def check_repo_file_tracked_at_head(repo: str, relative_path: str, label: str) -> None:
    """Reject a local file unless its exact repository-relative path is tracked at HEAD."""
    tracked = git_out(repo, "ls-files", "--", relative_path).splitlines()
    if relative_path not in tracked:
        die(f"{label} is not tracked by the dispatched commit")


_REVIEW_REPORT_RE = re.compile(
    r"<!--\s*awf-review-report\s*(?:\n\s*)?(\{.*?\})(?:\s*\n\s*|\s*)-->",
    re.DOTALL,
)
_REVIEW_REPORT_FENCED_RE = re.compile(r"```json\s*\n?(.*?)\n?```", re.DOTALL)
_REVIEW_VERDICTS = {"PASS", "REQUEST_CHANGES", "BLOCKED"}
_REVIEW_REPORT_MAX_BYTES = 16 * 1024
_REVIEW_REPORT_KEYS = {"verdict", "deterministic_failures", "blocked_reason"}
_DIFF_BODY_RE = re.compile(
    r"(?m)^(?:diff --git |@@ -|--- a/|\+\+\+ b/)|```(?:diff|patch)\s*$",
    re.IGNORECASE,
)


class DuplicateReviewReportKey(ValueError):
    """Raised when JSON object pairs contain a duplicate key."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateReviewReportKey(key)
        result[key] = value
    return result


_INLINE_REVIEW_REPORT_RE = re.compile(r"<!--\s*awf-review-report\s+(\{.*?\})\s*-->", re.DOTALL)


def normalize_machine_review_envelope(workspace: str, report_path: str) -> None:
    """Normalize a syntactically valid one-line model envelope in-place."""
    source = resolve_repo_file(workspace, report_path, "ReviewReport")
    try:
        markdown = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    matches = list(_INLINE_REVIEW_REPORT_RE.finditer(markdown))
    if len(matches) != 1:
        return
    match = matches[0]
    if "\n" in markdown[match.start() : match.end()].split("{", 1)[0]:
        return
    try:
        machine = json.loads(match.group(1), object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, DuplicateReviewReportKey):
        return
    if not isinstance(machine, dict):
        return
    canonical = (
        "<!-- awf-review-report\n"
        + json.dumps(machine, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n-->"
    )
    updated = markdown[: match.start()] + canonical + markdown[match.end() :]
    if updated != markdown:
        source.write_text(updated, encoding="utf-8", newline="\n")


def resolve_review_report_path(repo: str, report_path: str, implementation_report: str) -> Path:
    """Resolve one explicit repo-relative ReviewReport path without traversal."""
    if not report_path:
        die("--review-report is required")
    if "\\" in report_path or report_path.startswith("/") or ":" in report_path:
        die("ReviewReport path must be repository-relative and use forward slashes")
    if ".." in report_path.split("/"):
        die("ReviewReport path must not contain parent traversal")

    repo_root = Path(repo).resolve()
    resolved = (repo_root / report_path).resolve()
    if resolved == repo_root or repo_root not in resolved.parents:
        die("ReviewReport path escapes the repository")

    implementation_path = Path(implementation_report)
    if not implementation_path.is_absolute():
        implementation_path = repo_root / implementation_path
    if resolved == implementation_path.resolve():
        die("ReviewReport path must be distinct from ImplementationReport path")
    return resolved


def resolve_repo_file(repo: str, relative_path: str, label: str) -> Path:
    """Resolve one required repository-relative file path without traversal."""
    if not relative_path:
        die(f"--{label.lower().replace(' ', '-')} is required")
    if "\\" in relative_path or relative_path.startswith("/") or ":" in relative_path:
        die(f"{label} path must be repository-relative and use forward slashes")
    if ".." in relative_path.split("/"):
        die(f"{label} path must not contain parent traversal")
    repo_root = Path(repo).resolve()
    resolved = (repo_root / relative_path).resolve()
    if resolved == repo_root or repo_root not in resolved.parents:
        die(f"{label} path escapes the repository")
    return resolved


def _validate_deterministic_failure(item: object, index: int) -> dict[str, object]:
    if not isinstance(item, dict):
        die(f"deterministic_failures[{index}] must be an object")
    expected = {"evidence", "required_correction"}
    if set(item) != expected:
        die(f"deterministic_failures[{index}] has invalid fields")
    correction = item["required_correction"]
    evidence = item["evidence"]
    if not isinstance(correction, str) or not correction.strip():
        die(f"deterministic_failures[{index}] requires a correction")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("kind"), str):
        die(f"deterministic_failures[{index}] requires structured evidence")

    kind = evidence["kind"]
    if kind == "criterion":
        expected_evidence = {"kind", "criterion"}
        valid = isinstance(evidence.get("criterion"), str) and bool(evidence["criterion"].strip())
    elif kind == "command":
        expected_evidence = {"kind", "command", "result"}
        valid = all(
            isinstance(evidence.get(key), str) and bool(evidence[key].strip())
            for key in ("command", "result")
        )
    elif kind == "file_line":
        expected_evidence = {"kind", "file", "line"}
        file_name = evidence.get("file")
        line = evidence.get("line")
        valid = (
            isinstance(file_name, str)
            and bool(file_name.strip())
            and not file_name.startswith("/")
            and "\\" not in file_name
            and ".." not in file_name.split("/")
            and isinstance(line, int)
            and not isinstance(line, bool)
            and line > 0
        )
    else:
        die(f"deterministic_failures[{index}] has unknown evidence kind")
    if set(evidence) != expected_evidence or not valid:
        die(f"deterministic_failures[{index}] lacks precise evidence")
    return {"evidence": dict(evidence), "required_correction": correction.strip()}


def parse_review_report(report_path: Path) -> dict[str, object]:
    """Validate and normalize a bounded ReviewReport for downstream payloads."""
    try:
        markdown = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        die(f"ReviewReport is missing or unreadable: {report_path}")
    if not markdown.strip():
        die("ReviewReport is empty")
    if _DIFF_BODY_RE.search(markdown):
        die("ReviewReport must not contain full diff or patch bodies")
    secret_label = _scan_text(markdown)
    if secret_label:
        die(f"ReviewReport contains prohibited {secret_label} material")

    blocks = _REVIEW_REPORT_RE.findall(markdown)
    if len(blocks) == 1:
        machine_source = blocks[0]
    elif len(blocks) == 0:
        # Older reviewer prompts described the machine object but omitted the
        # HTML wrapper required by this parser. Accept exactly one fenced
        # wrapper so completed model output can recover without a second call.
        fenced = _REVIEW_REPORT_FENCED_RE.findall(markdown)
        if len(fenced) != 1:
            die("ReviewReport must contain exactly one awf-review-report object")
        try:
            wrapped = json.loads(fenced[0], object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, DuplicateReviewReportKey):
            die("ReviewReport machine object is malformed or contains duplicate fields")
        if not isinstance(wrapped, dict) or set(wrapped) != {"awf-review-report"}:
            die("ReviewReport machine object has missing or unknown fields")
        machine = wrapped["awf-review-report"]
        if not isinstance(machine, dict):
            die("ReviewReport machine object is malformed")
        data = machine
        if set(data) != _REVIEW_REPORT_KEYS:
            die("ReviewReport machine object has missing or unknown fields")
        return _normalize_review_report(data, markdown)
    else:
        die("ReviewReport must contain exactly one awf-review-report object")
    try:
        data = json.loads(machine_source, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, DuplicateReviewReportKey):
        die("ReviewReport machine object is malformed or contains duplicate fields")
    if not isinstance(data, dict) or set(data) != _REVIEW_REPORT_KEYS:
        die("ReviewReport machine object has missing or unknown fields")

    return _normalize_review_report(data, markdown)


def _normalize_review_report(data: dict[str, object], markdown: str) -> dict[str, object]:
    verdict = data["verdict"]
    if not isinstance(verdict, str) or verdict not in _REVIEW_VERDICTS:
        die("ReviewReport verdict must be exactly PASS, REQUEST_CHANGES, or BLOCKED")
    failures = data["deterministic_failures"]
    if not isinstance(failures, list):
        die("ReviewReport deterministic_failures must be an array")
    normalized_failures = [
        _validate_deterministic_failure(item, index) for index, item in enumerate(failures)
    ]
    blocked_reason = data["blocked_reason"]
    # PASS has no blocking condition, so a model may express that absence as
    # JSON null. Normalize it before the verdict-specific invariants below;
    # BLOCKED and REQUEST_CHANGES retain strict string typing.
    if verdict == "PASS" and blocked_reason is None:
        blocked_reason = ""
    elif not isinstance(blocked_reason, str):
        die("ReviewReport blocked_reason must be a string")
    blocked_reason = blocked_reason.strip()

    if verdict == "PASS" and normalized_failures:
        die("PASS ReviewReport cannot contain deterministic failures")
    if verdict == "REQUEST_CHANGES" and not normalized_failures:
        die("REQUEST_CHANGES requires deterministic failure evidence")
    if verdict == "BLOCKED" and not blocked_reason:
        die("BLOCKED requires an escalation reason")
    if verdict != "BLOCKED" and blocked_reason:
        die("blocked_reason is only valid for BLOCKED")

    normalized: dict[str, object] = {
        "format": "awf.review-report.v1",
        "verdict": verdict,
        "deterministic_failures": normalized_failures,
        "blocked_reason": blocked_reason,
        "markdown": markdown,
    }
    # Match send_event()'s JSON representation so the bound applies to the bytes that
    # are actually embedded in the downstream payload, including escaped Unicode.
    encoded = json.dumps(normalized).encode("utf-8")
    if len(encoded) > _REVIEW_REPORT_MAX_BYTES:
        die("normalized ReviewReport exceeds 16 KiB")
    return normalized


def validate_embedded_review_report(data: object) -> dict[str, object]:
    """Revalidate the exact normalized ReviewReport carried by a decision event."""
    expected_keys = {
        "format",
        "verdict",
        "deterministic_failures",
        "blocked_reason",
        "markdown",
    }
    if not isinstance(data, dict) or set(data) != expected_keys:
        die("embedded ReviewReport has missing or unknown fields")
    if data.get("format") != "awf.review-report.v1":
        die("embedded ReviewReport format is unsupported")
    markdown = data.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        die("embedded ReviewReport markdown is missing")
    if _DIFF_BODY_RE.search(markdown):
        die("embedded ReviewReport must not contain full diff or patch bodies")
    secret_label = _scan_text(markdown)
    if secret_label:
        die(f"embedded ReviewReport contains prohibited {secret_label} material")
    blocks = _REVIEW_REPORT_RE.findall(markdown)
    if len(blocks) == 1:
        machine_source = blocks[0]
    elif len(blocks) == 0:
        fenced = _REVIEW_REPORT_FENCED_RE.findall(markdown)
        if len(fenced) != 1:
            die("embedded ReviewReport must contain exactly one awf-review-report object")
        try:
            wrapped = json.loads(fenced[0], object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, DuplicateReviewReportKey):
            die("embedded ReviewReport machine object is malformed or contains duplicate fields")
        if not isinstance(wrapped, dict) or set(wrapped) != {"awf-review-report"}:
            die("embedded ReviewReport machine object has missing or unknown fields")
        machine = wrapped["awf-review-report"]
        if not isinstance(machine, dict) or set(machine) != _REVIEW_REPORT_KEYS:
            die("embedded ReviewReport machine object has missing or unknown fields")
        normalized = _normalize_review_report(machine, markdown)
        if normalized != data:
            die("embedded ReviewReport does not match its normalized machine object")
        return normalized
    else:
        die("embedded ReviewReport must contain exactly one awf-review-report object")
    try:
        machine = json.loads(machine_source, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, DuplicateReviewReportKey):
        die("embedded ReviewReport machine object is malformed or contains duplicate fields")
    if not isinstance(machine, dict) or set(machine) != _REVIEW_REPORT_KEYS:
        die("embedded ReviewReport machine object has missing or unknown fields")
    normalized = _normalize_review_report(machine, markdown)
    if normalized != data:
        die("embedded ReviewReport does not match its normalized machine object")
    return normalized


# ---------------------------------------------------------------------------
# Postflight contract
# ---------------------------------------------------------------------------


class PostflightContract:
    """Frozen postflight contract parsed from a TaskCard awf-postflight block."""

    def __init__(
        self,
        allowed_paths: list[str],
        verification_commands: list[list[str]],
    ) -> None:
        self.allowed_paths = list(allowed_paths)
        self.verification_commands = [list(cmd) for cmd in verification_commands]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PostflightContract):
            return NotImplemented
        return (
            self.allowed_paths == other.allowed_paths
            and self.verification_commands == other.verification_commands
        )

    def __repr__(self) -> str:
        return (
            f"PostflightContract(allowed_paths={self.allowed_paths!r}, "
            f"verification_commands={self.verification_commands!r})"
        )


_POSTFLIGHT_RE = re.compile(r"<!--\s*awf-postflight\s*\n(.*?)\n\s*-->", re.DOTALL)

# Artifact denylist — paths that always fail even if in allowed_paths.
_DENY_PREFIXES: tuple[str, ...] = (
    ".venv/",
    "venv/",
    "env/",
    "__pycache__/",
    "node_modules/",
    "dist/",
    "build/",
    "coverage/",
    "htmlcov/",
)
_DENY_EXACT: tuple[str, ...] = (
    "Thumbs.db",
    ".DS_Store",
    ".coverage",
    "coverage.xml",
)
_DENY_SUFFIXES: tuple[str, ...] = (
    ".swp",
    ".swo",
    ".swn",
    ".bak",
    ".orig",
    ".pyc",
    ".pyo",
    ".log",
    ".pid",
    ".egg-info",
)


def _is_env_denied(path: str) -> bool:
    """True for .env variants that carry secrets, excluding example templates.

    Matches by basename so .env variants at any path depth are detected.
    """
    basename = os.path.basename(path)
    if basename == ".env":
        return True
    if basename.startswith(".env."):
        # Allow documented examples
        return basename not in (".env.example", ".env.template", ".env.sample")
    return False


def _path_is_denied(path: str) -> bool:
    """Check a single repository-relative path against the artifact denylist.

    Directory patterns (e.g. ``node_modules/``, ``.venv/``) are matched at any
    depth by path component, not only at root.  ``.env`` variants are matched by
    basename.  Suffix-based patterns match at any depth.
    """
    if _is_env_denied(path):
        return True

    # Match directory prefixes at any depth via path component
    path_components = path.split("/")
    for prefix in _DENY_PREFIXES:
        stripped = prefix.rstrip("/")
        if stripped in path_components:
            return True

    if os.path.basename(path) in _DENY_EXACT:
        return True
    if path.endswith(_DENY_SUFFIXES):
        return True
    # Also deny files inside .egg-info directories
    if ".egg-info/" in path:
        return True
    return False


def parse_postflight_contract(card_path: str) -> PostflightContract:
    """Parse, validate, and freeze the awf-postflight contract from a TaskCard.

    Must be called before the model runs so that model edits to the card file
    (which is deliberately absent from ``allowed_paths``) cannot change the
    contract.
    """
    text = Path(card_path).read_text(encoding="utf-8")
    m = _POSTFLIGHT_RE.search(text)
    if not m:
        die("task card has no awf-postflight contract block")

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        die(f"malformed awf-postflight contract: {e}")

    if not isinstance(data, dict):
        die("awf-postflight contract must be a JSON object")

    # Reject extra keys
    allowed_keys = {"allowed_paths", "verification_commands"}
    extra = set(data) - allowed_keys
    if extra:
        die(f"unexpected awf-postflight keys: {', '.join(sorted(extra))}")

    # --- allowed_paths ---
    raw_paths = data.get("allowed_paths", [])
    if not isinstance(raw_paths, list) or not raw_paths:
        die("awf-postflight allowed_paths must be a non-empty array")

    normalized: list[str] = []
    seen: set[str] = set()
    for p in raw_paths:
        if not isinstance(p, str) or not p.strip():
            die(f"invalid allowed_path entry: {p!r}")
        if "\\" in p:
            die(f"allowed path must use forward slashes: {p!r}")
        if p.startswith("/"):
            die(f"allowed path must be repo-relative (no leading slash): {p!r}")
        if ":" in p:
            die(f"allowed path must not be drive-qualified: {p!r}")
        if ".." in p.split("/"):
            die(f"allowed path must not contain parent traversal: {p!r}")
        if p in seen:
            die(f"duplicate allowed path: {p!r}")
        seen.add(p)
        normalized.append(p)

    # --- verification_commands ---
    raw_cmds = data.get("verification_commands", [])
    if not isinstance(raw_cmds, list) or not raw_cmds:
        die("awf-postflight verification_commands must be a non-empty array")

    commands: list[list[str]] = []
    for i, cmd in enumerate(raw_cmds):
        if not isinstance(cmd, list) or len(cmd) == 0:
            die(f"verification_commands[{i}] must be a non-empty array of strings")
        if not all(isinstance(s, str) for s in cmd):
            die(f"verification_commands[{i}] must contain only strings")
        if cmd[0] == "":
            die(f"verification_commands[{i}] has an empty executable")
        argv = list(cmd)
        if argv[0] == "{python}":
            argv[0] = sys.executable
        commands.append(argv)

    return PostflightContract(allowed_paths=normalized, verification_commands=commands)


def validate_implementation_report_contract(
    card_path: str,
    a: argparse.Namespace,
    evidence: RunEvidence | None,
) -> None:
    """Fail a production delivery before model invocation when artifact identity drifts."""
    if not _is_v3(a):
        return
    try:
        validate_stage_artifact_contract(
            card_path=Path(card_path),
            task_id=a.branch.rsplit("/", 1)[-1],
            required_report_path=a.report,
        )
    except ArtifactContractError as exc:
        record(evidence, "contract_preflight_failed", reason=str(exc))
        die(f"implementation artifact contract rejected before model invocation: {exc}")


def load_reviewer_selection_contract(
    card_path: str,
    *,
    fallback_tool: str,
    fallback_model: str,
) -> ReviewerSelectionContract:
    """Load stage selections from the exact frozen TaskCard before a model starts."""
    try:
        return reviewer_selection_contract(
            Path(card_path).read_text(encoding="utf-8"),
            fallback_tool=fallback_tool,
            fallback_model=fallback_model,
        )
    except (OSError, UnicodeError, TaskCardContractError) as exc:
        die(f"TaskCard reviewer selection rejected before model invocation: {exc}")


def validate_frozen_role_selection(
    selection: object,
    *,
    role: str,
    tool: str,
    model: str,
) -> None:
    if (getattr(selection, "tool", None), getattr(selection, "model", None)) != (tool, model):
        die(f"TaskCard {role} selection mismatch")


# ---------------------------------------------------------------------------
# Postflight gates (run after model succeeds, before git write / send_event)
# ---------------------------------------------------------------------------


def run_verifications(repo: str, contract: PostflightContract) -> None:
    """Run every verification command in order. Stop at the first failure.

    Verification runs before the final Git delta collection so that files
    created by verification are subject to path/artifact checks.
    """
    for i, argv in enumerate(contract.verification_commands):
        log(f"postflight verification [{i + 1}/{len(contract.verification_commands)}]")
        rc = spawn(argv, cwd=repo, env=verification_env())
        if rc != 0:
            die(f"postflight verification [{i + 1}] failed (rc={rc})")


def _collect_delta_paths(repo: str) -> list[str]:
    """Return all repository-relative paths that differ from HEAD.

    Uses NUL-delimited git output for safe handling of all path names
    (spaces, Unicode, quotes).  Covers tracked changes (staged + unstaged
    vs HEAD) and untracked non-ignored files.  With ``--no-renames`` a
    renamed file appears as a delete of the old name and an add of the new
    name, so both sides are captured.
    """
    paths: list[str] = []

    # Tracked changes: staged + unstaged from HEAD
    tracked = postflight_git_out(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        "HEAD",
        "--no-renames",
        "-z",
    )
    if tracked:
        paths.extend(p for p in tracked.split("\0") if p)

    # Untracked non-ignored files
    untracked = postflight_git_out(repo, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked:
        paths.extend(p for p in untracked.split("\0") if p)

    return paths


def run_postflight_delta_gates(repo: str, contract: PostflightContract) -> None:
    """Enforce allowed paths, artifact denylist, narrow secret scan, and diff check.

    Must be called after ``run_verifications`` and before ``git add``.
    """
    delta_paths = _collect_delta_paths(repo)

    # 1. Empty set check
    if not delta_paths:
        die("postflight: no changes detected after model execution")

    # 2. Allowed-path gate
    allowed_set = set(contract.allowed_paths)
    offending: list[str] = []
    for p in delta_paths:
        if p not in allowed_set:
            offending.append(p)
    if offending:
        die(
            "postflight: changed path(s) not in allowed_paths:\n  " + "\n  ".join(sorted(offending))
        )

    # 3. Artifact denylist gate (checked even if path is allowed)
    denied: list[str] = []
    for p in delta_paths:
        if _path_is_denied(p):
            denied.append(p)
    if denied:
        die("postflight: artifact denylist violation:\n  " + "\n  ".join(sorted(denied)))

    # 4. Narrow secret scan — added lines in tracked diffs + untracked file content
    _narrow_secret_scan(repo, delta_paths)

    # 5. git diff --check on full HEAD delta (staged + unstaged)
    checked = postflight_git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "HEAD",
        "--check",
    )
    if checked.returncode != 0:
        die("postflight: git diff HEAD --check found whitespace errors")


# ---------------------------------------------------------------------------
# Narrow secret scan
# ---------------------------------------------------------------------------


# High-confidence credential detectors: (label, regex)
_SECRET_DETECTORS: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN\s+(?:\S+\s+)?PRIVATE\s+KEY-----")),
    ("credential-url", re.compile(r"https?://[^/:@\s]+:[^/@\s]+@")),
    ("github-token", re.compile(r"gh[puosr]_[A-Za-z0-9_]{36,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
]


def _scan_text(text: str) -> str | None:
    """Return the first matching detector label, or None."""
    for label, pat in _SECRET_DETECTORS:
        if pat.search(text):
            return label
    return None


def _narrow_secret_scan(repo: str, delta_paths: list[str] | None = None) -> None:
    """Scan added content from tracked diffs and untracked files for secrets.

    Uses the full HEAD→working-tree diff (staged + unstaged) for tracked
    changes and NUL-delimited git output for untracked file discovery.
    Reports the first hit per-path with detector label only — never the value.
    Fails closed on unreadable untracked files.
    """
    if delta_paths is None:
        delta_paths = _collect_delta_paths(repo)

    # Identify untracked paths with NUL-delimited output, then scan each tracked
    # path independently.  This avoids parsing quoted, human-readable patch
    # headers and prevents configured diff helpers from transforming content or
    # executing in the credential-bearing runner environment.
    untracked_out = postflight_git_out(repo, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = {path for path in untracked_out.split("\0") if path}

    for path in delta_paths:
        if path in untracked:
            continue
        diff_out = postflight_git_out(
            repo,
            "diff",
            "HEAD",
            "--no-color",
            "--no-renames",
            "--no-textconv",
            "--no-ext-diff",
            "--unified=0",
            "--",
            path,
        )
        in_hunk = False
        for line in diff_out.splitlines():
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk and line.startswith("+"):
                label = _scan_text(line[1:])
                if label:
                    die(f"postflight secret scan: {label} in {path}")

    # Untracked regular files.
    if untracked_out:
        for path in untracked_out.split("\0"):
            if not path:
                continue
            full = os.path.join(repo, path)
            if os.path.isfile(full):
                try:
                    content = Path(full).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    die(f"postflight secret scan: unreadable-file in untracked file {path}")
                label = _scan_text(content)
                if label:
                    die(f"postflight secret scan: {label} in untracked file {path}")


# ---------------------------------------------------------------------------
# git helpers shared by all roles
# ---------------------------------------------------------------------------


_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def fetch_and_checkout(repo: str, branch: str, expected_commit: str) -> None:
    """Synchronize a clean checkout to the exact remote task branch."""
    log(f"preflight + fetch + checkout {branch} in {repo}")
    if git(repo, "check-ref-format", "--branch", branch) != 0:
        die(f"invalid task branch {branch!r}")
    if not _COMMIT_RE.fullmatch(expected_commit):
        die("event commit must be a 7-64 character hexadecimal Git object ID")

    dirty = git_out(repo, "status", "--porcelain")
    if dirty:
        die("working tree is dirty; commit, stash, or clean it before retrying")

    all_heads = "+refs/heads/*:refs/remotes/origin/*"
    if git(repo, "fetch", "--quiet", "--prune", "origin", all_heads) != 0:
        die("cannot fetch latest refs from origin")

    remote_ref = f"refs/remotes/origin/{branch}"
    if git(repo, "show-ref", "--verify", "--quiet", remote_ref) != 0:
        die(f"remote branch origin/{branch} does not exist")

    resolved_expected = git_out(repo, "rev-parse", "--verify", f"{expected_commit}^{{commit}}")
    remote_head = git_out(repo, "rev-parse", f"origin/{branch}")
    if not resolved_expected:
        die(f"event commit {expected_commit} is not available after fetch")
    if remote_head != resolved_expected:
        die(
            f"origin/{branch} changed after dispatch; expected {resolved_expected}, "
            f"found {remote_head}"
        )

    local_ref = f"refs/heads/{branch}"
    if git(repo, "show-ref", "--verify", "--quiet", local_ref) == 0:
        ahead = git_out(repo, "rev-list", "--count", f"origin/{branch}..{branch}")
        if not ahead.isdigit():
            die(f"cannot compare local branch {branch} with origin/{branch}")
        if int(ahead) > 0:
            die(f"local branch {branch} has unpushed commits; refusing to overwrite it")

    if git(repo, "checkout", "-q", "-B", branch, f"origin/{branch}") != 0:
        die(f"cannot checkout branch {branch} from origin/{branch}")

    head = git_out(repo, "rev-parse", "HEAD")
    if not head or head != remote_head:
        die(f"checkout {branch} is not synchronized with origin/{branch}")


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# provider adapter compatibility wrappers
# ---------------------------------------------------------------------------


def tool_opencode_exec(
    repo: str,
    card_file: str,
    prompt_file: str,
    model: str,
    implementation_report_path: str,
    review_feedback: str = "",
    evidence: RunEvidence | None = None,
) -> int:
    """Run OpenCode as an executor: edit code in `repo` per the card + prompt."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    prompt = read_text(prompt_file)
    normalized_feedback = normalize_rework_feedback(review_feedback) if review_feedback else ""
    invocation_argv = render_opencode_executor_argv(
        binary=binp,
        workspace=repo,
        card_file=card_file,
        model=model,
        prompt=prompt,
        implementation_report_path=implementation_report_path,
        normalized_review_feedback=normalized_feedback,
    )
    if evidence is not None:
        return spawn(
            invocation_argv,
            cwd=repo,
            env=model_env(repo),
            evidence=evidence,
            tracked_phase="opencode",
        )
    return spawn(invocation_argv, cwd=repo, env=model_env(repo))


def normalize_rework_feedback(raw: str) -> str:
    """Return bounded reviewer feedback without forwarding report prose or patches."""
    if len(raw.encode("utf-8")) > _REVIEW_REPORT_MAX_BYTES:
        die("review feedback exceeds 16 KiB")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, DuplicateReviewReportKey):
        die("review feedback is malformed or contains duplicate fields")
    if not isinstance(data, dict) or data.get("format") != "awf.review-report.v1":
        die("review feedback has an invalid format")
    verdict = data.get("verdict")
    failures = data.get("deterministic_failures")
    blocked_reason = data.get("blocked_reason")
    if verdict != "REQUEST_CHANGES" or not isinstance(failures, list) or not failures:
        die("rework requires REQUEST_CHANGES with deterministic failures")
    if not isinstance(blocked_reason, str) or blocked_reason:
        die("REQUEST_CHANGES feedback cannot contain a blocked reason")
    normalized_failures = [
        _validate_deterministic_failure(item, index) for index, item in enumerate(failures)
    ]
    bounded = {
        "verdict": verdict,
        "deterministic_failures": normalized_failures,
        "blocked_reason": "",
    }
    text = json.dumps(bounded, indent=2, sort_keys=True)
    secret_label = _scan_text(text)
    if secret_label:
        die(f"review feedback contains prohibited {secret_label} material")
    return text


def tool_codex_review(
    repo: str,
    base: str,
    prompt_file: str,
    card_file: str,
    model: str,
    review_report_path: str,
    evidence: RunEvidence | None = None,
) -> int:
    """Run Codex review and persist its final response at the exact report path."""
    binp = env("AWF_CODEX_BIN", "codex")
    prompt = read_text(prompt_file)
    template_path = Path(__file__).resolve().parent.parent / "templates/artifacts/review-report.md"
    review_report_template = read_text(str(template_path))
    card_text = read_text(card_file) if card_file and Path(card_file).is_file() else ""
    invocation_argv, invocation_stdin = render_codex_reviewer_invocation(
        binary=binp,
        workspace=repo,
        base=base,
        model=model,
        review_report_path=review_report_path,
        prompt=prompt,
        review_report_template=review_report_template,
        card_text=card_text,
    )
    return spawn(
        invocation_argv,
        cwd=repo,
        stdin=invocation_stdin,
        env=model_env(repo),
        evidence=evidence,
        tracked_phase="codex" if evidence is not None else None,
    )


def tool_opencode_review(
    repo: str,
    base: str,
    prompt_file: str,
    card_file: str,
    model: str,
    review_report_path: str,
    evidence: RunEvidence | None = None,
) -> int:
    """Fallback reviewer using OpenCode (when Codex is unavailable)."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    attached_card = card_file if card_file and Path(card_file).is_file() else ""
    invocation_argv = render_opencode_reviewer_argv(
        binary=binp,
        workspace=repo,
        card_file=attached_card,
        model=model,
        prompt=read_text(prompt_file),
        review_report_path=review_report_path,
    )
    if evidence is not None:
        return spawn(
            invocation_argv,
            cwd=repo,
            env=model_env(repo),
            evidence=evidence,
            tracked_phase="opencode",
        )
    return spawn(invocation_argv, cwd=repo, env=model_env(repo))


def tool_pi_review(
    repo: str,
    base: str,
    prompt_file: str,
    card_file: str,
    model: str,
    review_report_path: str,
    evidence: RunEvidence | None = None,
) -> int:
    """Run Pi as a read-only reviewer and persist stdout as the ReviewReport."""
    binp = env("AWF_PI_BIN", "pi")
    template_path = Path(__file__).resolve().parent.parent / "templates/artifacts/review-report.md"
    card_text = read_text(card_file) if card_file and Path(card_file).is_file() else ""
    trusted_diff = bounded_postflight_git_out(
        repo,
        64 * 1024,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        f"{base}...HEAD",
        "--",
    )
    if not trusted_diff:
        trusted_diff = "(empty diff)"
    context = read_text(prompt_file)
    context += (
        "\n\n--- Pi read-only reviewer boundary ---\n\n"
        "The trusted runner supplied the exact base-to-HEAD diff because this Pi adapter has "
        "no command tool. Inspect repository files with the read-only tools as needed. Treat "
        "verification results in the ImplementationReport as evidence; if the diff or report "
        "is insufficient for a deterministic verdict, return BLOCKED rather than claiming PASS."
        f"\n\n--- Trusted committed diff ---\n\n{trusted_diff}"
        f"\n\n--- Required ReviewReport template ---\n\n{read_text(str(template_path))}"
    )
    if card_text:
        context += "\n\n--- TaskCard (acceptance criteria to verify) ---\n\n" + card_text

    def invoke(context_path: Path) -> int:
        atomic_write_text(context_path, context)
        invocation_argv = render_pi_reviewer_argv(
            binary=binp,
            base=base,
            model=model,
            review_report_path=review_report_path,
            context_file=str(context_path),
        )
        return spawn(
            invocation_argv,
            cwd=repo,
            env=model_env(repo),
            evidence=evidence,
            tracked_phase="pi" if evidence is not None else None,
            stdout_path=review_report_path,
        )

    if evidence is not None:
        return invoke(evidence.run_dir / "pi-review-context.md")
    with tempfile.TemporaryDirectory(prefix="awf-pi-review-") as context_dir:
        return invoke(Path(context_dir) / "review-context.md")


# ---------------------------------------------------------------------------
# Agent Bus event emission (reuse the agent-bus CLI for auth consistency)
# ---------------------------------------------------------------------------


def send_event(from_role: str, to_role: str, etype: str, payload: dict) -> bool:
    url = env("AGENT_BUS_URL")
    bus = env("AWF_BUS_BIN", "agent-bus")
    token = env(f"AWF_{from_role.upper()}_TOKEN")
    if not (url and token):
        log(f"no AGENT_BUS_URL/AWF_{from_role.upper()}_TOKEN; skipping {etype} announcement")
        return False
    cenv = child_env()
    cenv["AGENT_BUS_URL"] = url
    cenv["AGENT_BUS_TOKEN"] = token
    cenv["AGENT_BUS_AGENT"] = from_role
    argv = [
        bus,
        "send",
        "--from",
        from_role,
        "--to",
        to_role,
        "--type",
        etype,
        "--payload",
        json.dumps(payload),
    ]
    log(f"send {etype}: {from_role} -> {to_role}")
    try:
        rc = run_command(
            argv,
            env=cenv,
            stdin=DEVNULL,
            allow_shell_wrapper=True,
            secrets=(token,),
        ).returncode
    except ExecutionFailure as exc:
        log(f"WARN: failed to send {etype}: {exc}")
        return False
    if rc != 0:
        log(f"WARN: failed to send {etype} (rc={rc})")
    return rc == 0


def build_delivery_payload(
    source_role: str,
    event_type: str,
    payload: dict[str, object],
    evidence: RunEvidence | None,
) -> dict[str, object]:
    payload_sha256 = canonical_payload_sha256(payload)
    source_event_id = evidence.event_id if evidence is not None else 0
    delivery_id = make_delivery_id(
        source_role,
        event_type,
        payload_sha256,
        source_event_id,
    )
    return {
        **payload,
        "awf_delivery_id": delivery_id,
        "awf_payload_sha256": payload_sha256,
        "awf_source_event_id": source_event_id,
    }


def _outbox_immutable(record_value: dict[str, object]) -> dict[str, object]:
    return {
        key: value for key, value in record_value.items() if key not in {"status", "updated_at"}
    }


_OUTBOX_ROUTES = {
    "coder.review_handoff": (
        "coder",
        "reviewer",
        {"task:awf-review", "task:awf-review-v2", "task:awf-review-v3"},
    ),
    "reviewer.pass": (
        "reviewer",
        "architect",
        {"decision:awf-ready", "decision:awf-ready-v2", "decision:awf-ready-v3"},
    ),
    "reviewer.request_changes": (
        "reviewer",
        "coder",
        {"task:awf-rework", "task:awf-rework-v2", "task:awf-rework-v3"},
    ),
    "reviewer.blocked": (
        "reviewer",
        "architect",
        {"decision:awf-blocked", "decision:awf-blocked-v2", "decision:awf-blocked-v3"},
    ),
}


def validate_outbox_record(record_value: dict[str, object]) -> None:
    outbox_format = record_value.get("format")
    if outbox_format not in {"awf.outbox.v1", "awf.outbox.v2"}:
        die("outbox format is invalid")
    action = record_value.get("action")
    route = _OUTBOX_ROUTES.get(action)
    if route is None:
        die("outbox action is invalid")
    source_role, to_role, event_types = route
    event_type = record_value.get("event_type")
    if (
        record_value.get("source_role") != source_role
        or record_value.get("to_role") != to_role
        or event_type not in event_types
    ):
        die("outbox route does not match its Workflow action")
    payload = record_value.get("payload")
    if not isinstance(payload, dict):
        die("outbox payload is invalid")
    if record_value.get("envelope_sha256") != canonical_payload_sha256(payload):
        die("outbox payload integrity check failed")
    payload_base = {key: value for key, value in payload.items() if not key.startswith("awf_")}
    payload_sha256 = canonical_payload_sha256(payload_base)
    if (
        payload.get("awf_payload_sha256") != payload_sha256
        or record_value.get("payload_sha256") != payload_sha256
    ):
        die("outbox canonical payload hash is inconsistent")
    delivery_id = payload.get("awf_delivery_id")
    source_event_id = payload.get("awf_source_event_id")
    if not isinstance(delivery_id, str) or not isinstance(source_event_id, int):
        die("outbox delivery metadata is invalid")
    if source_event_id < 1:
        die("outbox source event ID must be positive")
    expected_delivery = make_delivery_id(
        source_role,
        str(event_type),
        payload_sha256,
        source_event_id,
    )
    if delivery_id != expected_delivery or record_value.get("delivery_id") != expected_delivery:
        die("outbox delivery ID is inconsistent")
    provenance = record_value.get("provenance")
    if outbox_format == "awf.outbox.v2":
        if not isinstance(provenance, dict):
            die("v2 outbox is missing PR provenance")
        if provenance.get("provenance_version") != "awf.pr-provenance.v1":
            die("v2 outbox PR provenance version is invalid")
        if payload.get("provenance_version") != provenance.get("provenance_version"):
            die("outbox payload PR provenance is inconsistent")
        for field in _PROVENANCE_FIELDS:
            if payload.get(field) != provenance.get(field):
                die(f"outbox payload {field} is inconsistent")
    elif provenance is not None:
        die("legacy outbox must not contain PR provenance")


def prepare_outbox(
    evidence: RunEvidence | None,
    input_context: dict[str, object],
    *,
    action: str,
    branch: str,
    source_commit: str,
    evidence_commit: str,
    to_role: str,
    event_type: str,
    payload: dict[str, object],
    provenance: dict[str, object] | None = None,
) -> tuple[Path, dict[str, object]] | None:
    if evidence is None:
        return None
    delivery_id = payload.get("awf_delivery_id")
    payload_sha256 = payload.get("awf_payload_sha256")
    source_event_id = payload.get("awf_source_event_id")
    if not isinstance(delivery_id, str) or not isinstance(payload_sha256, str):
        die("outbox payload is missing Workflow delivery metadata")
    expected_delivery = make_delivery_id(
        evidence.role,
        event_type,
        payload_sha256,
        int(source_event_id),
    )
    if delivery_id != expected_delivery:
        die("outbox payload delivery ID is invalid")
    record_value: dict[str, object] = {
        "format": "awf.outbox.v2" if provenance is not None else "awf.outbox.v1",
        "source_role": evidence.role,
        "input_key": input_context["key"],
        "input_delivery_id": input_context["delivery_id"],
        "input_payload_sha256": input_context["payload_sha256"],
        "input_source_event_id": input_context["source_event_id"],
        "action": action,
        "branch": branch,
        "source_commit": source_commit,
        "evidence_commit": evidence_commit,
        "to_role": to_role,
        "event_type": event_type,
        "delivery_id": delivery_id,
        "payload_sha256": payload_sha256,
        "envelope_sha256": canonical_payload_sha256(payload),
        "payload": payload,
        "status": "prepared",
        "updated_at": _utc_now(),
    }
    if provenance is not None:
        record_value["provenance"] = provenance_payload(provenance)
    validate_outbox_record(record_value)
    path = delivery_state_path(evidence, "outbox", str(input_context["key"]))
    existing = _load_delivery_record(path, "outbox")
    if existing is not None:
        if _outbox_immutable(existing) != _outbox_immutable(record_value):
            die("existing outbox does not match the current Workflow input")
        return path, existing
    _atomic_write_json(path, record_value)
    record(evidence, "outbox_prepared", delivery_id=delivery_id, event_type=event_type)
    return path, record_value


def _set_outbox_status(
    path: Path,
    record_value: dict[str, object],
    status: str,
) -> dict[str, object]:
    updated = {**record_value, "status": status, "updated_at": _utc_now()}
    _atomic_write_json(path, updated)
    return updated


def deliver_outbox(
    evidence: RunEvidence,
    path: Path,
    record_value: dict[str, object],
) -> bool:
    validate_outbox_record(record_value)
    attempting = _set_outbox_status(path, record_value, "attempting")
    try:
        sent = send_event(
            str(attempting["source_role"]),
            str(attempting["to_role"]),
            str(attempting["event_type"]),
            dict(attempting["payload"]),
        )
    except BaseException:
        _set_outbox_status(path, attempting, "ambiguous")
        record(evidence, "outbox_ambiguous", delivery_id=attempting["delivery_id"])
        raise
    if not sent:
        _set_outbox_status(path, attempting, "ambiguous")
        record(evidence, "outbox_ambiguous", delivery_id=attempting["delivery_id"])
        return False
    sent_record = _set_outbox_status(path, attempting, "sent")
    record(evidence, "outbox_sent", delivery_id=sent_record["delivery_id"])
    return True


def verify_outbox_evidence(repo: str, record_value: dict[str, object]) -> None:
    provenance_value = record_value.get("provenance")
    if isinstance(provenance_value, dict):
        payload = record_value.get("payload")
        if not isinstance(payload, dict):
            die("v2 outbox payload is invalid")
        args = argparse.Namespace(
            input_type="task:awf-review-v3",
            branch=str(record_value["branch"]),
            commit=str(payload.get("commit", "")),
            **{field: payload.get(field, "") for field in _PROVENANCE_FIELDS},
        )
        provenance = provenance_from_args(args, repo, require_pr=True)
        verify_pr_remote_tuple(repo, provenance, verify_pr=True)
        if str(record_value.get("evidence_commit", "")) != provenance["head_sha"]:
            die("outbox evidence commit does not match PR provenance")
        if record_value.get("action") == "coder.review_handoff":
            report_path = payload.get("report")
            if not isinstance(report_path, str):
                die("coder outbox is missing its ImplementationReport path")
            tracked = git_out(
                repo,
                "ls-tree",
                "-r",
                "--name-only",
                str(provenance["head_sha"]),
                "--",
                report_path,
            ).splitlines()
            if report_path not in tracked:
                die("coder outbox ImplementationReport is not tracked at the PR head")
        return
    branch = str(record_value.get("branch", ""))
    evidence_commit = str(record_value.get("evidence_commit", ""))
    if git(repo, "check-ref-format", "--branch", branch) != 0:
        die("outbox branch is invalid")
    if not _COMMIT_RE.fullmatch(evidence_commit):
        die("outbox evidence commit is invalid")
    remote_ref = f"refs/remotes/origin/{branch}"
    refspec = f"+refs/heads/{branch}:{remote_ref}"
    if git(repo, "fetch", "--no-tags", "origin", refspec) != 0:
        die("cannot refresh the outbox remote branch")
    resolved = git_out(repo, "rev-parse", "--verify", f"{evidence_commit}^{{commit}}")
    remote_head = git_out(repo, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    if not resolved or resolved != evidence_commit or remote_head != evidence_commit:
        die("outbox evidence no longer matches the remote task branch")
    if record_value.get("action") == "coder.review_handoff":
        payload = record_value.get("payload")
        report_path = payload.get("report") if isinstance(payload, dict) else None
        if not isinstance(report_path, str):
            die("coder outbox is missing its ImplementationReport path")
        tracked = git_out(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            evidence_commit,
            "--",
            report_path,
        ).splitlines()
        if report_path not in tracked:
            die("coder outbox ImplementationReport is not tracked at the evidence commit")


def resume_outbox(
    a: argparse.Namespace,
    role: str,
    repo: str,
    evidence: RunEvidence | None,
    input_context: dict[str, object],
) -> bool:
    delivery_id = str(input_context["delivery_id"])
    payload_sha256 = str(input_context["payload_sha256"])
    if evidence is None:
        return False
    path = delivery_state_path(evidence, "outbox", str(input_context["key"]))
    existing = _load_delivery_record(path, "outbox")
    if inbox_completed(evidence, delivery_id, payload_sha256):
        if existing is not None and existing.get("format") == "awf.outbox.v2":
            validate_outbox_record(existing)
            verify_outbox_evidence(repo, existing)
        return True
    if existing is None:
        return False
    expected_bindings = {
        "source_role": role,
        "input_key": input_context["key"],
        "input_delivery_id": input_context["delivery_id"],
        "input_payload_sha256": input_context["payload_sha256"],
        "input_source_event_id": input_context["source_event_id"],
        "branch": a.branch,
        "source_commit": a.commit,
    }
    for key, expected in expected_bindings.items():
        if existing.get(key) != expected:
            die(f"outbox {key} does not match the current Workflow input")
    validate_outbox_record(existing)
    reconcile_recovery_checkpoint_with_outbox(evidence, input_context, existing)
    status = existing.get("status")
    if status == "sent":
        if existing.get("format") == "awf.outbox.v2":
            verify_outbox_evidence(repo, existing)
        complete_inbox(evidence, delivery_id, payload_sha256)
        return True
    if status not in {"prepared", "attempting", "ambiguous"}:
        die(f"outbox has unsupported status {status!r}")
    verify_outbox_evidence(repo, existing)
    if not deliver_outbox(evidence, path, existing):
        die("failed to replay downstream outbox; source event remains unacknowledged")
    sent = _load_delivery_record(path, "outbox")
    if sent is None:
        die("sent outbox evidence disappeared during replay")
    reconcile_recovery_checkpoint_with_outbox(evidence, input_context, sent)
    complete_inbox(evidence, delivery_id, payload_sha256)
    return True


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------


def role_coder(a: argparse.Namespace) -> int:
    # Resolve to an absolute path: a relative/unresolved cwd is what makes git behave
    # differently under a service (cmd.exe) vs. an interactive shell.
    repo = str(Path(env("AWF_REPO_DIR", required=True)).resolve())
    script_dir = env("AWF_SCRIPT_DIR", required=True)
    prompt_file = os.path.join(script_dir, "executor-prompt.md")
    tool = env("AWF_TOOL", a.tool or "opencode")
    model = env("AWF_MODEL", a.model or "")
    no_push = env("AWF_NO_PUSH", "0") == "1"
    evidence = getattr(a, "evidence", None)
    input_context = validate_input_delivery(a, "coder", evidence)
    validate_delivery_selection(a, input_context, tool=tool, model=model)
    selections = reviewer_selection_contract("", fallback_tool=tool, fallback_model=model)
    provenance = None
    contract: PostflightContract | None = None
    fresh_contract_prevalidated = False
    if _is_v3(a):
        try:
            provenance = provenance_from_args(
                a,
                repo,
                require_pr=getattr(a, "input_type", "") == "task:awf-rework-v3",
            )
        except SystemExit:
            record(evidence, "fork_pr_rejected", reason="invalid_or_untrusted_provenance")
            raise

        # A malformed fresh delivery must not consume its one model-attempt budget.
        # Durable deliveries keep the existing replay order because their trusted
        # checkout may already have advanced beyond the original input commit.
        if not delivery_has_durable_state(evidence, input_context):
            try:
                fetch_and_checkout_pr_head(
                    repo,
                    provenance,
                    verify_pr=bool(provenance["pull_request"]),
                )
            except SystemExit:
                record(evidence, "fork_pr_rejected", reason="input_provenance_drift")
                raise
            card_file = str(resolve_repo_file(repo, a.card, "TaskCard"))
            if not Path(card_file).is_file():
                die(f"card not found after checkout: {card_file}")
            contract = parse_postflight_contract(card_file)
            validate_implementation_report_contract(card_file, a, evidence)
            selections = load_reviewer_selection_contract(
                card_file,
                fallback_tool=tool,
                fallback_model=model,
            )
            validate_frozen_role_selection(
                selections.coder,
                role="coder",
                tool=tool,
                model=model,
            )
            fresh_contract_prevalidated = True
    gate = pre_invocation_gate(a, "coder", evidence)

    try:
        if resume_outbox(a, "coder", repo, evidence, input_context):
            record(evidence, "outbox_replay_complete")
            return 0
    except SystemExit:
        record(evidence, "fork_pr_rejected", reason="outbox_provenance_drift")
        raise
    duplicate = gate is not None and getattr(gate, "reason", "") == "duplicate_event"
    checkpoint_path: Path | None = None
    checkpoint: dict[str, object] | None = None
    if provenance is not None and evidence is not None:
        checkpoint_path = delivery_state_path(
            evidence,
            "checkpoint",
            str(input_context["key"]),
        )
        existing_checkpoint = _load_delivery_record(
            checkpoint_path,
            "recovery checkpoint",
        )
        if duplicate and existing_checkpoint is None:
            recovered = recover_legacy_publication_checkpoint(
                evidence,
                input_context,
                branch=a.branch,
                source_commit=a.commit,
                provenance=provenance,
            )
            if recovered is None:
                die("duplicate Workflow event has no durable recovery checkpoint or outbox")
            checkpoint_path, existing_checkpoint = recovered
        checkpoint_path, checkpoint = begin_recovery_checkpoint(
            evidence,
            input_context,
            role="coder",
            branch=a.branch,
            source_commit=a.commit,
            provenance=provenance,
        )
    elif duplicate:
        die("duplicate Workflow event has no durable downstream outbox")

    recovery_phase = str(checkpoint["phase"]) if checkpoint is not None else "model_not_started"
    model_policy = recovery_model_policy(checkpoint) if checkpoint is not None else "invoke_once"
    if model_policy == "recover_or_fail":
        if checkpoint is not None and checkpoint_path is not None and evidence is not None:
            checkpoint = recover_completed_model_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
            )
            recovery_phase = str(checkpoint["phase"]) if checkpoint is not None else "model_started"
        if recovery_phase == "model_started":
            die("model invocation outcome is ambiguous; refusing to invoke it again")

    if recovery_phase == "model_not_started":
        if provenance is not None and not fresh_contract_prevalidated:
            try:
                fetch_and_checkout_pr_head(
                    repo,
                    provenance,
                    verify_pr=bool(provenance["pull_request"]),
                )
            except SystemExit:
                record(evidence, "fork_pr_rejected", reason="input_provenance_drift")
                raise
        elif provenance is None:
            fetch_and_checkout(repo, a.branch, a.commit)
        card_file = str(resolve_repo_file(repo, a.card, "TaskCard"))
        if not Path(card_file).is_file():
            die(f"card not found after checkout: {card_file}")

        # 2. Parse and freeze the TaskCard postflight contract before model starts
        if contract is None:
            contract = parse_postflight_contract(card_file)
            validate_implementation_report_contract(card_file, a, evidence)
        model_state_dir = evidence.run_dir if evidence is not None else None
        model_repo = prepare_model_workspace(repo, a.commit, state_dir=model_state_dir)
        if checkpoint is not None and checkpoint_path is not None:
            model_manifest_sha256 = durable_model_manifest_sha256(model_repo)
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "model_started",
                model_workspace=str(Path(model_repo).resolve()),
                model_manifest_sha256=model_manifest_sha256,
                model_event_id=evidence.event_id,
                model_process=tool,
            )
        model_card_file = str(resolve_repo_file(model_repo, a.card, "TaskCard"))
        log(f"coder: branch={a.branch} tool={tool} model={model or '<default>'}")
        if tool == "opencode":
            rc = tool_opencode_exec(
                model_repo,
                model_card_file,
                prompt_file,
                model,
                a.report,
                getattr(a, "review_feedback", ""),
                evidence,
            )
        else:
            die(f"coder: unsupported tool '{tool}'")
        if rc != 0:
            die(f"tool '{tool}' failed (rc={rc}); not announcing review")
        if checkpoint is not None and checkpoint_path is not None:
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "model_completed",
                model_workspace=str(Path(model_repo).resolve()),
                model_manifest_sha256=model_manifest_sha256,
                model_event_id=evidence.event_id,
                model_process=tool,
            )
        recovery_phase = "model_completed"
    elif recovery_phase in {"model_completed", "postflight_completed"}:
        facts = dict(checkpoint["facts"]) if checkpoint is not None else {}
        model_workspace = facts.get("model_workspace")
        if not isinstance(model_workspace, str) or not model_workspace:
            die("completed model checkpoint is missing its workspace")
        checkpoint, manifest_sha256 = recover_postflight_manifest(
            evidence,
            checkpoint_path,
            checkpoint,
            model_workspace,
        )
        if not isinstance(manifest_sha256, str):
            die("completed model checkpoint is missing its Git manifest")
        model_repo = restore_durable_model_manifest(
            evidence,
            model_workspace,
            manifest_sha256,
        )

    if recovery_phase == "model_completed":
        assert_model_workspace_state(model_repo, a.commit)
        if provenance is not None:
            try:
                assert_model_pr_git_state(repo, provenance)
            except SystemExit:
                record(evidence, "fork_pr_rejected", reason="model_boundary_provenance_drift")
                raise
        else:
            assert_model_git_state(repo, a.branch, a.commit)
        record(evidence, "model_git_state_verified", model_git_state="pass")
        if contract is None:
            card_file = str(resolve_repo_file(repo, a.card, "TaskCard"))
            if not Path(card_file).is_file():
                die(f"card not found after trusted checkout restore: {card_file}")
            contract = parse_postflight_contract(card_file)
            validate_implementation_report_contract(card_file, a, evidence)

        if checkpoint is not None and checkpoint_path is not None:
            checkpoint = increment_postflight_attempt(evidence, checkpoint_path, checkpoint)
        record(
            evidence,
            "postflight_start",
            postflight_started=True,
            postflight_status="running",
        )
        try:
            # 4. ImplementationReport gate — fail before any write or downstream event
            model_report = resolve_repo_file(model_repo, a.report, "ImplementationReport")
            check_report(str(model_report))

            # 5. Rerun every verification command from the frozen contract
            run_verifications(model_repo, contract)
            assert_model_git_metadata(model_repo)
            stage_model_artifact(model_repo, a.report, "ImplementationReport")

            # 6. Enforce all delta gates (paths, artifacts, secrets, diff check)
            run_postflight_delta_gates(model_repo, contract)
            assert_model_git_metadata(model_repo)
        except BaseException:
            record(evidence, "postflight_fail", postflight_status="fail")
            raise
        postflight_manifest_sha256 = (
            durable_model_manifest_sha256(model_repo) if checkpoint is not None else ""
        )
        record(
            evidence,
            "postflight_pass",
            postflight_status="pass",
            postflight_model_manifest_sha256=postflight_manifest_sha256,
        )
        if checkpoint is not None and checkpoint_path is not None:
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "postflight_completed",
                postflight_model_manifest_sha256=postflight_manifest_sha256,
            )
        recovery_phase = "postflight_completed"

    if recovery_phase == "postflight_completed":
        imported_tree = import_model_delta(model_repo, repo)
        check_report(str(resolve_repo_file(repo, a.report, "ImplementationReport")))
        if checkpoint is not None and checkpoint_path is not None:
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "model_imported",
                imported_tree=imported_tree,
            )
        recovery_phase = "model_imported"
    elif checkpoint is not None:
        facts = dict(checkpoint["facts"])
        imported_tree = str(facts.get("imported_tree", ""))
        if not _FULL_COMMIT_RE.fullmatch(imported_tree):
            die("recovery checkpoint imported tree is invalid")

    # 7. commit + push the executor's output back to the same branch
    if checkpoint is None:
        record(evidence, "commit", commit_status="running")
        if git(repo, "diff", "--cached", "--quiet") != 0:
            if git_out(repo, "write-tree") != imported_tree:
                die("trusted index changed after verified model import")
            msg = executor_commit_message(a.branch, tool)
            if git(repo, "commit", "-q", "-m", msg) != 0:
                die("git commit failed (is git user.name/user.email configured on this machine?)")
            log(f"committed executor output on {a.branch}")
        else:
            log("no changes produced by the tool")
        commit_sha = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
        record(evidence, "commit", commit_status="pass", commit_sha=commit_sha)
    elif recovery_phase == "model_imported":
        record(evidence, "commit", commit_status="running")
        current_head = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
        if current_head == a.commit:
            if git(repo, "read-tree", imported_tree) != 0:
                die("failed to restore the verified imported tree")
            if git_out(repo, "write-tree") != imported_tree:
                die("trusted index changed after verified model import")
            msg = executor_commit_message(a.branch, tool)
            if git(repo, "commit", "-q", "-m", msg) != 0:
                die("git commit failed (is git user.name/user.email configured on this machine?)")
            log(f"committed executor output on {a.branch}")
            commit_sha = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
        else:
            parent = git_out(repo, "rev-parse", "--verify", "HEAD^1")
            current_tree = git_out(repo, "rev-parse", "--verify", "HEAD^{tree}")
            if parent != a.commit or current_tree != imported_tree:
                die("trusted repository drifted after the imported-tree checkpoint")
            commit_sha = current_head
        if not _FULL_COMMIT_RE.fullmatch(commit_sha):
            die("trusted commit checkpoint is invalid")
        record(evidence, "commit", commit_status="pass", commit_sha=commit_sha)
        if checkpoint is not None and checkpoint_path is not None:
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "commit_created",
                commit_sha=commit_sha,
            )
        recovery_phase = "commit_created"
    else:
        facts = dict(checkpoint["facts"])
        commit_sha = str(facts.get("commit_sha", ""))
        current_head = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
        current_tree = git_out(repo, "rev-parse", "--verify", "HEAD^{tree}")
        if (
            not _FULL_COMMIT_RE.fullmatch(commit_sha)
            or current_head != commit_sha
            or current_tree != imported_tree
        ):
            die("trusted repository does not match the durable commit checkpoint")
    if no_push:
        die(
            "AWF_NO_PUSH=1 cannot complete the trusted coder handler; "
            "remote review handoff requires a verified push"
        )
    if provenance is not None:
        try:
            if recovery_phase == "commit_created":
                verify_upstream_base(repo, provenance)
                record(evidence, "push", push_started=True)
                provenance = push_and_verify_fork_head(repo, provenance)
                new_commit = str(provenance["head_sha"])
                record(evidence, "remote_sha_verified", remote_sha=new_commit)
                if checkpoint is not None and checkpoint_path is not None:
                    checkpoint = advance_recovery_checkpoint(
                        evidence,
                        checkpoint_path,
                        checkpoint,
                        "fork_sha_verified",
                        head_sha=new_commit,
                    )
                recovery_phase = "fork_sha_verified"
            else:
                facts = dict(checkpoint["facts"]) if checkpoint is not None else {}
                new_commit = str(facts.get("head_sha", ""))
                if new_commit != commit_sha:
                    die("fork checkpoint does not match the durable commit")
                provenance = {**provenance, "head_sha": new_commit}
                verify_pr_remote_tuple(repo, provenance, verify_pr=False)

            if recovery_phase == "fork_sha_verified":
                provenance = ensure_pull_request(repo, provenance)
                if checkpoint is not None and checkpoint_path is not None:
                    checkpoint = advance_recovery_checkpoint(
                        evidence,
                        checkpoint_path,
                        checkpoint,
                        "pr_tuple_verified",
                        verified_provenance=provenance_payload(provenance),
                    )
                recovery_phase = "pr_tuple_verified"
            else:
                facts = dict(checkpoint["facts"]) if checkpoint is not None else {}
                verified = facts.get("verified_provenance")
                if not isinstance(verified, dict):
                    die("PR checkpoint is missing verified provenance")
                provenance = {**provenance, **verified}
                verify_pr_remote_tuple(repo, provenance, verify_pr=True)
        except SystemExit:
            record(evidence, "fork_pr_rejected", reason="fork_push_or_pr_verification_failed")
            raise
    else:
        record(evidence, "push", push_started=True)
        new_commit = push_and_verify_remote_head(repo, a.branch)
        record(evidence, "remote_sha_verified", remote_sha=new_commit)
    input_type = getattr(a, "input_type", "")
    review_type = (
        "task:awf-review-v3"
        if input_type.endswith("-v3")
        else "task:awf-review-v2"
        if input_type.endswith("-v2")
        else "task:awf-review"
    )
    card_file = str(resolve_repo_file(repo, a.card, "TaskCard"))
    selections = load_reviewer_selection_contract(
        card_file,
        fallback_tool=tool,
        fallback_model=model,
    )
    validate_frozen_role_selection(
        selections.coder,
        role="coder",
        tool=tool,
        model=model,
    )
    review_base = {
        "task_id": a.branch.rsplit("/", 1)[-1],
        "branch": a.branch,
        "card": a.card,
        "commit": new_commit,
        "report": a.report,
        "review_report": a.review_report,
        "tool": selections.reviewer.tool,
        "model": selections.reviewer.model,
    }
    if provenance is not None:
        review_base.update(provenance_payload(provenance))
    review_payload = build_delivery_payload(
        "coder",
        review_type,
        review_base,
        evidence,
    )
    outbox = prepare_outbox(
        evidence,
        input_context,
        action="coder.review_handoff",
        branch=a.branch,
        source_commit=a.commit,
        evidence_commit=new_commit,
        to_role="reviewer",
        event_type=review_type,
        payload=review_payload,
        provenance=provenance,
    )
    if checkpoint is not None and checkpoint_path is not None:
        if str(checkpoint["phase"]) == "pr_tuple_verified":
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "outbox_prepared",
                outbox_delivery_id=review_payload["awf_delivery_id"],
            )
        elif str(checkpoint["phase"]) != "outbox_prepared":
            die("recovery checkpoint is inconsistent with the durable outbox")
    sent = (
        deliver_outbox(evidence, *outbox)
        if evidence is not None and outbox is not None
        else send_event("coder", "reviewer", review_type, review_payload)
    )
    if not sent:
        die("failed to send reviewer event; implementation will not be ACKed")
    if checkpoint is not None and checkpoint_path is not None:
        checkpoint = advance_recovery_checkpoint(
            evidence,
            checkpoint_path,
            checkpoint,
            "outbox_sent",
            outbox_delivery_id=review_payload["awf_delivery_id"],
        )
    complete_inbox(
        evidence,
        str(input_context["delivery_id"]),
        str(input_context["payload_sha256"]),
    )
    record(evidence, "review_event_sent", review_event_sent=True)
    return 0


def role_reviewer(a: argparse.Namespace) -> int:
    repo = str(Path(env("AWF_REPO_DIR", required=True)).resolve())
    script_dir = env("AWF_SCRIPT_DIR", required=True)
    prompt_file = os.path.join(script_dir, "reviewer-prompt.md")
    tool = env("AWF_TOOL", a.tool or "")
    model = env("AWF_MODEL", a.model or "")
    base = env("AWF_BASE", a.base or "master")
    evidence = getattr(a, "evidence", None)
    input_context = validate_input_delivery(a, "reviewer", evidence)
    validate_delivery_selection(a, input_context, tool=tool, model=model)
    provenance = None
    if _is_v3(a):
        try:
            provenance = provenance_from_args(a, repo, require_pr=True)
        except SystemExit:
            record(evidence, "fork_pr_rejected", reason="invalid_or_untrusted_provenance")
            raise
    gate = pre_invocation_gate(a, "reviewer", evidence)

    try:
        if resume_outbox(a, "reviewer", repo, evidence, input_context):
            record(evidence, "outbox_replay_complete")
            return 0
    except SystemExit:
        record(evidence, "fork_pr_rejected", reason="outbox_provenance_drift")
        raise
    duplicate = gate is not None and getattr(gate, "reason", "") == "duplicate_event"
    checkpoint_path: Path | None = None
    checkpoint: dict[str, object] | None = None
    if provenance is not None and evidence is not None and tool in {"opencode", "pi"}:
        checkpoint_path = delivery_state_path(
            evidence,
            "checkpoint",
            str(input_context["key"]),
        )
        existing_checkpoint = _load_delivery_record(
            checkpoint_path,
            "recovery checkpoint",
        )
        if duplicate and existing_checkpoint is None:
            recovered = recover_legacy_reviewer_checkpoint(
                evidence,
                input_context,
                branch=a.branch,
                source_commit=a.commit,
                provenance=provenance,
            )
            if recovered is None:
                die("duplicate reviewer event has no durable recovery checkpoint or outbox")
            checkpoint_path, existing_checkpoint = recovered
        checkpoint_path, checkpoint = begin_recovery_checkpoint(
            evidence,
            input_context,
            role="reviewer",
            branch=a.branch,
            source_commit=a.commit,
            provenance=provenance,
        )
    elif duplicate:
        die("duplicate Workflow event has no durable downstream outbox")

    recovery_phase = str(checkpoint["phase"]) if checkpoint is not None else "model_not_started"
    model_policy = recovery_model_policy(checkpoint) if checkpoint is not None else "invoke_once"
    if checkpoint is not None and recovery_phase in {
        "model_imported",
        "pr_tuple_verified",
        "outbox_prepared",
    }:
        facts = dict(checkpoint["facts"])
        expected_report_sha256 = facts.get("review_report_sha256")
        persisted_report = resolve_review_report_path(
            repo,
            a.review_report,
            a.report,
        )
        if not isinstance(expected_report_sha256, str):
            die("trusted ReviewReport does not match its recovery checkpoint")
        if persisted_report.is_file():
            if hashlib.sha256(persisted_report.read_bytes()).hexdigest() != expected_report_sha256:
                die("trusted ReviewReport does not match its recovery checkpoint")
            # The report is re-imported from the durable model workspace after
            # the trusted PR checkout has restored a clean tree.
            persisted_report.unlink()

    if provenance is not None:
        try:
            fetch_and_checkout_pr_head(repo, provenance, verify_pr=True)
        except SystemExit:
            record(evidence, "fork_pr_rejected", reason="reviewer_provenance_drift")
            raise
    else:
        fetch_and_checkout(repo, a.branch, a.commit)
    card_file = str(resolve_repo_file(repo, a.card, "TaskCard"))
    if not Path(card_file).is_file():
        die(f"card not found after checkout: {card_file}")
    selections = load_reviewer_selection_contract(
        card_file,
        fallback_tool=tool,
        fallback_model=model,
    )
    validate_frozen_role_selection(
        selections.reviewer,
        role="reviewer",
        tool=tool,
        model=model,
    )

    # ImplementationReport gate — fail before any model invocation
    implementation_report = resolve_repo_file(repo, a.report, "ImplementationReport")
    check_report(str(implementation_report))
    check_report_tracked_at_head(repo, a.report)
    review_report_path = resolve_review_report_path(
        repo,
        a.review_report,
        str(implementation_report),
    )
    if git_out(repo, "ls-files", "--", a.review_report):
        die("ReviewReport path must not replace a tracked repository file")
    review_report_path.parent.mkdir(parents=True, exist_ok=True)
    if model_policy == "recover_or_fail":
        if checkpoint is not None and checkpoint_path is not None and evidence is not None:
            recovered_checkpoint = recover_completed_model_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
            )
            if recovered_checkpoint is not None:
                checkpoint = recovered_checkpoint
                recovery_phase = str(checkpoint["phase"])
        if recovery_phase == "model_started":
            die("reviewer model invocation outcome is ambiguous; refusing to invoke it again")
    if recovery_phase == "model_not_started" and review_report_path.exists():
        review_report_path.unlink()

    base_commit = (
        str(provenance["base_sha"]) if provenance is not None else resolve_review_base(repo, base)
    )
    if recovery_phase == "model_not_started":
        log(f"reviewer: branch={a.branch} tool={tool or '<human>'} base={base}")
    reviewer_tools = {"codex", "opencode", "pi"}
    if tool == "codex" and checkpoint is None:
        rc = tool_codex_review(repo, base_commit, prompt_file, card_file, model, a.review_report)
    elif tool in reviewer_tools and recovery_phase == "model_not_started":
        model_state_dir = evidence.run_dir if evidence is not None else None
        model_repo = prepare_model_workspace(repo, a.commit, state_dir=model_state_dir)
        model_base = "awf-review-base"
        if git(model_repo, "branch", "--force", model_base, base_commit) != 0:
            die("failed to create isolated reviewer base ref")
        freeze_model_git_metadata(model_repo)
        model_card_file = str(resolve_repo_file(model_repo, a.card, "TaskCard"))
        model_review_report_path = resolve_review_report_path(
            model_repo,
            a.review_report,
            a.report,
        )
        if checkpoint is not None and checkpoint_path is not None:
            model_manifest_sha256 = durable_model_manifest_sha256(model_repo)
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "model_started",
                model_workspace=str(Path(model_repo).resolve()),
                model_manifest_sha256=model_manifest_sha256,
                model_event_id=evidence.event_id,
                model_process=tool,
            )
        if tool == "codex":
            rc = tool_codex_review(
                model_repo,
                model_base,
                prompt_file,
                model_card_file,
                model,
                str(model_review_report_path),
                evidence,
            )
        elif tool == "opencode":
            rc = tool_opencode_review(
                model_repo,
                model_base,
                prompt_file,
                model_card_file,
                model,
                str(model_review_report_path),
                evidence,
            )
        else:
            rc = tool_pi_review(
                model_repo,
                model_base,
                prompt_file,
                model_card_file,
                model,
                str(model_review_report_path),
                evidence,
            )
        if rc == 0:
            if checkpoint is not None and checkpoint_path is not None:
                checkpoint = advance_recovery_checkpoint(
                    evidence,
                    checkpoint_path,
                    checkpoint,
                    "model_completed",
                    model_workspace=str(Path(model_repo).resolve()),
                    model_manifest_sha256=model_manifest_sha256,
                    model_event_id=evidence.event_id,
                    model_process=tool,
                )
            recovery_phase = "model_completed"
    elif tool in reviewer_tools and recovery_phase != "model_not_started":
        facts = dict(checkpoint["facts"]) if checkpoint is not None else {}
        model_workspace = facts.get("model_workspace")
        if not isinstance(model_workspace, str) or not model_workspace:
            die("completed reviewer checkpoint is missing its workspace")
        checkpoint, manifest_sha256 = recover_postflight_manifest(
            evidence,
            checkpoint_path,
            checkpoint,
            model_workspace,
        )
        model_process = facts.get("model_process", "opencode")
        if (
            not isinstance(model_workspace, str)
            or not isinstance(manifest_sha256, str)
            or model_process != tool
        ):
            die("completed reviewer checkpoint is missing its durable workspace")
        model_repo = restore_durable_model_manifest(
            evidence,
            model_workspace,
            manifest_sha256,
        )
        model_base = "awf-review-base"
        rc = 0
    elif checkpoint is None:
        die("reviewer tool must be codex, opencode, or pi")
    else:
        rc = 0
    if checkpoint is not None and recovery_phase not in {
        "model_not_started",
        "model_completed",
    }:
        rc = 0
    if tool not in reviewer_tools:
        die("reviewer tool must be codex, opencode, or pi")
    if rc != 0:
        die(f"reviewer tool '{tool}' failed (rc={rc}); no verdict routed")

    if tool in reviewer_tools and recovery_phase != "model_not_started":
        assert_model_workspace_state(model_repo, a.commit)
        if git_out(model_repo, "rev-parse", "--verify", f"{model_base}^{{commit}}") != base_commit:
            die("model process changed the isolated reviewer base ref")
        if provenance is not None:
            assert_model_pr_git_state(repo, provenance)
        else:
            assert_model_git_state(repo, a.branch, a.commit)
        review_report_path = import_model_report(model_repo, repo, a.review_report)
        try:
            review_report = parse_review_report(review_report_path)
        except SystemExit:
            mark_artifact_invalid(
                evidence,
                checkpoint_path,
                checkpoint,
                "trusted ReviewReport schema validation failed",
            )
            die(
                "artifact_invalid: ReviewReport schema rejected before checkpoint advancement; "
                "same-delivery correction was attempted once and no model replay is legal"
            )
        if (
            checkpoint is not None
            and checkpoint_path is not None
            and recovery_phase == "model_completed"
        ):
            report_sha256 = hashlib.sha256(review_report_path.read_bytes()).hexdigest()
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "model_imported",
                review_report_sha256=report_sha256,
                # import_model_report stages the ReviewReport after the
                # model boundary; recovery must validate that trusted state,
                # not the pre-stage model manifest.
                postflight_model_manifest_sha256=durable_model_manifest_sha256(model_repo),
            )
            recovery_phase = "model_imported"
    elif checkpoint is not None:
        facts = dict(checkpoint["facts"])
        report_sha256 = facts.get("review_report_sha256")
        if (
            not isinstance(report_sha256, str)
            or not review_report_path.is_file()
            or hashlib.sha256(review_report_path.read_bytes()).hexdigest() != report_sha256
        ):
            die("trusted ReviewReport does not match its recovery checkpoint")
    if checkpoint is not None and checkpoint_path is not None and provenance is not None:
        if recovery_phase in {"model_imported", "pr_tuple_verified"}:
            try:
                review_report = parse_review_report(review_report_path)
            except SystemExit:
                mark_artifact_invalid(
                    evidence,
                    checkpoint_path,
                    checkpoint,
                    "trusted ReviewReport schema validation failed in legacy checkpoint",
                )
                die(
                    "artifact_invalid: legacy checkpoint report is invalid; immutable report SHA "
                    "and provenance are preserved, so only an owner-authorized replacement "
                    "delivery is legal"
                )
        if str(checkpoint["phase"]) == "model_imported":
            verify_pr_remote_tuple(repo, provenance, verify_pr=True)
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "pr_tuple_verified",
                verified_provenance=provenance_payload(provenance),
            )
        else:
            facts = dict(checkpoint["facts"])
            if facts.get("verified_provenance") != provenance_payload(provenance):
                die("reviewer PR checkpoint does not match persisted provenance")
            verify_pr_remote_tuple(repo, provenance, verify_pr=True)

    review_report = parse_review_report(review_report_path)
    verdict = review_report["verdict"]
    route = {
        "PASS": ("architect", "decision:awf-ready"),
        "REQUEST_CHANGES": ("coder", "task:awf-rework"),
        "BLOCKED": ("architect", "decision:awf-blocked"),
    }[verdict]
    if getattr(a, "input_type", "").endswith("-v3"):
        route = (route[0], f"{route[1]}-v3")
    elif getattr(a, "input_type", "").endswith("-v2"):
        route = (route[0], f"{route[1]}-v2")
    target_selection = selections.coder if verdict == "REQUEST_CHANGES" else selections.reviewer
    verdict_base = {
        "task_id": a.branch.rsplit("/", 1)[-1],
        "branch": a.branch,
        "card": a.card,
        "commit": a.commit,
        "report": a.report,
        "review_report_path": a.review_report,
        "review_report": review_report,
        "tool": target_selection.tool,
        "model": target_selection.model,
    }
    if provenance is not None:
        verdict_base.update(provenance_payload(provenance))
    payload = build_delivery_payload(
        "reviewer",
        route[1],
        verdict_base,
        evidence,
    )
    outbox = prepare_outbox(
        evidence,
        input_context,
        action=f"reviewer.{verdict.lower()}",
        branch=a.branch,
        source_commit=a.commit,
        evidence_commit=a.commit,
        to_role=route[0],
        event_type=route[1],
        payload=payload,
        provenance=provenance,
    )
    if checkpoint is not None and checkpoint_path is not None:
        if str(checkpoint["phase"]) == "pr_tuple_verified":
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "outbox_prepared",
                outbox_delivery_id=payload["awf_delivery_id"],
            )
        elif str(checkpoint["phase"]) != "outbox_prepared":
            die("reviewer recovery checkpoint is inconsistent with the durable outbox")
    sent = (
        deliver_outbox(evidence, *outbox)
        if evidence is not None and outbox is not None
        else send_event("reviewer", route[0], route[1], payload)
    )
    if not sent:
        die(f"failed to send {route[1]}; review event will not be ACKed")
    if checkpoint is not None and checkpoint_path is not None:
        checkpoint = advance_recovery_checkpoint(
            evidence,
            checkpoint_path,
            checkpoint,
            "outbox_sent",
            outbox_delivery_id=payload["awf_delivery_id"],
        )
    complete_inbox(
        evidence,
        str(input_context["delivery_id"]),
        str(input_context["payload_sha256"]),
    )
    return 0


def role_architect(a: argparse.Namespace) -> int:
    """Consume a terminal reviewer decision without invoking a model or routing again."""
    repo = env("AWF_REPO_DIR", required=True)
    evidence = getattr(a, "evidence", None)
    input_context = validate_input_delivery(a, "architect", evidence)
    if inbox_completed(
        evidence,
        str(input_context["delivery_id"]),
        str(input_context["payload_sha256"]),
    ):
        if evidence is not None:
            evidence.record("terminal_decision_replayed", decision_type=a.input_type)
        return 0

    try:
        embedded = json.loads(a.review_feedback)
    except json.JSONDecodeError:
        die("architect review feedback must be valid JSON")
    review_report = validate_embedded_review_report(embedded)
    expected_verdict = "PASS" if "ready" in a.input_type else "BLOCKED"
    if review_report["verdict"] != expected_verdict:
        die("architect decision type does not match the embedded ReviewReport verdict")

    provenance = None
    if _is_v3(a):
        provenance = provenance_from_args(a, repo, require_pr=True)
    terminal_repo = prepare_terminal_workspace(
        repo,
        a.branch,
        a.commit,
        provenance=provenance,
        evidence=evidence,
    )

    card_path = resolve_repo_file(terminal_repo, a.card, "TaskCard")
    if not card_path.is_file():
        die("TaskCard is not tracked at the terminal decision commit")
    check_repo_file_tracked_at_head(terminal_repo, a.card, "TaskCard")
    report_path = resolve_repo_file(terminal_repo, a.report, "ImplementationReport")
    check_report(str(report_path))
    check_report_tracked_at_head(terminal_repo, a.report)
    resolve_review_report_path(terminal_repo, a.review_report, a.report)

    if _control_plane_enabled():
        task_id = a.branch.rsplit("/", 1)[-1]
        run_id = getattr(a, "run_id", "") or os.environ.get("AWF_RUN_ID") or f"task-{task_id}"
        state_root = (
            evidence.state_dir
            if evidence is not None
            else Path(
                os.environ.get(
                    "AWF_STATE_ROOT",
                    str(Path.home() / ".local/state/agent-workflow"),
                )
            )
        )
        pull_request = {
            "number": int(provenance["pull_request"]) if provenance is not None else 0,
            "base_sha": str(provenance["base_sha"]) if provenance is not None else "",
            "head_sha": str(provenance["head_sha"]) if provenance is not None else a.commit,
        }
        terminal = {
            "verdict": expected_verdict,
            "reason": "review_passed" if expected_verdict == "PASS" else "review_blocked",
            "event_id": evidence.event_id if evidence is not None else int(a.event_id),
            "delivery_id": str(input_context["delivery_id"]),
            "payload_sha256": str(input_context["payload_sha256"]),
            "source_event_id": int(input_context["source_event_id"]),
            "branch": a.branch,
            "commit": a.commit,
            "artifacts": {
                "implementation": {
                    "path": a.report,
                    "sha256": "sha256:" + hashlib.sha256(report_path.read_bytes()).hexdigest(),
                },
                "review": {
                    "path": a.review_report,
                    "sha256": canonical_payload_sha256(review_report),
                },
            },
            "pull_request": pull_request,
            "ci": {"status": "not_recorded", "conclusion": ""},
            "merge": {"status": "not_merged", "commit": ""},
        }
        try:
            RunLedger(state_root, run_id).mark_terminal(
                terminal_state="completed" if expected_verdict == "PASS" else "blocked",
                terminal=terminal,
            )
        except ControlPlaneDenied as exc:
            record(evidence, "terminal_ledger_failed", reason=str(exc))
            die(f"terminal decision could not be persisted: {exc}")

    if evidence is not None:
        evidence.record(
            "terminal_decision_verified",
            decision_type=a.input_type,
            verdict=expected_verdict,
            branch=a.branch,
            commit=a.commit,
            pull_request=provenance["pull_request"] if provenance is not None else 0,
        )
    complete_inbox(
        evidence,
        str(input_context["delivery_id"]),
        str(input_context["payload_sha256"]),
    )
    return 0


ROLES = {"architect": role_architect, "coder": role_coder, "reviewer": role_reviewer}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="awf_role", description="Agent Workflow role handler")
    p.add_argument("role", choices=sorted(ROLES))
    p.add_argument("--event-id", required=True, type=int)
    p.add_argument("--input-type", default="")
    p.add_argument("--delivery-id", default="")
    p.add_argument("--payload-sha256", default="")
    p.add_argument("--source-event-id", type=int, default=0)
    p.add_argument("--branch", required=True)
    p.add_argument("--card", default="")
    p.add_argument("--commit", default="")
    p.add_argument("--model", default="")
    p.add_argument("--tool", default="")
    p.add_argument("--report", default="")
    p.add_argument("--review-report", dest="review_report", default="")
    p.add_argument("--review-feedback", dest="review_feedback", default="")
    p.add_argument("--base", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--stage", default="")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--max-attempts", type=int, default=1)
    p.add_argument("--rework-budget", type=int, default=1)
    p.add_argument("--terminal-state", default="")
    p.add_argument("--route-override", default="")
    p.add_argument("--provenance-version", default="")
    p.add_argument("--upstream-repo", default="")
    p.add_argument("--upstream-remote", default="")
    p.add_argument("--base-ref", default="")
    p.add_argument("--base-sha", default="")
    p.add_argument("--head-repo", default="")
    p.add_argument("--head-remote", default="")
    p.add_argument("--head-ref", default="")
    p.add_argument("--head-sha", default="")
    p.add_argument("--pull-request", type=int, default=0)
    a = p.parse_args(argv)
    if a.event_id < 1:
        p.error("--event-id must be a positive integer")
    a.evidence = RunEvidence(a.event_id, a.role)
    a.evidence.record(
        "handler_start",
        handler_pid=os.getpid(),
        postflight_started=False,
        postflight_status="not_started",
    )
    try:
        rc = ROLES[a.role](a)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
        a.evidence.record("handler_exit", handler_rc=exit_code)
        raise
    except BaseException:
        a.evidence.record("handler_exit", handler_rc=1)
        raise
    a.evidence.record("handler_exit", handler_rc=rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
