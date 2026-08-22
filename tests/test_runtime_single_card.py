from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from agent_workflow.runtime import (
    AtomicRunStore,
    AuthorizationCommand,
    ContractError,
    DecisionOutcome,
    FreshRunSpec,
    HandoffCommand,
    JournalAuthorization,
    LaunchIntent,
    LocalRuntimeApplication,
    LocalStageRequest,
    ModelSelection,
    OutgoingIntent,
    ProcessObservation,
    ProviderResult,
    ResultEnvelope,
    RoleBinding,
    TerminalCommand,
    TerminalOutcome,
    ValidationEffect,
    WorkflowStage,
)
from agent_workflow.runtime.renderers import ARCHITECT_TERMINAL


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def binding(tmp_path: Path, role: str, tool: str, model: ModelSelection) -> RoleBinding:
    workspace = (tmp_path / role).resolve()
    return RoleBinding(
        role,
        tool,
        model,
        f"profile-{role}",
        digest(f"profile-{role}"),
        str(workspace),
    )


def fresh_spec(tmp_path: Path) -> FreshRunSpec:
    state = (tmp_path / "state").resolve()
    return FreshRunSpec(
        run_id="task-phase5-02-test",
        task_id="phase5-02-test",
        task_card="docs/tasks/phase5-02-test.md",
        task_card_sha256=digest("card"),
        repository="owner/repo",
        frozen_base="a" * 40,
        task_branch="codex/phase5-02-test",
        state_root_sha256=digest("awf-state-root-v1\0" + str(state)),
        semantic_contract_sha256=digest("contract"),
        architect=binding(tmp_path, "architect", "pi", ModelSelection("tool-default", "")),
        coder=binding(tmp_path, "coder", "opencode", ModelSelection("explicit", "coder/model")),
        reviewer=binding(
            tmp_path, "reviewer", "opencode", ModelSelection("explicit", "coder/model")
        ),
        implement_attempts=1,
        review_attempts=2,
        rework_budget=1,
        implement_route="task:awf-runtime-v2-implement-v1",
        review_route="task:awf-runtime-v2-review-v1",
        rework_route="task:awf-runtime-v2-rework-v1",
        architect_route="decision:awf-runtime-v2-architect-v1",
        implementation_report=".awf/artifacts/impl.md",
        review_report=".awf/artifacts/review.md",
        decision_report=".awf/artifacts/decision.md",
    )


def authorize_and_complete(
    store: AtomicRunStore,
    spec: FreshRunSpec,
    stage: WorkflowStage,
    label: str,
    attempt: int,
) -> tuple[AuthorizationCommand, ValidationEffect]:
    incoming = store.pending_handoff()
    role = {
        WorkflowStage.REVIEW: "reviewer",
        WorkflowStage.ARCHITECT: "architect",
    }.get(stage, "coder")
    command = AuthorizationCommand(
        spec.sha256,
        f"invoke-{label}",
        digest(f"authorization-{label}"),
        stage,
        role,
        attempt,
        incoming.delivery_id if incoming else "awfv2:" + digest(f"delivery-{label}"),
        incoming.payload_sha256 if incoming else digest(f"payload-{label}"),
    )
    store.authorize(
        command,
        JournalAuthorization(
            spec.sha256,
            command.invocation_id,
            command.authorization_sha256,
            digest(f"invocation-{label}"),
        ),
    )
    journal = store.journal(command.invocation_id)
    launch = LaunchIntent(command.authorization_sha256, digest(f"rendered-{label}"))
    process = ProcessObservation(command.authorization_sha256, digest(f"process-{label}"))
    result = ProviderResult(
        command.authorization_sha256,
        process.process_identity_sha256,
        0,
        digest(f"result-{label}"),
    )
    journal.record_launch_intent(launch)
    journal.record_process_observation(process)
    journal.record_result(result)
    return command, ValidationEffect(
        command.authorization_sha256,
        result.result_sha256,
        digest(f"artifact-{label}"),
        digest(f"effect-{label}"),
    )


def record_handoff(
    store: AtomicRunStore,
    spec: FreshRunSpec,
    source: AuthorizationCommand,
    effect: ValidationEffect,
    *,
    route: str,
    target_role: str,
    label: str,
) -> None:
    envelope = ResultEnvelope.create(
        run_id=spec.run_id,
        task_id=spec.task_id,
        run_spec_sha256=spec.sha256,
        source_role=source.role,
        target_role=target_role,
        route=route,
        source_invocation_id=source.invocation_id,
        source_authorization_sha256=source.authorization_sha256,
        target_invocation_id=f"invoke-{label}",
        causation_delivery_id=source.delivery_id,
        payload={"label": label},
    )
    decision = store.record_handoff(
        HandoffCommand(
            spec.sha256,
            source.invocation_id,
            source.authorization_sha256,
            envelope.delivery_id,
            envelope.payload_sha256.removeprefix("sha256:"),
            route,
            target_role,
        ),
        effect,
        OutgoingIntent.from_envelope(envelope),
    )
    assert decision.outcome is DecisionOutcome.SAFE_CONTINUE


def test_fresh_role_bindings_preserve_tool_default_and_explicit_refs(tmp_path: Path) -> None:
    spec = fresh_spec(tmp_path)
    restored = FreshRunSpec.from_mapping(spec.to_mapping())

    assert restored == spec
    assert restored.architect.model == ""
    assert restored.coder.model == "coder/model"
    assert restored.coder.model_selection == restored.reviewer.model_selection
    assert restored.coder.workspace != restored.reviewer.workspace
    with pytest.raises(ContractError, match="tool-default"):
        ModelSelection("tool-default", "unexpected/model")
    with pytest.raises(ContractError, match="opaque"):
        ModelSelection("explicit", "two tokens")


def test_fresh_store_routes_reviewer_pass_to_one_architect_terminal(tmp_path: Path) -> None:
    spec = fresh_spec(tmp_path)
    store = AtomicRunStore(tmp_path / "state", spec.run_id, "writer-phase5-02")
    assert store.initialize(spec).stage is WorkflowStage.IMPLEMENT

    implement, implement_effect = authorize_and_complete(
        store, spec, WorkflowStage.IMPLEMENT, "implement", 1
    )
    record_handoff(
        store,
        spec,
        implement,
        implement_effect,
        route=spec.review_route,
        target_role="reviewer",
        label="review",
    )
    review, review_effect = authorize_and_complete(store, spec, WorkflowStage.REVIEW, "review", 1)
    record_handoff(
        store,
        spec,
        review,
        review_effect,
        route=spec.architect_route,
        target_role="architect",
        label="architect",
    )
    architect, architect_effect = authorize_and_complete(
        store, spec, WorkflowStage.ARCHITECT, "architect", 1
    )
    terminal_envelope = ResultEnvelope.create(
        run_id=spec.run_id,
        task_id=spec.task_id,
        run_spec_sha256=spec.sha256,
        source_role="architect",
        target_role="architect",
        route="result:completed",
        source_invocation_id=architect.invocation_id,
        source_authorization_sha256=architect.authorization_sha256,
        target_invocation_id="terminal-phase5-02",
        causation_delivery_id=architect.delivery_id,
        payload={"decision": "approve", "merged": True},
    )
    outcome = store.record_terminal(
        TerminalCommand(
            spec.sha256,
            architect.invocation_id,
            architect.authorization_sha256,
            terminal_envelope.delivery_id,
            terminal_envelope.payload_sha256.removeprefix("sha256:"),
            TerminalOutcome.COMPLETED,
            digest("merge-observation"),
        ),
        architect_effect,
        OutgoingIntent.from_envelope(terminal_envelope),
    )

    assert outcome.outcome is DecisionOutcome.SAFE_CONTINUE
    assert store.initialize(spec).terminal is TerminalOutcome.COMPLETED


def test_local_application_compiles_exact_fresh_architect_invocation(tmp_path: Path) -> None:
    spec = fresh_spec(tmp_path)
    workspace = tmp_path / "architect-event"
    workspace.mkdir()
    request = LocalStageRequest(
        invocation_id="invoke-architect",
        stage=WorkflowStage.ARCHITECT,
        attempt=1,
        delivery_id="awfv2:" + digest("architect-delivery"),
        payload_sha256=digest("architect-payload"),
        outgoing_target_invocation_id="terminal-architect",
        provider_executable=str(Path(sys.executable).resolve()),
        provider_environment=(("LANG", "C.UTF-8"),),
        input_text='{"review_verdict":"PASS"}',
        provider_args=(ARCHITECT_TERMINAL,),
        source_repo=str(tmp_path.resolve()),
        trusted_repo=str(tmp_path.resolve()),
        expected_commit="a" * 40,
        workspace_state_dir=str((tmp_path / "workspaces").resolve()),
        python_executable=str(Path(sys.executable).resolve()),
    )

    invocation = LocalRuntimeApplication(tmp_path / "state", "writer")._invocation(
        spec, request, str(workspace.resolve())
    )

    assert invocation.role == "architect"
    assert invocation.provider == "pi"
    assert invocation.model == ""
    assert invocation.provider_args == (ARCHITECT_TERMINAL,)
    assert invocation.report_path == str(workspace / spec.decision_report)
