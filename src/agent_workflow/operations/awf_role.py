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
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agent_workflow import __version__ as AWF_VERSION
from agent_workflow.operations.awf_control_plane import (
    DEFAULT_ROUTES,
    ControlPlaneDenied,
    RunLedger,
    authority_manifest_binding,
    build_context_packet,
    load_authority_manifest,
)
from agent_workflow.operations.awf_delivery import canonical_payload_sha256, make_delivery_id
from agent_workflow.operations.awf_executor import (
    DEVNULL,
    PIPE,
    CompletedProcess,
    ExecutionFailure,
)
from agent_workflow.operations.awf_executor import (
    run as run_command,
)
from agent_workflow.operations.awf_executor import (
    start as start_command,
)
from agent_workflow.operations.awf_feedback import (
    MAX_COMBINED_REPORT_BYTES,
    FindingContractError,
    capture_report_finding,
)
from agent_workflow.operations.awf_feedback import (
    default_state_root as feedback_state_root,
)
from agent_workflow.operations.awf_taskcard import (
    ReviewerSelectionContract,
    TaskCardContractError,
    reviewer_selection_contract,
)
from agent_workflow.resources import templates_dir
from agent_workflow.runtime import (
    ATTACH_INPUT,
    CODEX_FINDING_INSTRUCTIONS,
    OPENCODE_FINDING_INSTRUCTIONS,
    ArtifactError,
    InvocationSpec,
    RenderedInvocation,
    WorkspaceError,
    WorkspaceSpec,
    import_workspace_delta,
    prepare_workspace,
    render_provider_invocation,
    restore_workspace_manifest,
    serialize_workspace_delta,
    workspace_control_sha256,
    workspace_manifest,
    workspace_manifest_sha256,
)
from agent_workflow.runtime import (
    PostflightContract as RuntimePostflightContract,
)
from agent_workflow.runtime import (
    artifact_fact as runtime_artifact_fact,
)
from agent_workflow.runtime import (
    assert_frozen_workspace as runtime_assert_frozen_workspace,
)
from agent_workflow.runtime import (
    assert_workspace_state as runtime_assert_workspace_state,
)
from agent_workflow.runtime import (
    bind_environment as bind_workspace_environment,
)
from agent_workflow.runtime import (
    freeze_workspace as runtime_freeze_workspace,
)
from agent_workflow.runtime import (
    normalize_review_envelope as runtime_normalize_review_envelope,
)
from agent_workflow.runtime import (
    normalize_rework_feedback as runtime_normalize_rework_feedback,
)
from agent_workflow.runtime import (
    parse_postflight_contract as runtime_parse_postflight_contract,
)
from agent_workflow.runtime import (
    parse_review_report as runtime_parse_review_report,
)
from agent_workflow.runtime import path_is_denied as runtime_path_is_denied
from agent_workflow.runtime import (
    postflight_result as runtime_postflight_result,
)
from agent_workflow.runtime import (
    resolve_repo_file as runtime_resolve_repo_file,
)
from agent_workflow.runtime import (
    resolve_review_report_path as runtime_resolve_review_report_path,
)
from agent_workflow.runtime import (
    scan_secret_text as runtime_scan_secret_text,
)
from agent_workflow.runtime import (
    validate_embedded_review_report as runtime_validate_embedded_review_report,
)
from agent_workflow.runtime import (
    validate_implementation_report as runtime_validate_implementation_report,
)
from agent_workflow.runtime import (
    validate_postflight_paths as runtime_validate_postflight_paths,
)
from agent_workflow.runtime import (
    validate_secret_observation as runtime_validate_secret_observation,
)
from agent_workflow.runtime import (
    validate_stage_artifact_contract as runtime_validate_stage_artifact_contract,
)
from agent_workflow.state_root import state_root_binding


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


def direct_entry_state_root() -> Path:
    """Resolve the explicit legacy handler order: environment, then platform default."""
    configured = os.environ.get("AWF_STATE_ROOT")
    return Path(configured).expanduser().resolve() if configured else workflow_state_directory()


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
            "state_root_sha256": state_root_binding(self.state_dir),
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
_DELIVERY_ID_RE = re.compile(r"^awf:[0-9a-f]{64}$")
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


def workflow_run_id(a: argparse.Namespace) -> str:
    task_id = a.branch.rsplit("/", 1)[-1]
    return getattr(a, "run_id", "") or os.environ.get("AWF_RUN_ID") or f"task-{task_id}"


def provider_invocation_binding(
    a: argparse.Namespace,
    role: str,
    input_context: dict[str, object],
    gate: object | None,
    *,
    tool: str,
    model: str,
) -> tuple[str, str, str, str]:
    """Project current authority into one opaque, non-authorizing renderer identity."""
    run_id = workflow_run_id(a)
    task_id = a.branch.rsplit("/", 1)[-1]
    invocation_id = str(input_context["key"])
    authorization_sha256 = canonical_payload_sha256(
        {
            "run_id": run_id,
            "task_id": task_id,
            "invocation_id": invocation_id,
            "delivery_id": input_context["delivery_id"],
            "payload_sha256": input_context["payload_sha256"],
            "source_event_id": input_context["source_event_id"],
            "event_type": getattr(a, "input_type", ""),
            "role": role,
            "tool": tool,
            "model": model,
            "source_commit": a.commit,
            "gate_allowed": getattr(gate, "allowed", None),
            "gate_reason": getattr(gate, "reason", ""),
            "gate_run_id": getattr(gate, "run_id", ""),
            "gate_sequence": int(getattr(gate, "sequence", 0)),
        }
    ).removeprefix("sha256:")
    return invocation_id, run_id, task_id, authorization_sha256


def pre_invocation_gate(
    a: argparse.Namespace, role: str, evidence: RunEvidence | None
) -> object | None:
    """Persist and atomically authorize the stage before any model adapter call."""
    if not _control_plane_enabled():
        return None
    event_type = getattr(a, "input_type", "") or (
        "task:awf-review-v2" if role == "reviewer" else "task:awf-impl-v2"
    )
    run_id = workflow_run_id(a)
    stage = (
        getattr(a, "stage", "")
        or os.environ.get("AWF_STAGE")
        or ("review" if role == "reviewer" else "rework" if "rework" in event_type else "implement")
    )
    state_root = evidence.state_dir if evidence is not None else direct_entry_state_root()
    ledger = RunLedger(state_root, run_id)
    frozen_base = a.commit
    run_contract_sha256 = ""
    if ledger.ledger_path.exists():
        _, current_packet = ledger.recover()
        frozen_base = str(current_packet["frozen_base"])
        run_contract_sha256 = str(current_packet.get("run_contract_sha256", ""))
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
        state_root_sha256=state_root_binding(state_root),
        run_contract_sha256=run_contract_sha256,
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
    root_binding = value.get("state_root_sha256", "")
    if root_binding and root_binding != state_root_binding(path.parents[2]):
        die(f"{label} state-root binding does not match its location")
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
            "state_root_sha256",
            "workspace_lineage_delivery_id",
            "workspace_lineage_checkpoint_sha256",
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
    root_binding = record_value.get("state_root_sha256", "")
    if root_binding and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(root_binding)):
        die("recovery checkpoint state-root binding is invalid")
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
    lineage_delivery = record_value.get("workspace_lineage_delivery_id", "")
    lineage_checkpoint = record_value.get("workspace_lineage_checkpoint_sha256", "")
    if bool(lineage_delivery) != bool(lineage_checkpoint):
        die("recovery checkpoint workspace lineage binding is incomplete")
    if lineage_delivery and not _DELIVERY_ID_RE.fullmatch(str(lineage_delivery)):
        die("recovery checkpoint workspace lineage delivery is invalid")
    if lineage_checkpoint and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(lineage_checkpoint)):
        die("recovery checkpoint workspace lineage digest is invalid")


def begin_recovery_checkpoint(
    evidence: RunEvidence,
    input_context: dict[str, object],
    *,
    role: str,
    branch: str,
    source_commit: str,
    provenance: dict[str, object],
    workspace_lineage_delivery_id: str = "",
    workspace_lineage_checkpoint_sha256: str = "",
) -> tuple[Path, dict[str, object]]:
    path = delivery_state_path(evidence, "checkpoint", str(input_context["key"]))
    record_value: dict[str, object] = {
        "format": "awf.recovery-checkpoint.v1",
        "state_root_sha256": state_root_binding(evidence.state_dir),
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
    if workspace_lineage_delivery_id or workspace_lineage_checkpoint_sha256:
        record_value.update(
            {
                "workspace_lineage_delivery_id": workspace_lineage_delivery_id,
                "workspace_lineage_checkpoint_sha256": workspace_lineage_checkpoint_sha256,
            }
        )
    validate_recovery_checkpoint(record_value)
    existing = _load_delivery_record(path, "recovery checkpoint")
    if existing is not None:
        validate_recovery_checkpoint(existing)
        legacy_record = dict(record_value)
        legacy_record.pop("state_root_sha256")
        if _checkpoint_immutable(existing) == _checkpoint_immutable(legacy_record):
            existing = {**existing, "state_root_sha256": state_root_binding(evidence.state_dir)}
            _atomic_write_json(path, existing)
        elif _checkpoint_immutable(existing) != _checkpoint_immutable(record_value):
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


def replacement_eligibility(
    checkpoint: dict[str, object], outbox: dict[str, object] | None
) -> dict[str, str]:
    """Return immutable old-delivery lineage only for the narrow no-effect ambiguity case."""
    validate_recovery_checkpoint(checkpoint)
    if outbox is not None:
        validate_outbox_record(outbox)
        die("replacement is denied while the old delivery has an outgoing effect")
    if checkpoint.get("phase") != "model_started":
        die("replacement requires an ambiguous model_started checkpoint")
    facts = checkpoint["facts"]
    if not isinstance(facts, dict) or not isinstance(facts.get("model_event_id"), int):
        die("replacement checkpoint has no exact old provider process identity")
    if any(
        key in facts
        for key in (
            "postflight_status",
            "imported_tree",
            "commit_sha",
            "head_sha",
            "verified_provenance",
        )
    ):
        die("replacement is denied after an old Git, PR, or merge effect")
    provenance = checkpoint["provenance"]
    if not isinstance(provenance, dict) or not isinstance(provenance.get("base_sha"), str):
        die("replacement checkpoint provenance is invalid")
    return {
        "old_delivery_id": str(checkpoint["input_delivery_id"]),
        "old_payload_sha256": str(checkpoint["input_payload_sha256"]),
        "old_checkpoint_sha256": canonical_payload_sha256(checkpoint),
        "old_role": str(checkpoint["role"]),
        "old_event_id": str(facts["model_event_id"]),
        "old_branch": str(checkpoint["branch"]),
        "old_source_commit": str(checkpoint["source_commit"]),
        "old_base_sha": str(provenance["base_sha"]),
        "old_provenance_sha256": canonical_payload_sha256(checkpoint["provenance"]),
    }


def replacement_evidence(
    state_root: Path, *, old_event_id: int, old_role: str, old_delivery_id: str
) -> dict[str, str]:
    """Read one explicitly named old delivery without scanning or mutating state."""
    if old_role not in {"coder", "reviewer"} or old_event_id < 1:
        die("replacement old delivery identity is invalid")
    if not _DELIVERY_ID_RE.fullmatch(old_delivery_id):
        die("replacement old delivery ID is invalid")
    digest = hashlib.sha256(old_delivery_id.encode("utf-8")).hexdigest()
    root = Path(state_root).resolve() / f"event-{old_event_id}"
    checkpoint_path = root / "checkpoint" / old_role / f"{digest}.json"
    checkpoint = _load_delivery_record(checkpoint_path, "replacement checkpoint")
    if checkpoint is None:
        die("replacement old checkpoint is missing")
    if (
        checkpoint.get("role") != old_role
        or checkpoint.get("input_delivery_id") != old_delivery_id
        or checkpoint.get("input_key") != old_delivery_id
    ):
        die("replacement old checkpoint identity drifted")
    facts = checkpoint.get("facts")
    if not isinstance(facts, dict) or facts.get("model_event_id") != old_event_id:
        die("replacement old provider process identity drifted")
    process = facts.get("model_process")
    log_path = root / "handler.log"
    if process not in {"opencode", "codex", "pi"} or not log_path.is_file():
        die("replacement old provider termination evidence is missing")
    try:
        records = [
            json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line
        ]
    except (OSError, json.JSONDecodeError):
        die("replacement old provider termination evidence is unreadable")
    exits = [
        item
        for item in records
        if isinstance(item, dict)
        and item.get("event_id") == old_event_id
        and item.get("role") == old_role
        and item.get("phase") == f"{process}_exit"
        and isinstance(item.get(f"{process}_rc"), int)
        and item.get(f"{process}_rc") != 0
    ]
    handler_exits = [
        item
        for item in records
        if isinstance(item, dict)
        and item.get("event_id") == old_event_id
        and item.get("role") == old_role
        and item.get("phase") == "handler_exit"
        and isinstance(item.get("handler_rc"), int)
        and item.get("handler_rc") != 0
    ]
    if not exits or not handler_exits:
        die("replacement old provider process is not proven stopped")
    outbox_path = root / "outbox" / old_role / f"{digest}.json"
    outbox = _load_delivery_record(outbox_path, "replacement outbox")
    return replacement_eligibility(checkpoint, outbox)


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
        "state_root_sha256": state_root_binding(evidence.state_dir),
        "role": evidence.role,
        "delivery_id": delivery_id,
        "payload_sha256": payload_sha256,
        "status": "completed",
    }
    if existing is not None:
        legacy_expected = {
            key: value for key, value in expected.items() if key != "state_root_sha256"
        }
        if existing != legacy_expected and existing != expected:
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
    root_binding = existing.get("state_root_sha256", "")
    if root_binding and root_binding != state_root_binding(evidence.state_dir):
        die("Workflow delivery state-root binding does not match its location")
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
    "AWF_FINDING_ENABLED",
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
            if upper in e and e[upper] != value:
                die(f"conflicting case-insensitive model environment key {upper}")
            e[upper] = value
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
    e.setdefault("PYTHONDONTWRITEBYTECODE", "1")
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
    # Native managers launch the handler by exact python/pythonw path, but their
    # inherited PATH need not contain that environment's bin/Scripts directory.
    # Frozen `python -m ...` verification must resolve to the installed runner.
    runtime_bin = os.path.abspath(os.path.dirname(sys.executable))
    path_entries = [
        entry
        for entry in e.get("PATH", "").split(os.pathsep)
        if entry and os.path.normcase(os.path.abspath(entry)) != os.path.normcase(runtime_bin)
    ]
    e["PATH"] = os.pathsep.join([runtime_bin, *path_entries])
    return e


def resolve_verification_argv(
    argv: list[str],
    *,
    os_name: str = os.name,
    executable: str = sys.executable,
) -> list[str]:
    """Resolve the frozen Python alias to the current Windows runner."""
    if os_name != "nt" or not argv or argv[0].casefold() not in {"python", "python.exe"}:
        return list(argv)
    runtime = Path(executable).absolute()
    runtime_python = runtime.with_name("python.exe")
    if runtime.name.casefold() not in {"python.exe", "pythonw.exe"} or not runtime_python.is_file():
        return list(argv)
    return [str(runtime_python), *argv[1:]]


_CAPTURED_STDOUT_MAX_BYTES = 16 * 1024
_CAPTURED_STDERR_MAX_BYTES = 16 * 1024


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


def read_bounded_stream(stream, max_bytes: int) -> tuple[str, bool]:
    """Drain one text stream to EOF while retaining only a bounded UTF-8 prefix."""
    retained = bytearray()
    truncated = False
    while True:
        chunk = stream.read(4096)
        if not chunk:
            break
        data = chunk.encode("utf-8", "replace") if isinstance(chunk, str) else bytes(chunk)
        remaining = max_bytes - len(retained)
        if remaining > 0:
            retained.extend(data[:remaining])
        if len(data) > max(remaining, 0):
            truncated = True
    return retained.decode("utf-8", "replace"), truncated


def _is_closed_stdin_error(exc: OSError, *, os_name: str = os.name) -> bool:
    """Recognize platform-specific writes to a child-closed stdin pipe."""
    return isinstance(exc, BrokenPipeError) or (os_name == "nt" and exc.errno == errno.EINVAL)


def spawn(
    argv: list[str],
    *,
    cwd: str | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    evidence: RunEvidence | None = None,
    tracked_phase: str | None = None,
    stdout_path: str | None = None,
    stdout_max_bytes: int = _CAPTURED_STDOUT_MAX_BYTES,
    stderr_path: str | None = None,
    stderr_max_bytes: int = _CAPTURED_STDERR_MAX_BYTES,
    discard_output: bool = False,
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
    if stderr_path is not None and (stdout_path is None or evidence is not None):
        die("captured model stderr requires untracked captured stdout")
    if discard_output and (
        stdout_path is not None or stderr_path is not None or evidence is not None
    ):
        die("discarded output is only supported for untracked commands")
    executable = Path(argv[0]).name if argv else "<empty>"
    log(f"exec: {executable} argc={len(argv)}")
    if evidence is not None and tracked_phase is not None:
        started = time.monotonic()
        try:
            proc = start_command(
                argv,
                cwd=cwd,
                stdin=PIPE if stdin is not None else DEVNULL,
                # pythonw has no usable inherited stdout on Windows. Model CLIs
                # still write progress there, so discard it explicitly unless
                # this call owns a bounded capture path.
                stdout=PIPE if stdout_path is not None else DEVNULL,
                stderr=PIPE,
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
        stderr_capture: dict[str, object] = {"text": "", "truncated": False, "error": None}
        stderr_thread = None
        cleanup_started = threading.Event()
        stderr_stream = getattr(proc, "stderr", None)
        if stderr_stream is not None:

            def drain_tracked_stderr() -> None:
                try:
                    text, truncated = read_bounded_stream(stderr_stream, _CAPTURED_STDERR_MAX_BYTES)
                except BaseException as exc:
                    if not cleanup_started.is_set():
                        stderr_capture["error"] = exc
                        if proc.poll() is None:
                            proc.kill()
                        stdout_stream = getattr(proc, "stdout", None)
                        if stdout_stream is not None:
                            stdout_stream.close()
                else:
                    stderr_capture.update(text=text, truncated=truncated)

            stderr_thread = threading.Thread(target=drain_tracked_stderr, daemon=True)
            stderr_thread.start()
        try:
            if stdout_path is not None:
                stdout_text, stdout_limit_exceeded = read_bounded_stdout(proc, stdout_max_bytes)
            elif stderr_thread is not None:
                if stdin is not None:
                    if proc.stdin is None:
                        die("tracked model stdin pipe is unavailable")
                    try:
                        proc.stdin.write(stdin)
                        proc.stdin.close()
                    except OSError as exc:
                        if not _is_closed_stdin_error(exc):
                            raise
                        # A provider may exit normally with a nonzero result before
                        # consuming all input. Preserve its real rc and stderr.
                        try:
                            proc.stdin.close()
                        except OSError as close_exc:
                            if not _is_closed_stdin_error(close_exc):
                                raise
                proc.wait()
                stdout_text = ""
                stdout_limit_exceeded = False
            else:
                proc.communicate(stdin)
                stdout_text = ""
                stdout_limit_exceeded = False
        except BaseException:
            cleanup_started.set()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            if stderr_stream is not None:
                stderr_stream.close()
            if stderr_thread is not None:
                stderr_thread.join(timeout=5.0)
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
        if stderr_thread is not None:
            stderr_thread.join(timeout=5.0)
            if stderr_thread.is_alive():
                cleanup_started.set()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                stderr_stream.close()
                stderr_thread.join(timeout=0.1)
                raise RuntimeError("tracked model stderr did not close after process exit")
        stderr_error = stderr_capture["error"]
        if isinstance(stderr_error, BaseException):
            raise stderr_error
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
            die(f"captured model stdout exceeds {stdout_max_bytes // 1024} KiB")
        if stdout_path is not None and proc.returncode == 0:
            atomic_write_text(Path(stdout_path), stdout_text or "")
        if proc.returncode != 0 and stderr_thread is not None:
            stderr_text = str(stderr_capture["text"])
            if stderr_capture["truncated"] is True:
                stderr_text += f"\n[stderr truncated at {_CAPTURED_STDERR_MAX_BYTES} bytes]\n"
            atomic_write_text(evidence.run_dir / f"{tracked_phase}.stderr", stderr_text)
        return proc.returncode
    if stdout_path is not None:
        proc = start_command(
            argv,
            cwd=cwd,
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE if stderr_path is not None else None,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env or child_env(),
            allow_shell_wrapper=True,
        )
        stderr_capture: dict[str, object] = {"text": "", "truncated": False, "error": None}
        stderr_thread = None
        cleanup_started = threading.Event()
        if stderr_path is not None:
            if proc.stderr is None:
                die("captured model stderr pipe is unavailable")

            def drain_stderr() -> None:
                try:
                    text, truncated = read_bounded_stream(proc.stderr, stderr_max_bytes)
                except BaseException as exc:
                    if not cleanup_started.is_set():
                        stderr_capture["error"] = exc
                        if proc.poll() is None:
                            proc.kill()
                        if proc.stdout is not None:
                            proc.stdout.close()
                else:
                    stderr_capture.update(text=text, truncated=truncated)

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()
        try:
            stdout_text, stdout_limit_exceeded = read_bounded_stdout(proc, stdout_max_bytes)
        except BaseException as stdout_error:
            cleanup_started.set()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            if proc.stderr is not None:
                proc.stderr.close()
            if stderr_thread is not None:
                stderr_thread.join(timeout=5.0)
            stderr_error = stderr_capture["error"]
            if isinstance(stderr_error, BaseException):
                raise stderr_error
            raise stdout_error
        if stderr_thread is not None:
            stderr_thread.join(timeout=5.0)
            if stderr_thread.is_alive():
                cleanup_started.set()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                if proc.stderr is not None:
                    proc.stderr.close()
                stderr_thread.join(timeout=0.1)
                raise RuntimeError("captured model stderr did not close after process exit")
        stderr_error = stderr_capture["error"]
        if isinstance(stderr_error, BaseException):
            raise stderr_error
        if stdout_limit_exceeded:
            die(f"captured model stdout exceeds {stdout_max_bytes // 1024} KiB")
        if proc.returncode == 0:
            atomic_write_text(Path(stdout_path), stdout_text)
        elif stderr_path is not None:
            stderr_text = str(stderr_capture["text"])
            if stderr_capture["truncated"] is True:
                stderr_text += f"\n[stderr truncated at {stderr_max_bytes} bytes]\n"
            atomic_write_text(Path(stderr_path), stderr_text)
        return proc.returncode
    proc = run_command(
        argv,
        cwd=cwd,
        input=stdin,
        stdin=DEVNULL if stdin is None else None,
        stdout=DEVNULL if discard_output else None,
        stderr=DEVNULL if discard_output else None,
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


def capture_dogfood_finding(
    report_path: Path,
    *,
    input_context: dict[str, object],
    source_role: str,
    source_tool: str,
    evidence: RunEvidence | None,
) -> None:
    """Strip one optional Finding before existing report validation/import.

    Feedback persistence is best-effort and cannot affect business success.
    Reserved-envelope contract errors and strip failures remain artifact
    failures because continuing would contaminate the formal report.
    """
    if os.environ.get("AWF_FINDING_ENABLED") != "1":
        return
    state_root = evidence.state_dir if evidence is not None else feedback_state_root
    delivery_identity = str(input_context.get("delivery_id") or input_context["key"])

    def record_best_effort(**fields: object) -> None:
        try:
            record(evidence, "finding_capture", **fields)
        except OSError as exc:
            log(f"WARN: Finding evidence was not persisted ({type(exc).__name__})")

    try:
        result = capture_report_finding(
            report_path,
            state_root,
            input_delivery_id=delivery_identity,
            source_role=source_role,
            source_tool=source_tool,
            awf_version=AWF_VERSION,
            warn=lambda message: log(f"WARN: {message}"),
        )
    except FindingContractError as exc:
        record_best_effort(finding_status="artifact_invalid")
        die(f"artifact_invalid: {exc}")
    except OSError as exc:
        record_best_effort(finding_status="strip_failed")
        die(f"artifact_invalid: Finding strip failed ({type(exc).__name__})")
    if result.status == "absent":
        return
    fields: dict[str, object] = {"finding_status": result.status}
    if result.occurrence_id:
        fields["finding_occurrence_id"] = result.occurrence_id
    if result.reason:
        fields["finding_rejection_reason"] = result.reason
    record_best_effort(**fields)


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


def _model_git_manifest(
    workspace: str,
    *,
    include_semantic_index: bool = True,
) -> dict[str, tuple[str, str]]:
    """Compatibility view over the installed Runtime workspace manifest."""
    if not include_semantic_index:
        die("control-only model manifest is internal to the Runtime workspace boundary")
    try:
        return workspace_manifest(workspace, _runtime_workspace_environment())
    except WorkspaceError as exc:
        die(str(exc))


def freeze_model_git_metadata(workspace: str) -> None:
    """Delegate the trusted pre-model Git-control freeze to the installed Runtime."""
    try:
        runtime_freeze_workspace(workspace, _runtime_workspace_environment())
    except WorkspaceError as exc:
        die(str(exc))


def assert_model_git_metadata(workspace: str) -> None:
    """Reject model Git-control drift through the installed Runtime boundary."""
    try:
        runtime_assert_frozen_workspace(workspace, _runtime_workspace_environment())
    except WorkspaceError as exc:
        die(str(exc))


def durable_model_manifest_sha256(workspace: str) -> str:
    try:
        return workspace_manifest_sha256(workspace, _runtime_workspace_environment())
    except WorkspaceError as exc:
        die(str(exc))


def durable_model_control_sha256(workspace: str) -> str:
    """Bind Git control metadata that must survive a trusted HEAD/index transition."""
    try:
        return workspace_control_sha256(workspace, _runtime_workspace_environment())
    except WorkspaceError as exc:
        die(str(exc))


def _assert_durable_model_workspace_path(evidence: RunEvidence, workspace: str) -> Path:
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
    return resolved


def advance_model_workspace_to_trusted_commit(
    evidence: RunEvidence,
    workspace: str,
    trusted_repo: str,
    *,
    source_commit: str,
    imported_tree: str,
    trusted_commit: str,
    expected_control_sha256: str,
) -> str:
    """Advance one no-remote workspace after the trusted commit is fully verified."""
    resolved = _assert_durable_model_workspace_path(evidence, workspace)
    if not all(_FULL_COMMIT_RE.fullmatch(value) for value in (source_commit, trusted_commit)):
        die("trusted workspace transition commit is invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", imported_tree):
        die("trusted workspace transition tree is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_control_sha256):
        die("trusted workspace transition control binding is invalid")
    if durable_model_control_sha256(str(resolved)) != expected_control_sha256:
        die("durable model workspace control metadata does not match its checkpoint")
    if git_out(str(resolved), "remote"):
        die("durable model workspace gained a Git remote before trusted transition")
    trusted_parent = git_out(trusted_repo, "rev-parse", "--verify", f"{trusted_commit}^1")
    trusted_tree = git_out(trusted_repo, "rev-parse", "--verify", f"{trusted_commit}^{{tree}}")
    if trusted_parent != source_commit or trusted_tree != imported_tree:
        die("trusted commit does not match the verified workspace transition")

    current_head = git_out(str(resolved), "rev-parse", "--verify", "HEAD^{commit}")
    if current_head == source_commit:
        if git_out(str(resolved), "write-tree") != imported_tree:
            die("durable model workspace tree does not match the imported checkpoint")
        if postflight_git(str(resolved), "diff", "--quiet").returncode != 0:
            die("durable model workspace changed after trusted import")
        fetched = run_command(
            [
                "git",
                "-C",
                str(resolved),
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                trusted_repo,
                trusted_commit,
            ],
            stdin=DEVNULL,
            stdout=DEVNULL,
            stderr=DEVNULL,
            env=postflight_git_env(),
        )
        if fetched.returncode != 0:
            die("failed to import the trusted commit into the durable model workspace")
        if postflight_git(
            str(resolved), "checkout", "--detach", "--force", trusted_commit
        ).returncode:
            die("failed to advance the durable model workspace to the trusted commit")
    elif current_head != trusted_commit:
        die("durable model workspace HEAD is outside its trusted transition")

    git_dir = resolved / ".git"
    for name in ("FETCH_HEAD", "ORIG_HEAD"):
        path = git_dir / name
        if path.exists():
            path.unlink()
    logs = git_dir / "logs"
    if logs.exists():
        shutil.rmtree(logs)
    if durable_model_control_sha256(str(resolved)) != expected_control_sha256:
        die("trusted workspace transition changed immutable Git control metadata")
    if git_out(str(resolved), "rev-parse", "--verify", "HEAD^{commit}") != trusted_commit:
        die("durable model workspace did not reach the trusted commit")
    if git_out(str(resolved), "rev-parse", "--verify", "HEAD^{tree}") != imported_tree:
        die("durable model workspace trusted tree is inconsistent")
    if git_out(str(resolved), "remote") or git_out(str(resolved), "status", "--porcelain"):
        die("durable model workspace is not clean after trusted transition")
    freeze_model_git_metadata(str(resolved))
    return durable_model_manifest_sha256(str(resolved))


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
            isinstance(report_sha, str) and artifact_sha256(path) == report_sha
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
    resolved = _assert_durable_model_workspace_path(evidence, workspace)
    try:
        return restore_workspace_manifest(
            str(resolved),
            expected_sha256,
            _runtime_workspace_environment(),
        )
    except WorkspaceError as exc:
        die(str(exc))


def _implement_lineage_checkpoint(
    evidence: RunEvidence,
    a: argparse.Namespace,
    provenance: dict[str, object],
) -> tuple[Path, dict[str, object]]:
    ledger, packet = RunLedger(evidence.state_dir, workflow_run_id(a)).recover()
    if packet.get("branch") != a.branch or packet.get("current_stage_evidence_commit") != a.commit:
        die("rework context packet does not match its branch/current commit")
    events = ledger.get("events")
    if not isinstance(events, list):
        die("rework ledger events are invalid")
    deliveries = {
        str(event.get("delivery_id"))
        for event in events
        if isinstance(event, dict)
        and event.get("role") == "coder"
        and event.get("stage") == "implement"
        and event.get("status") == "authorized"
        and _DELIVERY_ID_RE.fullmatch(str(event.get("delivery_id", "")))
    }
    if len(deliveries) != 1:
        die("rework requires exactly one authorized implement workspace lineage")
    delivery_id = next(iter(deliveries))
    checkpoint_path = delivery_state_path(evidence, "checkpoint", delivery_id)
    checkpoint = _load_delivery_record(checkpoint_path, "implement workspace lineage checkpoint")
    if checkpoint is None:
        die("rework implement workspace lineage checkpoint is missing")
    validate_recovery_checkpoint(checkpoint)
    facts = dict(checkpoint["facts"])
    if (
        checkpoint.get("role") != "coder"
        or checkpoint.get("input_delivery_id") != delivery_id
        or checkpoint.get("branch") != a.branch
        or checkpoint.get("phase") != "outbox_sent"
        or facts.get("head_sha") != a.commit
        or facts.get("trusted_workspace_commit_sha") != a.commit
        or facts.get("verified_provenance") != provenance_payload(provenance)
    ):
        die("rework implement workspace lineage does not match its trusted handoff")
    for field, pattern in (
        ("imported_tree", r"[0-9a-f]{40}"),
        ("trusted_workspace_manifest_sha256", r"sha256:[0-9a-f]{64}"),
    ):
        if not re.fullmatch(pattern, str(facts.get(field, ""))):
            die(f"rework implement workspace lineage {field} is invalid")
    return checkpoint_path, checkpoint


def resolve_fresh_rework_workspace_lineage(
    evidence: RunEvidence,
    a: argparse.Namespace,
    provenance: dict[str, object],
) -> tuple[str, str]:
    _, checkpoint = _implement_lineage_checkpoint(evidence, a, provenance)
    return str(checkpoint["input_delivery_id"]), canonical_payload_sha256(checkpoint)


def restore_rework_workspace_lineage(
    evidence: RunEvidence,
    a: argparse.Namespace,
    provenance: dict[str, object],
    checkpoint: dict[str, object],
) -> tuple[str, str]:
    delivery_id = str(checkpoint.get("workspace_lineage_delivery_id", ""))
    expected_checkpoint_sha256 = str(checkpoint.get("workspace_lineage_checkpoint_sha256", ""))
    lineage_path = delivery_state_path(evidence, "checkpoint", delivery_id)
    lineage = _load_delivery_record(lineage_path, "implement workspace lineage checkpoint")
    if lineage is None or canonical_payload_sha256(lineage) != expected_checkpoint_sha256:
        die("rework implement workspace lineage checkpoint changed")
    _, current = _implement_lineage_checkpoint(evidence, a, provenance)
    if current != lineage:
        die("rework implement workspace lineage is no longer unique and exact")
    facts = dict(lineage["facts"])
    workspace = str(facts.get("model_workspace", ""))
    manifest_sha256 = str(facts.get("trusted_workspace_manifest_sha256", ""))
    restored = restore_durable_model_manifest(evidence, workspace, manifest_sha256)
    assert_model_workspace_state(restored, a.commit)
    return restored, manifest_sha256


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


def _runtime_workspace_environment() -> tuple[tuple[str, str], ...]:
    """Bind the exact credential-free Git environment once per Runtime workspace call."""
    try:
        return bind_workspace_environment(postflight_git_env())
    except WorkspaceError as exc:
        die(str(exc))


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
    """Create a fresh no-remote clone through the installed Runtime boundary."""
    parent = (
        Path(state_dir).resolve()
        if state_dir is not None
        else Path(tempfile.gettempdir()).resolve()
    )
    try:
        prepared = prepare_workspace(
            WorkspaceSpec(
                source_repo=str(Path(source_repo).resolve()),
                expected_commit=expected_commit,
                state_dir=str(parent),
                workspace_prefix=workspace_prefix,
                environment=_runtime_workspace_environment(),
            )
        )
    except WorkspaceError as exc:
        die(str(exc))
    return prepared.path


def assert_model_workspace_state(workspace: str, expected_commit: str) -> None:
    """Reject workspace state drift through the installed Runtime boundary."""
    try:
        runtime_assert_workspace_state(
            workspace,
            expected_commit,
            _runtime_workspace_environment(),
        )
    except WorkspaceError as exc:
        die(str(exc))


def import_model_delta(workspace: str, trusted_repo: str) -> str:
    """Apply one Runtime-verified exact delta to the trusted local checkout."""
    environment = _runtime_workspace_environment()
    try:
        delta = serialize_workspace_delta(workspace, environment)
        return import_workspace_delta(
            delta,
            str(Path(trusted_repo).resolve()),
            environment,
        )
    except WorkspaceError as exc:
        die(str(exc))


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
    workspace_path = Path(tempfile.mkdtemp(prefix="terminal-workspace-", dir=parent)).resolve()
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
    """Validate an ImplementationReport through the installed Artifact boundary."""
    try:
        runtime_validate_implementation_report(Path(report_path))
    except ArtifactError as exc:
        die(str(exc))


def artifact_sha256(path: Path, relative_path: str | None = None) -> str:
    """Return the Runtime-bound exact raw Artifact digest."""
    try:
        return runtime_artifact_fact(path, relative_path).sha256
    except ArtifactError as exc:
        die(str(exc))


def check_report_tracked_at_head(repo: str, relative_path: str) -> None:
    """Reject ignored or stale local reports that are absent from the dispatched commit."""
    check_repo_file_tracked_at_head(repo, relative_path, "ImplementationReport")


def check_repo_file_tracked_at_head(repo: str, relative_path: str, label: str) -> None:
    """Reject a local file unless its exact repository-relative path is tracked at HEAD."""
    tracked = git_out(repo, "ls-files", "--", relative_path).splitlines()
    if relative_path not in tracked:
        die(f"{label} is not tracked by the dispatched commit")


def normalize_machine_review_envelope(workspace: str, report_path: str) -> None:
    """Normalize through the installed Artifact boundary."""
    runtime_normalize_review_envelope(resolve_repo_file(workspace, report_path, "ReviewReport"))


def resolve_review_report_path(repo: str, report_path: str, implementation_report: str) -> Path:
    """Resolve through the installed Artifact boundary."""
    try:
        return runtime_resolve_review_report_path(Path(repo), report_path, implementation_report)
    except ArtifactError as exc:
        die(str(exc))


def resolve_repo_file(repo: str, relative_path: str, label: str) -> Path:
    """Resolve through the installed Artifact boundary."""
    try:
        return runtime_resolve_repo_file(Path(repo), relative_path, label)
    except ArtifactError as exc:
        die(str(exc))


def parse_review_report(report_path: Path) -> dict[str, object]:
    """Validate and normalize through the installed Artifact boundary."""
    try:
        return runtime_parse_review_report(report_path).review.as_payload()
    except ArtifactError as exc:
        die(str(exc))


def validate_embedded_review_report(data: object) -> dict[str, object]:
    try:
        return runtime_validate_embedded_review_report(data).as_payload()
    except ArtifactError as exc:
        die(str(exc))


# ---------------------------------------------------------------------------
# Postflight contract
# ---------------------------------------------------------------------------


class PostflightContract:
    """List-shaped compatibility view of the immutable Runtime contract."""

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

    def runtime_contract(self) -> RuntimePostflightContract:
        return RuntimePostflightContract(
            tuple(self.allowed_paths),
            tuple(tuple(command) for command in self.verification_commands),
        )


def _path_is_denied(path: str) -> bool:
    """Compatibility probe delegated to the installed Artifact policy."""
    return runtime_path_is_denied(path)


def parse_postflight_contract(card_path: str) -> PostflightContract:
    """Parse through the installed Runtime and retain the legacy list-shaped view."""
    try:
        contract = runtime_parse_postflight_contract(Path(card_path), sys.executable)
    except ArtifactError as exc:
        die(str(exc))
    return PostflightContract(
        allowed_paths=list(contract.allowed_paths),
        verification_commands=[list(command) for command in contract.verification_commands],
    )


def validate_implementation_report_contract(
    card_path: str,
    a: argparse.Namespace,
    evidence: RunEvidence | None,
) -> None:
    """Fail a production delivery before model invocation when artifact identity drifts."""
    if not _is_v3(a):
        return
    try:
        runtime_validate_stage_artifact_contract(
            card_path=Path(card_path),
            task_id=a.branch.rsplit("/", 1)[-1],
            required_report_path=a.report,
        )
    except ArtifactError as exc:
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
        rc = spawn(
            resolve_verification_argv(argv),
            cwd=repo,
            env=verification_env(),
            discard_output=True,
        )
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


def run_postflight_delta_gates(repo: str, contract: PostflightContract):
    """Collect local observations and delegate every validation decision.

    Must be called after ``run_verifications`` and before ``git add``.
    """
    delta_paths = _collect_delta_paths(repo)
    runtime_contract = contract.runtime_contract()
    try:
        runtime_validate_postflight_paths(runtime_contract, tuple(delta_paths))
    except ArtifactError as exc:
        die(str(exc))
    secret_observation_sha256 = _narrow_secret_scan(repo, delta_paths)
    checked = postflight_git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "HEAD",
        "--check",
    )
    try:
        return runtime_postflight_result(
            tuple(delta_paths), secret_observation_sha256, checked.returncode
        )
    except ArtifactError as exc:
        die(str(exc))


# ---------------------------------------------------------------------------
# Narrow secret scan
# ---------------------------------------------------------------------------


def _scan_text(text: str) -> str | None:
    """Compatibility probe delegated to the installed Artifact policy."""
    return runtime_scan_secret_text(text)


def _narrow_secret_scan(repo: str, delta_paths: list[str] | None = None) -> str:
    """Collect exact secret observations and delegate the validation decision.

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

    tracked_added_lines: list[tuple[str, str]] = []
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
                tracked_added_lines.append((path, line[1:]))

    untracked_contents: list[tuple[str, str]] = []
    unreadable_untracked: list[str] = []
    if untracked_out:
        for path in untracked_out.split("\0"):
            if not path:
                continue
            full = os.path.join(repo, path)
            if os.path.isfile(full):
                try:
                    content = Path(full).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    unreadable_untracked.append(path)
                    continue
                untracked_contents.append((path, content))
    try:
        return runtime_validate_secret_observation(
            tuple(tracked_added_lines),
            tuple(untracked_contents),
            tuple(unreadable_untracked),
        )
    except ArtifactError as exc:
        die(str(exc))


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


def _provider_spec(
    binding: tuple[str, str, str, str] | None,
    *,
    role: str,
    provider: str,
    model: str,
    executable: str,
    workspace: str,
    input_path: str,
    input_text: str,
    report_path: str,
    provider_args: tuple[str, ...] = (),
) -> InvocationSpec:
    root = Path(workspace).resolve()

    def absolute(path: str) -> str:
        candidate = Path(path)
        return str((candidate if candidate.is_absolute() else root / candidate).resolve())

    environment = tuple(sorted(model_env(str(root)).items()))
    if binding is None:
        direct_sha256 = canonical_payload_sha256(
            {
                "role": role,
                "provider": provider,
                "model": model,
                "executable": executable,
                "workspace": str(root),
                "input_path": absolute(input_path),
                "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                "report_path": report_path,
                "report_target": absolute(report_path),
                "provider_args": provider_args,
                "environment": dict(environment),
            }
        ).removeprefix("sha256:")
        binding = (f"direct-{direct_sha256}", "direct-provider", "direct", direct_sha256)
    invocation_id, run_id, task_id, authorization_sha256 = binding
    return InvocationSpec(
        invocation_id=invocation_id,
        run_id=run_id,
        task_id=task_id,
        authorization_sha256=authorization_sha256,
        role=role,
        provider=provider,
        model=model,
        executable=executable,
        workspace=str(root),
        input_path=absolute(input_path),
        input_text=input_text,
        report_path=report_path,
        provider_args=provider_args,
        environment=environment,
    )


def spawn_rendered(
    rendered: RenderedInvocation,
    *,
    evidence: RunEvidence | None = None,
    tracked_phase: str | None = None,
    stdout_path: str | None = None,
    stdout_max_bytes: int = _CAPTURED_STDOUT_MAX_BYTES,
    stderr_path: str | None = None,
    stderr_max_bytes: int = _CAPTURED_STDERR_MAX_BYTES,
) -> int:
    if not rendered.environment:
        die("provider environment is not bound")
    try:
        stdin = None if rendered.stdin is None else rendered.stdin.decode("utf-8")
    except UnicodeDecodeError:
        die("provider stdin is not UTF-8 text")
    for item in rendered.file_inputs:
        path = Path(item.path)
        if path.exists() and (not path.is_file() or path.read_bytes() != item.content):
            die("provider file input conflicts with its rendered identity")
        try:
            text = item.content.decode("utf-8")
        except UnicodeDecodeError:
            die("provider file input is not UTF-8 text")
        atomic_write_text(path, text)
        if path.read_bytes() != item.content:
            die("provider file input changed before process start")
    return spawn(
        [rendered.executable, *rendered.argv],
        cwd=rendered.cwd,
        stdin=stdin,
        env=dict(rendered.environment),
        evidence=evidence,
        tracked_phase=tracked_phase,
        stdout_path=stdout_path,
        stdout_max_bytes=stdout_max_bytes,
        stderr_path=stderr_path,
        stderr_max_bytes=stderr_max_bytes,
    )


def tool_opencode_exec(
    repo: str,
    card_file: str,
    prompt_file: str,
    model: str,
    implementation_report_path: str,
    review_feedback: str = "",
    evidence: RunEvidence | None = None,
    binding: tuple[str, str, str, str] | None = None,
) -> int:
    """Run OpenCode as an executor: edit code in `repo` per the card + prompt."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    prompt = read_text(prompt_file)
    normalized_feedback = normalize_rework_feedback(review_feedback) if review_feedback else ""
    instructions = prompt
    instructions += (
        f"\n\nWrite the complete ImplementationReport to exactly: {implementation_report_path}\n"
    )
    if os.environ.get("AWF_FINDING_ENABLED") == "1":
        instructions += OPENCODE_FINDING_INSTRUCTIONS
    if normalized_feedback:
        instructions += "\n\n--- Structured reviewer feedback to correct ---\n\n"
        instructions += normalized_feedback
    spec = _provider_spec(
        binding,
        role="coder",
        provider="opencode",
        model=model,
        executable=binp,
        workspace=repo,
        input_path=card_file,
        input_text=instructions,
        report_path=implementation_report_path,
        provider_args=(ATTACH_INPUT,),
    )
    return spawn_rendered(
        render_provider_invocation(spec),
        evidence=evidence,
        tracked_phase="opencode" if evidence is not None else None,
    )


def tool_codex_exec(
    repo: str,
    card_file: str,
    prompt_file: str,
    model: str,
    implementation_report_path: str,
    review_feedback: str = "",
    evidence: RunEvidence | None = None,
    binding: tuple[str, str, str, str] | None = None,
) -> int:
    """Run Codex only inside the existing isolated writable model workspace."""
    instructions = read_text(prompt_file) + (
        f"\n\nWrite the complete ImplementationReport to exactly: {implementation_report_path}\n"
    )
    if review_feedback:
        instructions += (
            "\n\n--- Structured reviewer feedback to correct ---\n\n"
            + normalize_rework_feedback(review_feedback)
        )
    spec = _provider_spec(
        binding,
        role="coder",
        provider="codex",
        model=model,
        executable=env("AWF_CODEX_BIN", "codex"),
        workspace=repo,
        input_path=card_file,
        input_text=instructions,
        report_path=implementation_report_path,
    )
    return spawn_rendered(
        render_provider_invocation(spec),
        evidence=evidence,
        tracked_phase="codex" if evidence is not None else None,
    )


def tool_pi_exec(
    repo: str,
    card_file: str,
    prompt_file: str,
    model: str,
    implementation_report_path: str,
    review_feedback: str = "",
    evidence: RunEvidence | None = None,
    binding: tuple[str, str, str, str] | None = None,
) -> int:
    """Run Pi only inside the existing isolated writable model workspace."""
    instructions = read_text(prompt_file) + (
        f"\n\nWrite the complete ImplementationReport to exactly: {implementation_report_path}\n"
    )
    if review_feedback:
        instructions += (
            "\n\n--- Structured reviewer feedback to correct ---\n\n"
            + normalize_rework_feedback(review_feedback)
        )
    spec = _provider_spec(
        binding,
        role="coder",
        provider="pi",
        model=model,
        executable=env("AWF_PI_BIN", "pi"),
        workspace=repo,
        input_path=card_file,
        input_text=instructions,
        report_path=implementation_report_path,
    )
    return spawn_rendered(
        render_provider_invocation(spec),
        evidence=evidence,
        tracked_phase="pi" if evidence is not None else None,
    )


def normalize_rework_feedback(raw: str) -> str:
    """Return bounded validated findings without forwarding report prose."""
    if len(raw.encode("utf-8")) > 16 * 1024:
        die("review feedback exceeds 16 KiB")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(key)
            value[key] = item
        return value

    try:
        data = json.loads(raw, object_pairs_hook=unique)
        return runtime_normalize_rework_feedback(data)
    except (json.JSONDecodeError, ValueError, ArtifactError) as exc:
        if isinstance(exc, ArtifactError):
            die(str(exc))
        die("review feedback is malformed or contains duplicate fields")


def tool_codex_review(
    repo: str,
    base: str,
    prompt_file: str,
    card_file: str,
    model: str,
    review_report_path: str,
    evidence: RunEvidence | None = None,
    binding: tuple[str, str, str, str] | None = None,
) -> int:
    """Run Codex review and persist its final response at the exact report path."""
    binp = env("AWF_CODEX_BIN", "codex")
    prompt = read_text(prompt_file)
    template_path = templates_dir() / "artifacts/review-report.md"
    review_report_template = read_text(str(template_path))
    card_text = read_text(card_file) if card_file and Path(card_file).is_file() else ""
    invocation_input = prompt
    invocation_input += (
        f"\n\nReview the committed branch diff against the base ref `{base}`. "
        "Use Git read-only commands to inspect that exact comparison."
    )
    invocation_input += (
        "\n\nYour final response is persisted verbatim as the ReviewReport. "
        "Return the complete filled-in Markdown report itself; do not merely summarize "
        "the verdict or say that you wrote a file."
        f"\n\nReviewReport output path: {review_report_path}\n"
        "\n--- Required ReviewReport template ---\n\n" + review_report_template
    )
    if os.environ.get("AWF_FINDING_ENABLED") == "1":
        invocation_input += CODEX_FINDING_INSTRUCTIONS
    if card_text:
        invocation_input += "\n\n--- TaskCard (acceptance criteria to verify) ---\n\n" + card_text
    input_path = card_file if card_file and Path(card_file).is_file() else review_report_path
    spec = _provider_spec(
        binding,
        role="reviewer",
        provider="codex",
        model=model,
        executable=binp,
        workspace=repo,
        input_path=input_path,
        input_text=invocation_input,
        report_path=review_report_path,
    )
    return spawn_rendered(
        render_provider_invocation(spec),
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
    binding: tuple[str, str, str, str] | None = None,
) -> int:
    """Fallback reviewer using OpenCode (when Codex is unavailable)."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    attached_card = card_file if card_file and Path(card_file).is_file() else ""
    instructions = read_text(prompt_file)
    instructions += f"\n\nWrite the complete ReviewReport to exactly: {review_report_path}\n"
    if os.environ.get("AWF_FINDING_ENABLED") == "1":
        instructions += OPENCODE_FINDING_INSTRUCTIONS
    spec = _provider_spec(
        binding,
        role="reviewer",
        provider="opencode",
        model=model,
        executable=binp,
        workspace=repo,
        input_path=attached_card or review_report_path,
        input_text=instructions,
        report_path=review_report_path,
        provider_args=(ATTACH_INPUT,) if attached_card else (),
    )
    return spawn_rendered(
        render_provider_invocation(spec),
        evidence=evidence,
        tracked_phase="opencode" if evidence is not None else None,
    )


def tool_pi_review(
    repo: str,
    base: str,
    prompt_file: str,
    card_file: str,
    model: str,
    review_report_path: str,
    evidence: RunEvidence | None = None,
    binding: tuple[str, str, str, str] | None = None,
) -> int:
    """Run Pi as a read-only reviewer and persist stdout as the ReviewReport."""
    binp = env("AWF_PI_BIN", "pi")
    template_path = templates_dir() / "artifacts/review-report.md"
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
        spec = _provider_spec(
            binding,
            role="reviewer",
            provider="pi",
            model=model,
            executable=binp,
            workspace=repo,
            input_path=str(context_path),
            input_text=context,
            report_path=review_report_path,
            provider_args=(base,),
        )
        return spawn_rendered(
            render_provider_invocation(spec),
            evidence=evidence,
            tracked_phase="pi" if evidence is not None else None,
            stdout_path=review_report_path,
            stdout_max_bytes=MAX_COMBINED_REPORT_BYTES,
        )

    context_path = Path(repo) / ".awf" / "pi-review-context.md"
    try:
        return invoke(context_path)
    finally:
        context_path.unlink(missing_ok=True)


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
    root_binding = record_value.get("state_root_sha256", "")
    if root_binding and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(root_binding)):
        die("outbox state-root binding is invalid")
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


def terminal_delivery_chain_matches(
    state_root: Path,
    *,
    prepared_delivery_id: str,
    prepared_payload_sha256: str,
    terminal_input_context: dict[str, object],
    branch: str,
    provenance: dict[str, object],
    reviewer_verdict: str,
) -> bool:
    """Verify coder -> reviewer -> architect durable causality without replaying transport."""

    def load(role: str, input_delivery_id: str) -> dict[str, object] | None:
        digest = hashlib.sha256(input_delivery_id.encode("utf-8")).hexdigest()
        path = state_root / "outbox" / role / f"{digest}.json"
        try:
            value = _load_delivery_record(path, f"{role} causal outbox")
            if value is not None:
                validate_outbox_record(value)
            return value
        except SystemExit:
            return None

    coder = load("coder", prepared_delivery_id)
    if coder is None:
        return False
    expected_provenance = provenance_payload(provenance)
    if (
        coder.get("input_delivery_id") != prepared_delivery_id
        or coder.get("input_payload_sha256") != prepared_payload_sha256
        or coder.get("action") != "coder.review_handoff"
        or coder.get("branch") != branch
        or coder.get("provenance") != expected_provenance
        or coder.get("status") not in {"prepared", "sent", "ambiguous"}
    ):
        return False
    reviewer_delivery_id = coder.get("delivery_id")
    if not isinstance(reviewer_delivery_id, str):
        return False
    reviewer = load("reviewer", reviewer_delivery_id)
    expected_action = "reviewer.pass" if reviewer_verdict == "PASS" else "reviewer.blocked"
    coder_payload = coder.get("payload")
    reviewer_payload = reviewer.get("payload") if isinstance(reviewer, dict) else None
    if (
        not isinstance(reviewer, dict)
        or not isinstance(coder_payload, dict)
        or not isinstance(reviewer_payload, dict)
        or reviewer.get("input_delivery_id") != reviewer_delivery_id
        or reviewer.get("input_payload_sha256") != coder.get("payload_sha256")
        or reviewer.get("input_source_event_id") != coder_payload.get("awf_source_event_id")
        or reviewer.get("action") != expected_action
        or reviewer.get("branch") != branch
        or reviewer.get("provenance") != expected_provenance
        or reviewer.get("status") not in {"prepared", "sent", "ambiguous"}
        or reviewer.get("delivery_id") != terminal_input_context.get("delivery_id")
        or reviewer.get("payload_sha256") != terminal_input_context.get("payload_sha256")
        or reviewer_payload.get("awf_source_event_id")
        != terminal_input_context.get("source_event_id")
    ):
        return False
    return True


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
        "state_root_sha256": state_root_binding(evidence.state_dir),
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
        legacy_record = dict(record_value)
        legacy_record.pop("state_root_sha256")
        if _outbox_immutable(existing) == _outbox_immutable(legacy_record):
            existing = {**existing, "state_root_sha256": state_root_binding(evidence.state_dir)}
            _atomic_write_json(path, existing)
        elif _outbox_immutable(existing) != _outbox_immutable(record_value):
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
    renderer_binding = provider_invocation_binding(
        a, "coder", input_context, gate, tool=tool, model=model
    )

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
        workspace_lineage_delivery_id = ""
        workspace_lineage_checkpoint_sha256 = ""
        if getattr(a, "input_type", "") == "task:awf-rework-v3":
            if existing_checkpoint is None:
                (
                    workspace_lineage_delivery_id,
                    workspace_lineage_checkpoint_sha256,
                ) = resolve_fresh_rework_workspace_lineage(evidence, a, provenance)
            else:
                workspace_lineage_delivery_id = str(
                    existing_checkpoint.get("workspace_lineage_delivery_id", "")
                )
                workspace_lineage_checkpoint_sha256 = str(
                    existing_checkpoint.get("workspace_lineage_checkpoint_sha256", "")
                )
        checkpoint_path, checkpoint = begin_recovery_checkpoint(
            evidence,
            input_context,
            role="coder",
            branch=a.branch,
            source_commit=a.commit,
            provenance=provenance,
            workspace_lineage_delivery_id=workspace_lineage_delivery_id,
            workspace_lineage_checkpoint_sha256=workspace_lineage_checkpoint_sha256,
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
        if (
            getattr(a, "input_type", "") == "task:awf-rework-v3"
            and checkpoint is not None
            and evidence is not None
            and provenance is not None
        ):
            model_repo, model_manifest_sha256 = restore_rework_workspace_lineage(
                evidence,
                a,
                provenance,
                checkpoint,
            )
        else:
            model_repo = prepare_model_workspace(repo, a.commit, state_dir=model_state_dir)
            if checkpoint is not None:
                model_manifest_sha256 = durable_model_manifest_sha256(model_repo)
        if checkpoint is not None and checkpoint_path is not None:
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
                binding=renderer_binding,
            )
        elif tool == "codex":
            rc = tool_codex_exec(
                model_repo,
                model_card_file,
                prompt_file,
                model,
                a.report,
                getattr(a, "review_feedback", ""),
                evidence,
                binding=renderer_binding,
            )
        elif tool == "pi":
            rc = tool_pi_exec(
                model_repo,
                model_card_file,
                prompt_file,
                model,
                a.report,
                getattr(a, "review_feedback", ""),
                evidence,
                binding=renderer_binding,
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
        postflight_step = "capture_finding"
        try:
            model_report = resolve_repo_file(model_repo, a.report, "ImplementationReport")
            capture_dogfood_finding(
                model_report,
                input_context=input_context,
                source_role="coder",
                source_tool=tool,
                evidence=evidence,
            )
            # 4. ImplementationReport gate — fail before any write or downstream event
            postflight_step = "validate_report"
            check_report(str(model_report))

            # 5. Rerun every verification command from the frozen contract
            postflight_step = "run_verifications"
            run_verifications(model_repo, contract)
            postflight_step = "verify_git_metadata_after_verification"
            assert_model_git_metadata(model_repo)
            postflight_step = "stage_implementation_report"
            stage_model_artifact(model_repo, a.report, "ImplementationReport")

            # 6. Enforce all delta gates (paths, artifacts, secrets, diff check)
            postflight_step = "run_delta_gates"
            run_postflight_delta_gates(model_repo, contract)
            postflight_step = "verify_git_metadata_after_delta"
            assert_model_git_metadata(model_repo)
        except BaseException as exc:
            record(
                evidence,
                "postflight_fail",
                postflight_status="fail",
                postflight_failure_step=postflight_step,
                postflight_error_type=type(exc).__name__,
            )
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
                trusted_workspace_source_commit=a.commit,
                trusted_workspace_control_sha256=durable_model_control_sha256(model_repo),
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
            facts = dict(checkpoint["facts"])
            model_workspace = str(facts.get("model_workspace", ""))
            workspace_control_sha256 = str(facts.get("trusted_workspace_control_sha256", ""))
            trusted_workspace_manifest_sha256 = advance_model_workspace_to_trusted_commit(
                evidence,
                model_workspace,
                repo,
                source_commit=a.commit,
                imported_tree=imported_tree,
                trusted_commit=commit_sha,
                expected_control_sha256=workspace_control_sha256,
            )
            checkpoint = advance_recovery_checkpoint(
                evidence,
                checkpoint_path,
                checkpoint,
                "commit_created",
                commit_sha=commit_sha,
                trusted_workspace_commit_sha=commit_sha,
                trusted_workspace_manifest_sha256=trusted_workspace_manifest_sha256,
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


def _remove_delivered_review_report(repo: str, a: argparse.Namespace) -> None:
    """Remove the managed copy after its durable downstream outbox is sent."""
    review_report_path = resolve_review_report_path(repo, a.review_report, a.report)
    try:
        review_report_path.unlink(missing_ok=True)
    except OSError as exc:
        log(f"warning: failed to remove delivered ReviewReport: {exc}")


def _remove_completed_prior_review_report(
    repo: str,
    evidence: RunEvidence | None,
    input_context: dict[str, object],
) -> None:
    """Remove only an exact prior-card report already consumed by Architect."""
    if evidence is None:
        return
    status = git_out(repo, "status", "--porcelain", "--untracked-files=all")
    if not status:
        return
    matches = [
        re.fullmatch(r"\?\? (\.awf/artifacts/review-report-[A-Za-z0-9._-]+\.md)", line)
        for line in status.splitlines()
    ]
    if not matches or any(match is None for match in matches):
        return

    outbox_dir = evidence.state_dir / "outbox" / "reviewer"
    for match in matches:
        assert match is not None
        relative_path = match.group(1)
        report_path = Path(repo) / Path(relative_path)
        try:
            report_markdown = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return
        candidates: list[dict[str, object]] = []
        for outbox_path in sorted(outbox_dir.glob("*.json")):
            try:
                outbox = _load_delivery_record(outbox_path, "prior reviewer outbox")
            except SystemExit:
                continue
            if not isinstance(outbox, dict):
                continue
            payload = outbox.get("payload")
            embedded = payload.get("review_report") if isinstance(payload, dict) else None
            if (
                outbox.get("format") != "awf.outbox.v2"
                or outbox.get("source_role") != "reviewer"
                or outbox.get("action") != "reviewer.pass"
                or outbox.get("input_delivery_id") == input_context.get("delivery_id")
                or not isinstance(payload, dict)
                or payload.get("review_report_path") != relative_path
                or not isinstance(payload.get("report"), str)
                or not isinstance(embedded, dict)
                or embedded.get("markdown") != report_markdown
            ):
                continue
            try:
                validate_outbox_record(outbox)
                resolved = resolve_review_report_path(
                    repo,
                    relative_path,
                    str(payload["report"]),
                )
            except SystemExit:
                continue
            if resolved != report_path.resolve():
                continue
            if outbox.get("status") == "sent":
                candidates.append(outbox)
                continue
            if outbox.get("status") != "ambiguous":
                continue
            delivery_id = str(outbox.get("delivery_id", ""))
            payload_sha256 = str(outbox.get("payload_sha256", ""))
            digest = hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()
            try:
                completed = _load_delivery_record(
                    evidence.state_dir / "inbox" / "architect" / f"{digest}.json",
                    "prior Architect inbox",
                )
            except SystemExit:
                continue
            if completed == {
                "format": "awf.inbox.v1",
                "state_root_sha256": state_root_binding(evidence.state_dir),
                "role": "architect",
                "delivery_id": delivery_id,
                "payload_sha256": payload_sha256,
                "status": "completed",
            }:
                candidates.append(outbox)
        if len(candidates) != 1:
            return

    for match in matches:
        assert match is not None
        relative_path = match.group(1)
        (Path(repo) / relative_path).unlink()
        record(
            evidence,
            "prior_review_report_removed",
            review_report_path=relative_path,
        )


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
    try:
        if resume_outbox(a, "reviewer", repo, evidence, input_context):
            _remove_delivered_review_report(repo, a)
            record(evidence, "outbox_replay_complete")
            return 0
    except SystemExit:
        record(evidence, "fork_pr_rejected", reason="outbox_provenance_drift")
        raise
    _remove_completed_prior_review_report(repo, evidence, input_context)
    gate = pre_invocation_gate(a, "reviewer", evidence)
    renderer_binding = provider_invocation_binding(
        a, "reviewer", input_context, gate, tool=tool, model=model
    )
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
            if artifact_sha256(persisted_report, a.review_report) != expected_report_sha256:
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
        rc = tool_codex_review(
            repo,
            base_commit,
            prompt_file,
            card_file,
            model,
            a.review_report,
            binding=renderer_binding,
        )
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
                binding=renderer_binding,
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
                binding=renderer_binding,
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
                binding=renderer_binding,
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
        model_review_report_path = resolve_review_report_path(
            model_repo,
            a.review_report,
            a.report,
        )
        # The real importer rejects a missing model-side report. Keep the capture hook
        # conditional so recovery tests can replace the importer without changing its
        # established three-argument contract.
        if model_review_report_path.is_file():
            capture_dogfood_finding(
                model_review_report_path,
                input_context=input_context,
                source_role="reviewer",
                source_tool=tool,
                evidence=evidence,
            )
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
            report_sha256 = artifact_sha256(review_report_path, a.review_report)
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
            or artifact_sha256(review_report_path, a.review_report) != report_sha256
        ):
            die("trusted ReviewReport does not match its recovery checkpoint")
    else:
        capture_dogfood_finding(
            review_report_path,
            input_context=input_context,
            source_role="reviewer",
            source_tool=tool,
            evidence=evidence,
        )
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
    # The normalized ReviewReport is already bound into the durable outbox and
    # remains available in the durable model workspace.  Do not leave the
    # trusted checkout dirty after the delivery has completed: the same managed
    # Reviewer workspace must be reusable for the next dynamically authored
    # card in a Plan loop.
    _remove_delivered_review_report(repo, a)
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
        state_root = evidence.state_dir if evidence is not None else direct_entry_state_root()
        if provenance is not None and evidence is not None:
            try:
                from agent_workflow.operations.awf_plan import (
                    PlanOperationError,
                    handle_card_terminal,
                )
                from agent_workflow.plan_loop import PlanLoopError

                plan_result = handle_card_terminal(
                    args=a,
                    evidence=evidence,
                    input_context=input_context,
                    review_report=review_report,
                    provenance=provenance,
                    terminal_repo=Path(terminal_repo),
                    implementation_sha256="sha256:" + artifact_sha256(report_path, a.report),
                    review_sha256=canonical_payload_sha256(review_report),
                )
            except (PlanOperationError, PlanLoopError) as exc:
                record(evidence, "plan_terminal_failed", reason=str(exc))
                die(f"Plan terminal decision failed: {exc}")
            if (
                plan_result is not None
                and plan_result.get("pending_state") == "WAITING_FOR_HUMAN_APPROVAL"
            ):
                record(
                    evidence,
                    "plan_terminal_waiting_for_human_approval",
                    branch=a.branch,
                    commit=a.commit,
                    pull_request=provenance["pull_request"],
                )
                complete_inbox(
                    evidence,
                    str(input_context["delivery_id"]),
                    str(input_context["payload_sha256"]),
                )
                return 0
            if plan_result is not None:
                try:
                    RunLedger(state_root, run_id).mark_terminal(
                        terminal_state=str(plan_result["terminal_state"]),
                        terminal=dict(plan_result["terminal"]),
                    )
                except ControlPlaneDenied as exc:
                    record(evidence, "terminal_ledger_failed", reason=str(exc))
                    die(f"terminal decision could not be persisted: {exc}")
                record(
                    evidence,
                    "plan_terminal_verified",
                    terminal_state=plan_result["terminal_state"],
                    branch=a.branch,
                    commit=a.commit,
                    pull_request=provenance["pull_request"],
                )
                complete_inbox(
                    evidence,
                    str(input_context["delivery_id"]),
                    str(input_context["payload_sha256"]),
                )
                return 0
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
                    "sha256": "sha256:" + artifact_sha256(report_path, a.report),
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
    p.add_argument("--state-root", type=Path, default=None)
    p.add_argument("--state-root-sha256", default="")
    a = p.parse_args(argv)
    if a.event_id < 1:
        p.error("--event-id must be a positive integer")
    inherited_root = os.environ.get("AWF_STATE_ROOT")
    state_root = (
        a.state_root.expanduser().resolve()
        if a.state_root is not None
        else Path(inherited_root).expanduser().resolve()
        if inherited_root
        else direct_entry_state_root()
    )
    if inherited_root and Path(inherited_root).expanduser().resolve() != state_root:
        p.error("state-root mismatch between handler argv and inherited environment")
    binding = state_root_binding(state_root)
    inherited_binding = os.environ.get("AWF_STATE_ROOT_SHA256", "")
    if a.state_root_sha256 and a.state_root_sha256 != binding:
        p.error("handler state-root binding does not match --state-root")
    if inherited_binding and inherited_binding != binding:
        p.error("handler state-root binding does not match inherited environment")
    explicit_root = a.state_root is not None or bool(inherited_root)
    a.evidence = RunEvidence(
        a.event_id,
        a.role,
        state_root=state_root if explicit_root else None,
    )
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
