"""One conservative installed application boundary for Agent and CLI entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from agent_workflow import facade
from agent_workflow.plan_loop import PlanLoopError, PlanRunStore

HUMAN_PLAN_INTENT = "This Plan is approved and committed. Use AWF to complete it."
HUMAN_STOP_INTENT = "Stop this exact PlanRun and its local AWF listeners."
HUMAN_DEINIT_INTENT = "Deinitialize this exact completed PlanRun and its local AWF bindings."


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
    current = str(run.get("status", "unknown"))
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


def continue_after_approval(repo: Path, *, run_id: str, human_intent: str) -> None:
    _require_human_intent(human_intent, expected=HUMAN_PLAN_INTENT, action="approval continuation")
    status(repo, run_id=run_id)
    raise ApplicationError(
        "continue_after_approval is not yet authorized by the existing Plan authority"
    )


def authorize_replacement(repo: Path, *, run_id: str, human_intent: str) -> None:
    _require_human_intent(human_intent, expected=HUMAN_PLAN_INTENT, action="replacement")
    status(repo, run_id=run_id)
    raise ApplicationError(
        "authorize_replacement is not yet authorized by the existing Plan authority"
    )
