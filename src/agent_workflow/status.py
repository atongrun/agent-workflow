"""Read-only factual status aggregation for one Agent Workflow node."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from agent_workflow.resources import operations_dir
from agent_workflow.state_root import state_root_binding

if TYPE_CHECKING:
    from agent_workflow.node import NodeProfile

STATUS_FORMAT = "awf.node-status.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _operations():
    directory = operations_dir()
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    import awf_config
    import awf_control_plane
    import awf_executor
    import awf_preflight

    return awf_config, awf_control_plane, awf_executor, awf_preflight


def _command(argv: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    _, _, executor, _ = _operations()
    try:
        completed = executor.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            allow_shell_wrapper=True,
        )
    except executor.ExecutionFailure:
        return 1, ""
    return completed.returncode, completed.stdout.strip()


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _listener(profile: NodeProfile) -> dict[str, object]:
    from agent_workflow import node

    return {
        "source": "node_process_record+listener_lease+pid_probe",
        **node._listener_snapshot(profile),
    }


def _workspace(profile: NodeProfile) -> dict[str, object]:
    facts: dict[str, object] = {
        "source": "git_read_only",
        "status": "unknown",
        "repo": str(profile.repo),
        "scope": "source" if profile.role == "architect" else "dedicated_role",
    }
    commands = {
        "top": [
            "git",
            "--no-optional-locks",
            "-C",
            str(profile.repo),
            "rev-parse",
            "--show-toplevel",
        ],
        "head_sha": [
            "git",
            "--no-optional-locks",
            "-C",
            str(profile.repo),
            "rev-parse",
            "HEAD",
        ],
        "branch": [
            "git",
            "--no-optional-locks",
            "-C",
            str(profile.repo),
            "branch",
            "--show-current",
        ],
        "porcelain": [
            "git",
            "--no-optional-locks",
            "-C",
            str(profile.repo),
            "status",
            "--porcelain",
        ],
    }
    observed: dict[str, str] = {}
    for key, argv in commands.items():
        code, output = _command(argv)
        if code != 0:
            facts["reason"] = "git_unavailable"
            return facts
        observed[key] = output
    root_matches = Path(observed["top"]).resolve() == profile.repo
    dirty = bool(observed["porcelain"])
    ready = root_matches and (profile.role == "architect" or not dirty)
    facts.update(
        {
            "status": "ready" if ready else "not_ready",
            "root_matches": root_matches,
            "head_sha": observed["head_sha"],
            "branch": observed["branch"] or "detached",
            "dirty": dirty,
        }
    )
    return facts


def _ledger(profile: NodeProfile, run_id: str) -> tuple[dict[str, object], dict[str, object]]:
    if not run_id:
        return ({"source": "run_ledger", "status": "not_requested"}, {})
    _, control_plane, _, _ = _operations()
    try:
        ledger, packet = control_plane.RunLedger(profile.state_root, run_id).recover()
    except control_plane.ControlPlaneDenied:
        return ({"source": "run_ledger", "status": "unavailable", "run_id": run_id}, {})
    return (
        {
            "source": "run_ledger",
            "status": "recorded",
            "run_id": run_id,
            "terminal_state": ledger.get("terminal_state") or "running",
            "stage": packet.get("stage", ledger.get("stage", "")),
            "phase": packet.get("phase") or packet.get("transition") or "not_recorded",
            "attempts": ledger.get("attempts", 0),
            "next_action": packet.get("next_action", "stop"),
        },
        ledger,
    )


def _delivery_checkpoints(
    profile: NodeProfile, ledger: dict[str, object]
) -> tuple[dict[str, object], str]:
    directory = profile.state_root / "checkpoint" / profile.role
    branch = ""
    terminal = ledger.get("terminal") if isinstance(ledger, dict) else None
    terminal_delivery = ""
    if isinstance(terminal, dict):
        branch = str(terminal.get("branch", ""))
        terminal_delivery = str(terminal.get("delivery_id", ""))
    packet = ledger.get("context_packet") if isinstance(ledger, dict) else None
    if not branch and isinstance(packet, dict):
        branch = str(packet.get("branch", ""))
    records: list[dict[str, object]] = []
    unreadable = 0
    expected_binding = state_root_binding(profile.state_root)
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                unreadable += 1
                continue
            binding = value.get("state_root_sha256") if isinstance(value, dict) else None
            if binding is not None and binding != expected_binding:
                unreadable += 1
                continue
            if isinstance(value, dict) and (not branch or value.get("branch") == branch):
                records.append(value)
    latest = records[-1] if records else {}
    review_file_sha = ""
    reviewer_dir = profile.state_root / "checkpoint" / "reviewer"
    for path in sorted(reviewer_dir.glob("*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(record, dict)
            or (
                record.get("state_root_sha256") is not None
                and record.get("state_root_sha256") != expected_binding
            )
            or (branch and record.get("branch") != branch)
        ):
            continue
        facts = record.get("facts")
        if (
            terminal_delivery
            and isinstance(facts, dict)
            and facts.get("outbox_delivery_id") != terminal_delivery
        ):
            continue
        raw = facts.get("review_report_sha256") if isinstance(facts, dict) else None
        if isinstance(raw, str) and len(raw) == 64:
            review_file_sha = "sha256:" + raw
            break
    return (
        {
            "source": "delivery_checkpoint_files",
            "status": "partial" if unreadable else "recorded" if records else "not_recorded",
            "count": len(records),
            "unreadable": unreadable,
            "latest_phase": latest.get("phase", "not_recorded"),
        },
        review_file_sha,
    )


def _queue(profile: NodeProfile) -> dict[str, object]:
    config_module, _, _, preflight = _operations()
    try:
        config = config_module.load_config(profile.config_path)
        pending = preflight.pending_count(config, profile.role)
    except (config_module.ConfigError, preflight.PreflightError, OSError, ValueError):
        return {"source": "agent_bus_pending_read_only", "status": "unknown"}
    return {
        "source": "agent_bus_pending_read_only",
        "status": "observed",
        "pending": pending,
    }


def _artifact_file(profile: NodeProfile, path_value: object) -> tuple[str, str]:
    if not isinstance(path_value, str) or not path_value:
        return "not_recorded", ""
    path = (profile.repo / path_value).resolve()
    if path == profile.repo or profile.repo not in path.parents or not path.is_file():
        return "unavailable", ""
    try:
        return "observed", _sha256(path)
    except OSError:
        return "unavailable", ""


def _artifacts(
    profile: NodeProfile, ledger: dict[str, object], checkpoint_review_sha: str
) -> dict[str, object]:
    terminal = ledger.get("terminal") if isinstance(ledger, dict) else None
    values = terminal.get("artifacts") if isinstance(terminal, dict) else None
    if not isinstance(values, dict):
        return {"source": "terminal_ledger+live_files", "status": "not_recorded"}
    implementation = values.get("implementation")
    review = values.get("review")
    implementation = implementation if isinstance(implementation, dict) else {}
    review = review if isinstance(review, dict) else {}
    impl_status, impl_live_sha = _artifact_file(profile, implementation.get("path"))
    review_status, review_live_sha = _artifact_file(profile, review.get("path"))
    canonical_sha = review.get("canonical_report_sha256") or review.get("sha256") or ""
    recorded_file_sha = review.get("file_sha256") or checkpoint_review_sha
    return {
        "source": "terminal_ledger+delivery_checkpoint+live_files",
        "status": "recorded",
        "implementation": {
            "path": implementation.get("path", ""),
            "recorded_file_sha256": implementation.get("file_sha256")
            or implementation.get("sha256", ""),
            "live_file_status": impl_status,
            "live_file_sha256": impl_live_sha,
        },
        "review": {
            "path": review.get("path", ""),
            "file_sha256": recorded_file_sha or review_live_sha,
            "file_sha256_source": "delivery_checkpoint"
            if checkpoint_review_sha
            else "terminal_ledger"
            if review.get("file_sha256")
            else "live_file"
            if review_live_sha
            else "not_recorded",
            "live_file_status": review_status,
            "live_file_sha256": review_live_sha,
            "canonical_report_sha256": canonical_sha,
            "canonical_report_sha256_source": "terminal_ledger",
        },
    }


def _pr_and_ci(profile: NodeProfile, ledger: dict[str, object]) -> tuple[dict, dict]:
    terminal = ledger.get("terminal") if isinstance(ledger, dict) else None
    recorded_pr = terminal.get("pull_request") if isinstance(terminal, dict) else None
    recorded_ci = terminal.get("ci") if isinstance(terminal, dict) else None
    pull_request: dict[str, object] = {
        "source": "terminal_ledger+gh_read_only",
        "recorded": recorded_pr if isinstance(recorded_pr, dict) else "not_recorded",
        "live": "not_requested",
    }
    ci: dict[str, object] = {
        "source": "terminal_ledger+gh_read_only",
        "recorded": recorded_ci if isinstance(recorded_ci, dict) else "not_recorded",
        "live": "not_requested",
    }
    number = recorded_pr.get("number") if isinstance(recorded_pr, dict) else 0
    upstream = profile.values.get("upstream_repo")
    if not isinstance(number, int) or number < 1 or not upstream:
        return pull_request, ci
    gh = str(profile.values.get("gh_bin", "gh"))
    code, output = _command(
        [
            gh,
            "pr",
            "view",
            str(number),
            "--repo",
            str(upstream),
            "--json",
            "state,headRefOid,baseRefOid,statusCheckRollup",
        ]
    )
    if code != 0:
        pull_request["live"] = "unknown"
        ci["live"] = "unknown"
        return pull_request, ci
    try:
        live = json.loads(output)
    except json.JSONDecodeError:
        pull_request["live"] = "unknown"
        ci["live"] = "unknown"
        return pull_request, ci
    pull_request["live"] = {
        "state": live.get("state", "UNKNOWN"),
        "head_sha": live.get("headRefOid", ""),
        "base_sha": live.get("baseRefOid", ""),
    }
    checks = live.get("statusCheckRollup")
    conclusions = (
        [
            str(item.get("conclusion") or item.get("state") or "UNKNOWN")
            for item in checks
            if isinstance(item, dict)
        ]
        if isinstance(checks, list)
        else []
    )
    ci["live"] = {
        "checks": conclusions,
        "all_green": bool(conclusions)
        and all(value in {"SUCCESS", "NEUTRAL", "SKIPPED"} for value in conclusions),
    }
    return pull_request, ci


def snapshot(profile: NodeProfile, run_id: str = "") -> dict[str, object]:
    ledger_fact, ledger = _ledger(profile, run_id)
    delivery_fact, review_file_sha = _delivery_checkpoints(profile, ledger)
    pull_request, ci = _pr_and_ci(profile, ledger)
    return {
        "format": STATUS_FORMAT,
        "observed_at": _now(),
        "profile": {"name": profile.name, "role": profile.role, "path": str(profile.path)},
        "state_root": {
            "source": "node_profile",
            "sha256": state_root_binding(profile.state_root),
        },
        "listener": _listener(profile),
        "workspace": _workspace(profile),
        "checkpoint": {"ledger": ledger_fact, "delivery": delivery_fact},
        "queue": _queue(profile),
        "artifacts": _artifacts(profile, ledger, review_file_sha),
        "pull_request": pull_request,
        "ci": ci,
    }


def print_human(value: dict[str, object]) -> None:
    profile = value["profile"]
    listener = value["listener"]
    workspace = value["workspace"]
    checkpoint = value["checkpoint"]
    queue = value["queue"]
    artifacts = value["artifacts"]
    print(
        f"profile={profile['name']} role={profile['role']} listener={listener['status']} "
        f"workspace={workspace['status']} queue={queue['status']}"
    )
    print(
        f"workspace: scope={workspace['scope']} branch={workspace.get('branch', 'unknown')} "
        f"head={workspace.get('head_sha', 'unknown')} dirty={workspace.get('dirty', 'unknown')}"
    )
    ledger = checkpoint["ledger"]
    delivery = checkpoint["delivery"]
    print(
        f"checkpoint: ledger={ledger['status']} phase={ledger.get('phase', 'not_recorded')} "
        f"delivery={delivery['status']} latest={delivery.get('latest_phase', 'not_recorded')}"
    )
    print(f"queue: pending={queue.get('pending', 'unknown')} source={queue['source']}")
    review = artifacts.get("review") if isinstance(artifacts, dict) else None
    if isinstance(review, dict):
        print(
            f"review_artifact: file_sha256={review.get('file_sha256') or 'not_recorded'} "
            "canonical_report_sha256="
            f"{review.get('canonical_report_sha256') or 'not_recorded'}"
        )
    else:
        print("review_artifact: file_sha256=not_recorded canonical_report_sha256=not_recorded")
    print(
        f"pull_request: recorded={value['pull_request']['recorded']} "
        f"live={value['pull_request']['live']}"
    )
    print(f"ci: recorded={value['ci']['recorded']} live={value['ci']['live']}")
