from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_workflow.runtime import (
    AtomicRunStore,
    AuthorizationCommand,
    CommandEnvelope,
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
from agent_workflow.runtime.single_card import (
    COMMAND_TYPE,
    REQUIRED_BUS_CAPABILITY,
    AgentBusClient,
    FreshStageCoordinator,
    ReadinessFact,
    active_run_path,
    compile_fresh_run_spec,
    read_active_run,
    write_active_run,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def git(repo: Path | None, *args: str) -> str:
    argv = ["git"]
    if repo is not None:
        argv += ["-C", str(repo)]
    result = subprocess.run(argv + list(args), capture_output=True, text=True, check=True)
    return result.stdout.strip()


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


def test_compile_fresh_spec_uses_only_committed_card_and_known_bindings(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(None, "init", "-q", "-b", "main", str(repo))
    git(repo, "config", "user.name", "Fresh Test")
    git(repo, "config", "user.email", "fresh@example.invalid")
    card = repo / "docs" / "tasks" / "CARD-001.md"
    card.parent.mkdir(parents=True)
    card.write_text(
        "# Card\n\n## Task ID\n\nCARD-001\n\n- **Task branch**: `codex/CARD-001`\n",
        encoding="utf-8",
    )
    plan = repo / "docs" / "plans" / "runtime-v2-development-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Frozen semantic contract\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "freeze card")
    seed = fresh_spec(tmp_path)
    bindings = {
        "architect": seed.architect,
        "coder": seed.coder,
        "reviewer": seed.reviewer,
    }

    compiled = compile_fresh_run_spec(
        repo=repo,
        card=card,
        repository="owner/repo",
        state_root=tmp_path / "state",
        bindings=bindings,
    )

    assert compiled.format == "awf.runtime-v2.run-spec.v2"
    assert compiled.task_id == "CARD-001"
    assert compiled.frozen_base == git(repo, "rev-parse", "HEAD")
    assert compiled.architect == seed.architect
    card.write_text(card.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    with pytest.raises(Exception, match="working bytes differ"):
        compile_fresh_run_spec(
            repo=repo,
            card=card,
            repository="owner/repo",
            state_root=tmp_path / "other-state",
            bindings=bindings,
        )


def test_fresh_active_pointer_revalidates_store_and_never_reads_legacy(tmp_path: Path) -> None:
    spec = fresh_spec(tmp_path)
    state = tmp_path / "state"
    store = AtomicRunStore(state, spec.run_id, "writer-phase5-02")
    store.initialize(spec)
    repo = tmp_path / "project"
    (repo / ".awf").mkdir(parents=True)
    (repo / ".awf" / "legacy-run-ledger.json").write_text("not-json", encoding="utf-8")
    authority = state / "runtime-v2" / "runs" / spec.run_id / "authority.json"
    write_active_run(repo, spec, authority)

    assert read_active_run(repo)["run_id"] == spec.run_id  # type: ignore[index]
    pointer = json.loads(active_run_path(repo).read_text(encoding="utf-8"))
    pointer["run_spec_sha256"] = "0" * 64
    active_run_path(repo).write_text(json.dumps(pointer), encoding="utf-8")
    assert read_active_run(repo) is None


def test_readiness_requires_structured_argv_capability(tmp_path: Path) -> None:
    spec = fresh_spec(tmp_path)
    fact = ReadinessFact(
        nonce="a" * 32,
        expires_at=2_000_000_000,
        binding=spec.coder,
        source_commit=spec.frozen_base,
        tool_executable="/usr/bin/true",
        tool_version_sha256=digest("tool"),
        bus_executable="/usr/bin/true",
        bus_provenance_sha256=digest("bus"),
        bus_capabilities=(REQUIRED_BUS_CAPABILITY,),
    )
    assert fact.binding.model_selection.mode == "explicit"
    with pytest.raises(Exception, match="capability"):
        ReadinessFact(
            nonce="b" * 32,
            expires_at=2_000_000_000,
            binding=spec.coder,
            source_commit=spec.frozen_base,
            tool_executable="/usr/bin/true",
            tool_version_sha256=digest("tool"),
            bus_executable="/usr/bin/true",
            bus_provenance_sha256=digest("bus"),
            bus_capabilities=(),
        )


def test_agent_bus_adapter_uses_versioned_tags_and_exact_result_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = fresh_spec(tmp_path)
    observed_types: list[str] = []

    def fake_run(argv, **_kwargs):
        event_type = argv[argv.index("--type") + 1]
        observed_types.append(event_type)
        payload = json.loads(argv[argv.index("--payload") + 1])
        if "readiness" in event_type and "result" not in event_type:
            nonce = payload["nonce"]
            value = {
                "nonce": nonce,
                "expires_at": payload["expires_at"],
                "binding": spec.coder.to_mapping(),
                "source_commit": spec.frozen_base,
                "tool_executable": "/usr/bin/true",
                "tool_version_sha256": digest("tool"),
                "bus_executable": "/usr/bin/true",
                "bus_provenance_sha256": digest("bus"),
                "bus_capabilities": [REQUIRED_BUS_CAPABILITY],
            }
            path = tmp_path / "state" / "runtime-v2" / "readiness" / nonce / "coder.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(value), encoding="utf-8")
        elif event_type == COMMAND_TYPE:
            command = CommandEnvelope.decode(payload["envelope"].encode("utf-8"))
            result = ResultEnvelope.create(
                run_id=command.run_id,
                task_id=command.task_id,
                run_spec_sha256=command.run_spec_sha256,
                source_role="coder",
                target_role="architect",
                route="result:awf-runtime-v2-result-v1",
                source_invocation_id=command.target_invocation_id,
                source_authorization_sha256=digest("worker"),
                target_invocation_id="source-result",
                causation_delivery_id=command.delivery_id,
                payload={"kind": "coder"},
            )
            path = (
                tmp_path
                / "state"
                / "runtime-v2"
                / "inbox"
                / command.run_id
                / f"{result.delivery_id.removeprefix('awfv2:')}.json"
            )
            path.parent.mkdir(parents=True)
            path.write_bytes(result.encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentBusClient(
        executable="/usr/bin/true",
        environment={},
        state_root=tmp_path / "state",
        timeout_seconds=1,
    )
    fact = client.probe(
        role="coder",
        agent_tool="opencode",
        model_selection=spec.coder.model_selection,
        source_commit=spec.frozen_base,
    )
    command = CommandEnvelope.create(
        run_id=spec.run_id,
        task_id=spec.task_id,
        run_spec_sha256=spec.sha256,
        source_role="architect",
        target_role="coder",
        route=spec.implement_route,
        source_invocation_id="source",
        source_authorization_sha256=digest("source"),
        target_invocation_id="coder-one",
        payload={"kind": "test"},
    )

    result = client.invoke(command)

    assert fact.binding == spec.coder
    assert result.causation_delivery_id == command.delivery_id
    assert observed_types == [
        "control:awf-runtime-v2-readiness-v1",
        "task:awf-runtime-v2-command-v1",
    ]


def test_stage_coordinator_adopts_exact_worker_result_without_duplicate_send(
    tmp_path: Path,
) -> None:
    spec = fresh_spec(tmp_path)

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0
            self.results: dict[str, ResultEnvelope] = {}

        def invoke(self, command: CommandEnvelope) -> ResultEnvelope:
            self.calls += 1
            authorization = command.payload["authorization_sha256"]
            result = ResultEnvelope.create(
                run_id=command.run_id,
                task_id=command.task_id,
                run_spec_sha256=command.run_spec_sha256,
                source_role="coder",
                target_role="architect",
                route="result:awf-runtime-v2-result-v1",
                source_invocation_id=command.target_invocation_id,
                source_authorization_sha256=authorization,
                target_invocation_id="source-coder",
                causation_delivery_id=command.delivery_id,
                payload={
                    "kind": "coder",
                    "process_identity_sha256": digest("process"),
                    "workspace_manifest_sha256": "sha256:" + digest("workspace"),
                },
            )
            self.results[command.delivery_id] = result
            return result

        def existing_result(self, command: CommandEnvelope) -> ResultEnvelope | None:
            return self.results.get(command.delivery_id)

    client = FakeClient()
    coordinator = FreshStageCoordinator(
        state_root=tmp_path / "state",
        writer_id="writer-stage-test",
        stage_client=client,  # type: ignore[arg-type]
        executables={"coder": "/usr/bin/true", "reviewer": "/usr/bin/true"},
    )
    store = coordinator.initialize(spec, tmp_path / "project")

    first = coordinator.invoke(
        store,
        spec,
        stage=WorkflowStage.IMPLEMENT,
        attempt=1,
        expected_commit=spec.frozen_base,
        input_text="implement exact card",
    )
    replay = coordinator.invoke(
        store,
        spec,
        stage=WorkflowStage.IMPLEMENT,
        attempt=1,
        expected_commit=spec.frozen_base,
        input_text="implement exact card",
    )

    assert first.envelope.encode() == replay.envelope.encode()
    assert client.calls == 1
    journal = store.journal(first.command.invocation_id).snapshot()
    assert journal.result is not None
