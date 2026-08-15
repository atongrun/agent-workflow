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

_MODEL_OBSERVED_PHASES = {
    "model_started",
    "model_completed",
    "postflight_completed",
    "model_imported",
    "commit_created",
    "fork_sha_verified",
    "pr_created",
    "pr_tuple_verified",
    "outbox_prepared",
    "outbox_sent",
}


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


def _feedback(profile: NodeProfile) -> dict[str, object]:
    directory = operations_dir()
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    import awf_feedback

    try:
        counts = awf_feedback.feedback_status(profile.state_root)
    except (OSError, ValueError, awf_feedback.FeedbackStateError):
        return {
            "source": "feedback_outbox_files_read_only",
            "status": "unknown",
            "capture": "unknown",
            "outbox": "unknown",
            "flush": "unknown",
        }
    pending = int(counts.get("pending", 0))
    sent = int(counts.get("sent", 0))
    rejected = int(counts.get("rejected", 0))
    corrupt = int(counts.get("corrupt", 0))
    captured = pending + sent
    flush = (
        "blocked"
        if corrupt
        else "pending"
        if pending
        else "complete"
        if sent
        else "not_recorded"
    )
    return {
        "source": "feedback_outbox_files_read_only",
        "status": "observed",
        "capture": "recorded" if captured else "rejected" if rejected else "not_recorded",
        "outbox": "corrupt" if corrupt else "pending" if pending else "empty",
        "flush": flush,
        "next_legal_action": (
            f"awf feedback flush --state-root {profile.state_root}"
            if pending
            else "inspect corrupt Feedback Outbox records"
            if corrupt
            else "none"
        ),
        "counts": {
            "pending": pending,
            "sent": sent,
            "rejected": rejected,
            "corrupt": corrupt,
        },
    }


def _model_invocation(profile: NodeProfile, ledger: dict[str, object]) -> bool | None:
    packet = ledger.get("context_packet") if isinstance(ledger, dict) else None
    branch = str(packet.get("branch", "")) if isinstance(packet, dict) else ""
    expected_binding = state_root_binding(profile.state_root)
    observed_checkpoint = False
    events = ledger.get("events") if isinstance(ledger, dict) else None
    authorized = [
        item
        for item in events
        if isinstance(item, dict)
        and item.get("status") == "authorized"
        and item.get("role") in {"coder", "reviewer"}
        and isinstance(item.get("delivery_id"), str)
        and item.get("delivery_id")
    ] if isinstance(events, list) else []
    for event in authorized:
        delivery_id = str(event["delivery_id"])
        digest = hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()
        path = profile.state_root / "checkpoint" / str(event["role"]) / f"{digest}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        binding = record.get("state_root_sha256")
        if binding is not None and binding != expected_binding:
            continue
        if branch and record.get("branch") != branch:
            continue
        observed_checkpoint = True
        if record.get("phase") in _MODEL_OBSERVED_PHASES:
            return True
    return False if observed_checkpoint else None


def _event_observation(ledger: dict[str, object]) -> dict[str, object]:
    events = ledger.get("events") if isinstance(ledger, dict) else None
    safe_events = (
        [item for item in events if isinstance(item, dict)] if isinstance(events, list) else []
    )
    latest = safe_events[-1] if safe_events else {}
    return {
        "source": "run_ledger_payload_blind",
        "count": len(safe_events),
        "payload_hash_observed": isinstance(latest.get("payload_sha256"), str)
        and bool(latest.get("payload_sha256")),
        "latest": {
            key: latest[key]
            for key in ("event_id", "event_type", "role", "stage", "attempt", "status", "reason")
            if key in latest
        },
    }


def _causal_status(
    run_id: str,
    lifecycle: dict[str, object],
    ledger_fact: dict[str, object],
    ledger: dict[str, object],
    model_invoked: bool | None,
) -> dict[str, object]:
    stage = str(ledger_fact.get("stage", "not_recorded"))
    stage_attempts = ledger.get("stage_attempts") if isinstance(ledger, dict) else None
    attempt = (
        int(stage_attempts.get(stage, 0))
        if isinstance(stage_attempts, dict)
        else int(ledger_fact.get("attempts", 0) or 0)
    )
    events = _event_observation(ledger)
    authorized = (
        [
            item
            for item in ledger.get("events", [])
            if isinstance(item, dict) and item.get("status") == "authorized"
        ]
        if isinstance(ledger, dict)
        else []
    )
    if model_invoked is None and ledger_fact.get("status") == "recorded" and not authorized:
        model_invoked = False
    model_status = (
        "observed"
        if model_invoked is True
        else "not_observed"
        if model_invoked is False
        else "unknown"
    )

    terminal_state = str(ledger.get("terminal_state", "")) if isinstance(ledger, dict) else ""
    decisions = ledger.get("decisions") if isinstance(ledger, dict) else None
    safe_decisions = (
        [item for item in decisions if isinstance(item, dict)]
        if isinstance(decisions, list)
        else []
    )
    latest_decision = safe_decisions[-1] if safe_decisions else {}
    next_action = str(ledger_fact.get("next_action", "inspect recorded facts"))
    status_value = "active"
    owner = str(events["latest"].get("role") or "run_owner")
    cause = "no_blocker_observed"

    if terminal_state:
        status_value = "terminal"
        owner = "run_owner"
        cause = f"business_{terminal_state}"
        next_action = "stop"
    elif latest_decision.get("status") == "rejected":
        status_value = "blocked"
        cause = str(latest_decision.get("reason", "pre_model_authorization_rejected"))
        owner = "workflow_control_plane"
        next_action = f"correct {cause} before creating a fresh authorized delivery"
    elif lifecycle.get("dispatch_capable") is False:
        status_value = "blocked"
        blocked_fact = next(
            (
                name
                for name in ("configured", "installed", "running", "connected", "dispatch_capable")
                if lifecycle.get(name) is False
            ),
            "dispatch_capable",
        )
        owner = "node_lifecycle"
        cause = f"lifecycle_{blocked_fact}_false"
        action = lifecycle.get("next_legal_action")
        if isinstance(action, dict):
            next_action = str(action.get("command") or next_action)
    elif ledger_fact.get("status") != "recorded":
        status_value = "unknown"
        owner = "run_owner"
        cause = "run_ledger_unavailable"

    first_blocker = {
        "status": "observed" if status_value == "blocked" else "not_observed",
        "owner": owner,
        "cause": cause,
    }
    return {
        "source": "lifecycle+run_ledger+delivery_checkpoints",
        "status": status_value,
        "run_id": run_id or "not_requested",
        "stage": stage,
        "attempt": attempt,
        "owner": owner,
        "cause": cause,
        "first_blocker": first_blocker,
        "model_invocation": model_status,
        "event_observation": events,
        "next_legal_action": next_action,
        "prohibited_actions": [
            "ack",
            "requeue",
            "recover",
            "redispatch",
            "invoke_model",
        ],
        "chain": [
            {
                "boundary": "lifecycle",
                "status": "ready"
                if lifecycle.get("dispatch_capable") is True
                else "blocked"
                if lifecycle.get("dispatch_capable") is False
                else "unknown",
            },
            {"boundary": "run_ledger", "status": ledger_fact.get("status", "unknown")},
            {
                "boundary": "pre_model_authorization",
                "status": latest_decision.get("status", "not_recorded"),
            },
            {"boundary": "model_invocation", "status": model_status},
            {
                "boundary": "business_terminal",
                "status": terminal_state or "not_recorded",
            },
        ],
    }


def snapshot(profile: NodeProfile, run_id: str = "") -> dict[str, object]:
    from agent_workflow import node

    listener = _listener(profile)
    ledger_fact, ledger = _ledger(profile, run_id)
    delivery_fact, review_file_sha = _delivery_checkpoints(profile, ledger)
    pull_request, ci = _pr_and_ci(profile, ledger)
    lifecycle = node.lifecycle_facts(profile, listener=listener)
    model_invoked = _model_invocation(profile, ledger)
    return {
        "format": STATUS_FORMAT,
        "observed_at": _now(),
        "profile": {"name": profile.name, "role": profile.role, "path": str(profile.path)},
        "state_root": {
            "source": "node_profile",
            "sha256": state_root_binding(profile.state_root),
        },
        "lifecycle": lifecycle,
        "listener": listener,
        "workspace": _workspace(profile),
        "checkpoint": {"ledger": ledger_fact, "delivery": delivery_fact},
        "queue": _queue(profile),
        "artifacts": _artifacts(profile, ledger, review_file_sha),
        "pull_request": pull_request,
        "ci": ci,
        "feedback": _feedback(profile),
        "causal": _causal_status(
            run_id,
            lifecycle,
            ledger_fact,
            ledger,
            model_invoked,
        ),
    }


def print_human(value: dict[str, object], *, explain: bool = False) -> None:
    profile = value["profile"]
    listener = value["listener"]
    workspace = value["workspace"]
    checkpoint = value["checkpoint"]
    queue = value["queue"]
    artifacts = value["artifacts"]
    lifecycle = value.get("lifecycle")
    if isinstance(lifecycle, dict):

        def label(item: object) -> str:
            if item is True:
                return "true"
            if item is False:
                return "false"
            return "unknown"

        print(
            "lifecycle: "
            + " ".join(
                f"{name}={label(lifecycle.get(name))}"
                for name in (
                    "configured",
                    "installed",
                    "running",
                    "connected",
                    "dispatch_capable",
                )
            )
            + f" installation_status={lifecycle['installation']['status']}"
            + f" running_observation={lifecycle['running_observation']['status']}"
            + f" preflight={lifecycle['preflight']['status']}"
        )
        print(f"next_legal_action={lifecycle['next_legal_action']['command']}")
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
    feedback = value.get("feedback")
    if isinstance(feedback, dict):
        counts = feedback.get("counts") if isinstance(feedback.get("counts"), dict) else {}
        print(
            "feedback: "
            f"capture={feedback.get('capture', 'unknown')} "
            f"outbox={feedback.get('outbox', 'unknown')} "
            f"flush={feedback.get('flush', 'unknown')} "
            f"pending={counts.get('pending', 'unknown')}"
        )
    if explain:
        causal = value.get("causal")
        if isinstance(causal, dict):
            print(
                "causal: "
                f"run={causal.get('run_id', 'not_requested')} "
                f"stage={causal.get('stage', 'not_recorded')} "
                f"attempt={causal.get('attempt', 0)} "
                f"status={causal.get('status', 'unknown')}"
            )
            print(
                "first_blocker: "
                f"owner={causal.get('owner', 'unknown')} "
                f"cause={causal.get('cause', 'unknown')} "
                f"model_invocation={causal.get('model_invocation', 'unknown')}"
            )
            print(f"next_legal_action={causal.get('next_legal_action', 'unknown')}")
