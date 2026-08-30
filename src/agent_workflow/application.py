"""One conservative installed application boundary for Agent and CLI entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from agent_workflow import facade
from agent_workflow.plan_loop import PlanLoopError, PlanRunStore

HUMAN_PLAN_INTENT = "This Plan is approved and committed. Use AWF to complete it."
HUMAN_STOP_INTENT = "Stop this exact PlanRun and its local AWF listeners."
HUMAN_DEINIT_INTENT = "Deinitialize this exact completed PlanRun and its local AWF bindings."
HUMAN_APPROVAL_CONTINUE_INTENT = "Continue this exact approved PlanRun after Human approval."
HUMAN_REPLACEMENT_INTENT = "Authorize one fresh replacement for this exact blocked delivery."


class ApplicationError(RuntimeError):
    """Credential-safe refusal at the product application boundary."""


def _machine(repo: Path) -> facade.MachineContract:
    try:
        return facade.load_machine(repo)
    except facade.FacadeError as exc:
        raise ApplicationError("current-machine AWF binding is unavailable") from exc


def _store(repo: Path, run_id: str) -> PlanRunStore:
    machine = _machine(repo)
    if not machine.profiles:
        raise ApplicationError("current-machine AWF binding has no role profiles")
    return PlanRunStore(machine.profiles[0].state_root, run_id)


def _require_human_intent(intent: str, *, expected: str, action: str) -> None:
    if intent != expected:
        raise ApplicationError(f"the exact Human intent for {action} is required")


def _card(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: str(value[key])
        for key in ("task_id", "branch", "status", "taskcard_commit")
        if isinstance(value.get(key), str)
    }


def _completion(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result = _card(value.get("card"))
    for key in ("completed_at", "sha256"):
        if isinstance(value.get(key), str):
            result[key] = value[key]
    return result


def _roles(run: Mapping[str, object]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    architect = run.get("architect")
    if isinstance(architect, Mapping):
        result["architect"] = {
            key: str(architect[key])
            for key in ("tool", "model")
            if isinstance(architect.get(key), str)
        }
    for role in ("coder", "reviewer"):
        value = run.get(role)
        if isinstance(value, Mapping):
            result[role] = {
                key: str(value[key]) for key in ("tool", "model") if isinstance(value.get(key), str)
            }
    return result


def _completion_consistent(store: PlanRunStore, run: Mapping[str, object]) -> bool:
    completion = run.get("last_completion")
    if not isinstance(completion, Mapping) or not isinstance(completion.get("sha256"), str):
        return False
    try:
        completed = store.completions()
    except PlanLoopError:
        return False
    return any(item.get("sha256") == completion["sha256"] for item in completed)


def _authority_consistent(store: PlanRunStore, run: Mapping[str, object]) -> bool:
    status = run.get("status")
    card = run.get("current_card")
    completion = run.get("last_completion")
    stopped = run.get("stop_requested")
    if not isinstance(status, str) or not isinstance(stopped, bool):
        return False
    if status == "milestone_completed":
        return (
            card is None
            and isinstance(completion, Mapping)
            and not stopped
            and _completion_consistent(store, run)
        )
    if status == "card_active":
        return isinstance(card, Mapping) and not stopped
    if status == "waiting_for_human_approval":
        delivery = card.get("terminal_delivery") if isinstance(card, Mapping) else None
        approval = card.get("approval") if isinstance(card, Mapping) else None
        delivery_strings = (
            "run_id",
            "delivery_id",
            "payload_sha256",
            "branch",
            "commit",
            "implementation_path",
            "review_path",
            "implementation_sha256",
            "review_sha256",
        )
        return (
            isinstance(card, Mapping)
            and isinstance(delivery, Mapping)
            and all(
                isinstance(delivery.get(key), str) and delivery[key] for key in delivery_strings
            )
            and isinstance(delivery.get("event_id"), int)
            and isinstance(delivery.get("source_event_id"), int)
            and isinstance(approval, Mapping)
            and (
                (
                    approval.get("status") == "waiting"
                    and approval.get("review_decision") == "REVIEW_REQUIRED"
                    and approval.get("mergeability") == "BLOCKED"
                )
                or (
                    approval.get("status") == "human_merge_required"
                    and approval.get("review_decision") in {"", "APPROVED"}
                    and approval.get("mergeability") == "CLEAN"
                    and approval.get("merge_authority") == "external"
                )
            )
            and not stopped
        )
    if status in {"completed", "stopped", "blocked", "rejected"}:
        return card is None or isinstance(card, Mapping)
    return card is None or isinstance(card, Mapping)


def _actions(status: str, *, stop_requested: bool, authority_consistent: bool) -> tuple[str, ...]:
    if not authority_consistent:
        return ("get_status", "doctor", "stop")
    if stop_requested:
        return ("get_status", "doctor", "stop")
    if status == "milestone_completed":
        return ("get_status", "doctor", "deinit")
    if status == "waiting_for_human_approval":
        return ("get_status", "doctor", "continue_after_approval", "stop")
    if status in {
        "start_sent",
        "card_active",
        "architect_taskcard_running",
        "architect_next_running",
    }:
        return ("get_status", "doctor", "stop")
    if status in {
        "stopped",
        "blocked",
        "architect_failed_no_replay",
        "architect_output_invalid_no_replay",
        "architect_ambiguous",
        "start_ambiguous",
        "dispatch_ambiguous",
    }:
        return ("get_status", "doctor", "stop")
    # A future/unknown authority state is never eligible for continuation, replacement, or dispatch.
    return ("get_status", "doctor", "stop")


def _replacement_state(status: str) -> str:
    """Project no-replay ambiguity without making it replacement-eligible."""
    if status in {
        "architect_ambiguous",
        "architect_failed_no_replay",
        "architect_output_invalid_no_replay",
        "dispatch_ambiguous",
        "merge_ambiguous",
        "start_ambiguous",
    }:
        return "BLOCKED_AMBIGUOUS"
    return ""


def status(repo: Path, *, run_id: str) -> dict[str, object]:
    """Return the credential-free, read-only PlanRun product projection."""
    root = Path(repo).resolve()
    try:
        store = _store(root, run_id)
        run = store.load()
    except (PlanLoopError, OSError) as exc:
        raise ApplicationError("PlanRun is unavailable or its exact identity is invalid") from exc
    if Path(str(run.get("repo", ""))).resolve() != root:
        raise ApplicationError("PlanRun does not belong to this repository")
    raw_current = str(run.get("status", "unknown"))
    current = _replacement_state(raw_current) or raw_current
    reason = str(run.get("stop_reason", ""))
    consistent = _authority_consistent(store, run)
    actions = _actions(
        current,
        stop_requested=run.get("stop_requested") is True,
        authority_consistent=consistent,
    )
    return {
        "current_state": current,
        "current_card": _card(run.get("current_card")),
        "last_completion": _completion(run.get("last_completion")),
        "roles": _roles(run),
        "blocker": {
            "code": "authority_conflict" if not consistent else current if reason else "none",
            "message": "PlanRun facts conflict; inspect or stop only" if not consistent else reason,
        },
        "next_safe_action": actions[0],
        "allowed_actions": list(actions),
    }


def start_plan(
    repo: Path,
    *,
    plan: str,
    mode: str,
    human_intent: str,
) -> dict[str, object]:
    """Start through the existing Plan operation after exact local binding selection."""
    _require_human_intent(human_intent, expected=HUMAN_PLAN_INTENT, action="Plan start")
    if mode not in {"one-card", "milestone"}:
        raise ApplicationError("Plan mode must be one-card or milestone")
    root = Path(repo).resolve()
    candidate = (root / plan).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ApplicationError("Plan path must be repository-relative") from exc
    machine = _machine(root)
    selections = {profile.role: profile for profile in machine.profiles}
    if set(selections) != {"architect", "coder", "reviewer"}:
        raise ApplicationError(
            "start_plan requires exact local Architect, Coder, and Reviewer bindings"
        )
    from agent_workflow.operations import awf_plan

    try:
        return awf_plan.start_plan(
            repo=root,
            plan=candidate,
            mode=mode,
            coder_tool=str(selections["coder"].values["tool"]),
            coder_model=str(selections["coder"].values.get("model", "")),
            reviewer_tool=str(selections["reviewer"].values["tool"]),
            reviewer_model=str(selections["reviewer"].values.get("model", "")),
        )
    except (awf_plan.PlanOperationError, PlanLoopError, facade.FacadeError) as exc:
        raise ApplicationError(
            "Plan start was denied by the existing exact authority gates"
        ) from exc


def doctor(repo: Path, *, role: str = "") -> int:
    try:
        return facade.doctor(Path(repo), role=role)
    except facade.FacadeError as exc:
        raise ApplicationError(
            "doctor could not observe the exact current-machine binding"
        ) from exc


def stop(repo: Path, *, run_id: str, human_intent: str) -> int:
    _require_human_intent(human_intent, expected=HUMAN_STOP_INTENT, action="stop")
    if "stop" not in status(repo, run_id=run_id)["allowed_actions"]:
        raise ApplicationError("stop is not a current allowed action")
    try:
        return facade.stop(Path(repo), run_id=run_id)
    except facade.FacadeError as exc:
        raise ApplicationError("exact local stop was denied") from exc


def deinit(repo: Path, *, run_id: str, human_intent: str) -> int:
    _require_human_intent(human_intent, expected=HUMAN_DEINIT_INTENT, action="deinit")
    if "deinit" not in status(repo, run_id=run_id)["allowed_actions"]:
        raise ApplicationError("deinit is not a current allowed action")
    try:
        return facade.deinit(Path(repo), run_id=run_id)
    except facade.FacadeError as exc:
        raise ApplicationError("exact local deinit was denied") from exc


def continue_after_approval(repo: Path, *, run_id: str, human_intent: str) -> dict[str, object]:
    _require_human_intent(
        human_intent, expected=HUMAN_APPROVAL_CONTINUE_INTENT, action="approval continuation"
    )
    view = status(repo, run_id=run_id)
    if "continue_after_approval" not in view["allowed_actions"]:
        raise ApplicationError("approval continuation is not a current allowed action")
    from agent_workflow.operations import awf_plan
    from agent_workflow.operations.awf_control_plane import ControlPlaneDenied

    try:
        store = _store(Path(repo), run_id)
        profiles = {profile.role: profile for profile in _machine(Path(repo)).profiles}
        architect = profiles.get("architect")
        if architect is None:
            raise ApplicationError(
                "approval continuation requires the exact local Architect profile"
            )
        return awf_plan.continue_after_approval(
            repo=Path(repo).resolve(),
            state_root=store.state_root,
            run_id=run_id,
            architect_profile=architect,
        )
    except (awf_plan.PlanOperationError, PlanLoopError, ControlPlaneDenied) as exc:
        raise ApplicationError("approval continuation was denied by exact current facts") from exc


def authorize_replacement(
    repo: Path,
    *,
    run_id: str,
    human_intent: str,
    old_event_id: object,
    old_delivery_id: str,
    old_role: str,
) -> dict[str, object]:
    _require_human_intent(human_intent, expected=HUMAN_REPLACEMENT_INTENT, action="replacement")
    if (
        not isinstance(old_event_id, int)
        or old_event_id < 1
        or old_role not in {"coder", "reviewer"}
    ):
        raise ApplicationError("replacement old delivery identity is invalid")
    if not old_delivery_id:
        raise ApplicationError("replacement old delivery identity is invalid")
    store = _store(Path(repo), run_id)
    raw = store.load()
    if str(raw.get("status", "")) not in {
        "card_active",
        "architect_ambiguous",
        "architect_failed_no_replay",
        "architect_output_invalid_no_replay",
    }:
        raise ApplicationError("replacement requires an exact no-replay provider ambiguity")
    from agent_workflow.operations import awf_role

    try:
        lineage = awf_role.replacement_evidence(
            store.state_root,
            old_event_id=old_event_id,
            old_role=old_role,
            old_delivery_id=old_delivery_id,
        )
    except SystemExit as exc:
        raise ApplicationError(
            "replacement was denied by exact durable old-delivery facts"
        ) from exc
    card = raw.get("current_card")
    if (
        not isinstance(card, Mapping)
        or lineage.get("old_branch") != card.get("branch")
        or lineage.get("old_base_sha") != card.get("frozen_base")
        or lineage.get("old_role") != old_role
        or lineage.get("old_event_id") != str(old_event_id)
    ):
        raise ApplicationError("replacement old delivery does not match the current PlanRun card")
    current = dict(card)
    existing = current.get("replacement_authorization")
    if existing is not None and existing != lineage:
        raise ApplicationError("a different old delivery is already authorized for replacement")
    delivery = current.get("replacement_delivery")
    if existing == lineage and isinstance(delivery, Mapping):
        return {"replacement_authorization": lineage, "replacement_delivery": dict(delivery)}
    if existing == lineage:
        raise ApplicationError("replacement authorization has an unresolved dispatch outcome")
    store.update(current_card={**current, "replacement_authorization": lineage})
    from agent_workflow.operations import awf_plan

    try:
        profiles = {profile.role: profile for profile in _machine(Path(repo)).profiles}
        architect = profiles.get("architect")
        if architect is None:
            raise ApplicationError(
                "replacement dispatch requires the exact local Architect profile"
            )
        return awf_plan.dispatch_authorized_replacement(
            repo=Path(repo).resolve(),
            state_root=store.state_root,
            run_id=run_id,
            architect_profile=architect,
        )
    except (awf_plan.PlanOperationError, PlanLoopError, facade.FacadeError) as exc:
        raise ApplicationError("replacement dispatch was denied by exact current facts") from exc
