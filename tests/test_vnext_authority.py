import json

import pytest

from agent_workflow.vnext import RunAuthority
from agent_workflow.vnext.authority import AcceptanceKind, AuthorityError
from agent_workflow.vnext.contracts import (
    ContractError,
    RoleBinding,
    RunStatus,
    Stage,
    TaskProposal,
    WaitingReason,
    parse_typed_result,
)


def authority(stage: Stage = Stage.AUTHOR) -> RunAuthority:
    roles = (
        RoleBinding("architect", "pi", "local"),
        RoleBinding("coder", "opencode", "windows-coder"),
        RoleBinding("reviewer", "codex", "local"),
    )
    return RunAuthority(
        run_id="run-17",
        writer_id="coordinator-1",
        plan_sha256="a" * 64,
        repository="atongrun/example",
        base_ref="main",
        base_sha="b" * 40,
        roles=roles,
        stage=stage,
    )


def raw(value: object) -> bytes:
    return json.dumps(value).encode()


def proposal() -> dict[str, object]:
    return {
        "brief": "Add one bounded behavior",
        "change_paths": ["src/example.py"],
        "acceptance_criteria": ["The focused test passes"],
        "verification_argv": [["python", "-m", "pytest", "-q", "tests/test_example.py"]],
    }


def accept(current: RunAuthority, result: object):
    started = current.begin(writer_id="coordinator-1", input_value={"stage": current.stage})
    pending = started.pending_operation
    assert pending is not None
    return started.accept(
        writer_id="coordinator-1",
        operation_id=pending.operation_id,
        input_sha256=pending.input_sha256,
        result=result,
    )


def test_author_next_task_enters_implement_and_increments_sequence() -> None:
    result = parse_typed_result("author", raw({"status": "next_task", "task": proposal()}))
    accepted = accept(authority(), result)
    assert accepted.kind == AcceptanceKind.ACCEPTED
    assert accepted.authority.stage == Stage.IMPLEMENT
    assert accepted.authority.task_ordinal == 1
    assert accepted.authority.current_task is not None
    assert accepted.authority.current_task.task_ref == "awf/run-17-task-01"
    assert accepted.authority.sequence == 1


def test_five_stage_result_path_and_same_task_rework() -> None:
    current = authority(Stage.IMPLEMENT)
    implementation = parse_typed_result(
        "implement", raw({"status": "completed", "summary": "done", "diagnostics": ""})
    )
    current = accept(current, implementation).authority
    assert current.stage == Stage.REVIEW
    review = parse_typed_result(
        "review",
        raw(
            {
                "verdict": "request_changes",
                "findings": [{"required_correction": "Close the race", "evidence": "test"}],
                "blocked_reason": "",
                "rationale": "One required correction",
            }
        ),
    )
    current = accept(current, review).authority
    assert current.stage == Stage.IMPLEMENT
    assert current.rework_count == 1
    current = accept(current, implementation).authority
    approved = parse_typed_result(
        "review",
        raw({"verdict": "approve", "findings": [], "blocked_reason": "", "rationale": "ok"}),
    )
    current = accept(current, approved).authority
    assert current.stage == Stage.DECIDE
    decision = parse_typed_result("decide", raw({"verdict": "approve", "rationale": "ship"}))
    assert accept(current, decision).authority.stage == Stage.MERGE


def test_duplicate_is_idempotent_conflict_waits_and_late_is_diagnostic_only() -> None:
    result = parse_typed_result(
        "implement", raw({"status": "completed", "summary": "done", "diagnostics": ""})
    )
    started = authority(Stage.IMPLEMENT).begin(
        writer_id="coordinator-1", input_value={"task": "task-1"}
    )
    pending = started.pending_operation
    assert pending is not None
    accepted = started.accept(
        writer_id="coordinator-1",
        operation_id=pending.operation_id,
        input_sha256=pending.input_sha256,
        result=result,
    ).authority
    duplicate = accepted.accept(
        writer_id="coordinator-1",
        operation_id=pending.operation_id,
        input_sha256=pending.input_sha256,
        result=result,
    )
    assert duplicate.kind == AcceptanceKind.IDEMPOTENT
    conflict_result = parse_typed_result(
        "implement", raw({"status": "blocked", "summary": "no", "diagnostics": "x"})
    )
    conflict = accepted.accept(
        writer_id="coordinator-1",
        operation_id=pending.operation_id,
        input_sha256=pending.input_sha256,
        result=conflict_result,
    )
    assert conflict.kind == AcceptanceKind.CONFLICT
    assert conflict.authority.waiting_reason == WaitingReason.HUMAN
    late = accepted.accept(
        writer_id="coordinator-1",
        operation_id="0" * 64,
        input_sha256="1" * 64,
        result=result,
    )
    assert late.kind == AcceptanceKind.LATE
    assert late.authority == accepted


def test_wrong_writer_and_input_identity_fail_closed() -> None:
    current = authority().begin(writer_id="coordinator-1", input_value={"x": 1})
    with pytest.raises(AuthorityError, match="writer"):
        current.resume(writer_id="other")
    pending = current.pending_operation
    assert pending is not None
    result = parse_typed_result("author", raw({"status": "complete", "summary": "finished"}))
    conflict = current.accept(
        writer_id="coordinator-1",
        operation_id=pending.operation_id,
        input_sha256="f" * 64,
        result=result,
    )
    assert conflict.kind == AcceptanceKind.CONFLICT
    assert conflict.authority.status == RunStatus.WAITING


def test_conflicting_result_after_terminal_acceptance_waits_without_invalid_state() -> None:
    started = authority().begin(writer_id="coordinator-1", input_value={"plan": "exact"})
    pending = started.pending_operation
    assert pending is not None
    complete = parse_typed_result("author", raw({"status": "complete", "summary": "finished"}))
    accepted = started.accept(
        writer_id="coordinator-1",
        operation_id=pending.operation_id,
        input_sha256=pending.input_sha256,
        result=complete,
    ).authority
    conflicting = parse_typed_result("author", raw({"status": "blocked", "reason": "conflict"}))
    result = accepted.accept(
        writer_id="coordinator-1",
        operation_id=pending.operation_id,
        input_sha256=pending.input_sha256,
        result=conflicting,
    )
    assert result.kind == AcceptanceKind.CONFLICT
    assert result.authority.status == RunStatus.WAITING
    assert result.authority.terminal is None


@pytest.mark.parametrize(("stage", "budget"), [(Stage.AUTHOR, 2), (Stage.IMPLEMENT, 3)])
def test_attempt_failure_preserves_identity_and_exhaustion_waits(stage: Stage, budget: int) -> None:
    current = authority(stage)
    for attempt in range(1, budget + 1):
        started = current.begin(writer_id="coordinator-1", input_value={"same": "input"})
        assert started.stage == stage
        assert started.run_id == "run-17"
        assert started.pending_operation is not None
        assert started.pending_operation.attempt == attempt
        current = started.fail_attempt(writer_id="coordinator-1", error="provider failed")
    assert current.status == RunStatus.WAITING
    assert current.waiting_reason == WaitingReason.BUDGET_EXHAUSTED


def test_exact_merge_observation_returns_same_run_to_author_with_fresh_base() -> None:
    authored = parse_typed_result("author", raw({"status": "next_task", "task": proposal()}))
    current = accept(authority(), authored).authority
    implementation = parse_typed_result(
        "implement", raw({"status": "completed", "summary": "done", "diagnostics": ""})
    )
    current = accept(current, implementation).authority
    review = parse_typed_result(
        "review",
        raw({"verdict": "approve", "findings": [], "blocked_reason": "", "rationale": "ok"}),
    )
    current = accept(current, review).authority
    decision = parse_typed_result("decide", raw({"verdict": "approve", "rationale": "ship"}))
    current = accept(current, decision).authority
    current = current.observe_merge(
        writer_id="coordinator-1", task_head_sha="c" * 40, fresh_base_sha="d" * 40
    )
    assert current.run_id == "run-17"
    assert current.stage == Stage.AUTHOR
    assert current.base_sha == "d" * 40
    assert current.current_task is None


@pytest.mark.parametrize(
    "payload",
    [
        b'{"status":"complete","summary":"ok"}\n{"status":"complete","summary":"again"}',
        b'prefix {"status":"complete","summary":"ok"}',
        b'{"status":"complete","status":"blocked","reason":"x"}',
        b'{"status":"complete","summary":"ok","extra":true}',
    ],
)
def test_result_boundary_rejects_markdown_multiple_duplicate_and_extra_fields(
    payload: bytes,
) -> None:
    with pytest.raises(ContractError):
        parse_typed_result("author", payload)


def test_review_request_changes_requires_structured_correction() -> None:
    with pytest.raises(ContractError, match="finding"):
        parse_typed_result(
            "review",
            raw(
                {
                    "verdict": "request_changes",
                    "findings": [],
                    "blocked_reason": "",
                    "rationale": "fix it",
                }
            ),
        )


def test_task_proposal_and_peer_role_bindings_are_strict() -> None:
    task = TaskProposal.from_dict(proposal())
    assert task.change_paths == ("src/example.py",)
    with pytest.raises(ContractError, match="escapes"):
        TaskProposal.from_dict({**proposal(), "change_paths": ["../secret"]})
    with pytest.raises(ContractError, match="escapes"):
        TaskProposal.from_dict({**proposal(), "change_paths": ["..\\secret"]})
    roles = (
        RoleBinding("architect", "pi", "local"),
        RoleBinding("coder", "opencode", "windows-coder"),
        RoleBinding("reviewer", "codex", "local"),
    )
    assert {role.role for role in roles} == {"architect", "coder", "reviewer"}
