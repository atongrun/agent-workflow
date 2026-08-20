from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import agent_workflow.runtime.application as application_module
from agent_workflow.runtime import (
    ATTACH_INPUT,
    ApplicationError,
    AtomicRunStore,
    CommandEnvelope,
    DecisionOutcome,
    LocalRuntimeApplication,
    LocalStageRequest,
    LocalTransportBoundary,
    PostflightObservation,
    ProcessResult,
    ProviderSelection,
    ResultEnvelope,
    RunSpec,
    StoreError,
    SubprocessProviderLauncher,
    TerminalCommand,
    TerminalOutcome,
    TransportError,
    WorkflowStage,
    bind_environment,
    normalize_rework_feedback,
    parse_review_report,
)
from agent_workflow.runtime.contracts import RenderedInvocation
from tests.fixtures.runtime_v2_local_application_provider import ScriptedProviderLauncher

ROOT = Path(__file__).resolve().parents[1]
SHARED_CASES = ROOT / "tests" / "fixtures" / "runtime_v2_shared_slice_cases.json"


def digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


def git(repo: Path | None, *args: str, env: dict[str, str] | None = None) -> str:
    argv = ["git"]
    if repo is not None:
        argv += ["-C", str(repo)]
    completed = subprocess.run(
        [*argv, *args],
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    return completed.stdout.strip()


def environment(tmp_path: Path) -> tuple[tuple[str, str], ...]:
    inherited = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "COMSPEC",
            "HOMEDRIVE",
            "HOMEPATH",
            "PATH",
            "PATHEXT",
            "SYSTEMDRIVE",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "WINDIR",
        }
    }
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    inherited.update(
        {
            "GCM_INTERACTIVE": "Never",
            "GIT_CONFIG_COUNT": "4",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_KEY_1": "core.hooksPath",
            "GIT_CONFIG_KEY_2": "credential.helper",
            "GIT_CONFIG_KEY_3": "core.autocrlf",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_VALUE_1": os.devnull,
            "GIT_CONFIG_VALUE_2": "",
            "GIT_CONFIG_VALUE_3": "true" if os.name == "nt" else "false",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home.resolve()),
        }
    )
    return bind_environment(inherited)


@dataclass
class Fixture:
    root: Path
    state: Path
    workspaces: Path
    repo: Path
    env: tuple[tuple[str, str], ...]
    spec: RunSpec
    launcher: ScriptedProviderLauncher
    app: LocalRuntimeApplication

    def head(self) -> str:
        return git(self.repo, "rev-parse", "HEAD^{commit}", env=dict(self.env))

    def request(
        self,
        stage: WorkflowStage,
        label: str,
        attempt: int,
        *,
        verdict: str = "PASS",
        mode: str = "success",
        change_text: str | None = None,
        outgoing_target: str | None = None,
    ) -> LocalStageRequest:
        input_data = {
            "invocation_id": f"invoke-{label}",
            "stage": stage.value,
            "implementation_report": self.spec.implementation_report,
            "review_report": self.spec.review_report,
            "change_path": "result.txt",
            "change_text": change_text or f"{label}\n",
            "verdict": verdict,
            "mode": mode,
        }
        input_text = json.dumps(input_data, sort_keys=True)
        if stage is WorkflowStage.REWORK:
            review = parse_review_report(self.repo / self.spec.review_report).review.as_payload()
            input_text = normalize_rework_feedback(review)
        postflight = None
        if stage is not WorkflowStage.REVIEW:
            paths = (
                (self.spec.implementation_report, "result.txt")
                if stage is WorkflowStage.IMPLEMENT
                else ("result.txt",)
            )
            postflight = PostflightObservation(paths)
        incoming = (
            AtomicRunStore(self.state, self.spec.run_id, "writer-local-fixture").pending_handoff()
            if stage is not WorkflowStage.IMPLEMENT
            else None
        )
        return LocalStageRequest(
            invocation_id=f"invoke-{label}",
            stage=stage,
            attempt=attempt,
            delivery_id=incoming.delivery_id if incoming else f"delivery-{label}",
            payload_sha256=incoming.payload_sha256 if incoming else digest(f"payload-{label}"),
            outgoing_target_invocation_id=outgoing_target or f"invoke-next-{label}",
            provider_executable=str(Path(sys.executable).resolve()),
            provider_environment=self.env,
            input_text=input_text,
            provider_args=(self.spec.frozen_base,)
            if stage is WorkflowStage.REVIEW
            else (ATTACH_INPUT,),
            source_repo=str(self.repo),
            trusted_repo=str(self.repo),
            expected_commit=self.head(),
            workspace_state_dir=str(self.workspaces),
            python_executable=str(Path(sys.executable).resolve()),
            postflight=postflight,
        )


@pytest.fixture
def local_runtime(tmp_path: Path) -> Fixture:
    repo = tmp_path / "trusted"
    repo.mkdir()
    repo = repo.resolve()
    git(None, "init", "-q", "-b", "main", str(repo))
    git(repo, "config", "user.name", "Runtime Test")
    git(repo, "config", "user.email", "runtime@example.invalid")
    task_id = "runtime-v2-local-application-fixture"
    implementation = f".awf/artifacts/impl-report-{task_id}.md"
    review = f".awf/artifacts/review-report-{task_id}.md"
    card_path = Path("docs/tasks/runtime-v2-local-application-fixture.md")
    card = repo / card_path
    card.parent.mkdir(parents=True)
    payload = {
        "allowed_paths": ["result.txt", implementation, review],
        "verification_commands": [["{python}", "-c", "raise SystemExit(0)"]],
    }
    card.write_text(
        "# Local fixture\n\n<!-- awf-postflight\n" + json.dumps(payload, indent=2) + "\n-->\n",
        encoding="utf-8",
    )
    git(repo, "add", card_path.as_posix())
    git(repo, "commit", "-q", "-m", "freeze local fixture")
    base = git(repo, "rev-parse", "HEAD^{commit}")
    state = (tmp_path / "state").resolve()
    workspaces = (tmp_path / "workspaces").resolve()
    spec = RunSpec(
        run_id="task-runtime-v2-local-application-fixture",
        task_id=task_id,
        task_card=card_path.as_posix(),
        task_card_sha256=digest(card.read_bytes()),
        repository="local/disposable",
        frozen_base=base,
        task_branch="codex/runtime-v2-local-application-fixture",
        state_root_sha256=digest("awf-state-root-v1\0" + str(state)),
        semantic_contract_sha256=digest("frozen-semantic-contract"),
        coder=ProviderSelection("opencode", "fixture-coder"),
        reviewer=ProviderSelection("pi", "fixture-reviewer"),
        implement_attempts=1,
        review_attempts=2,
        rework_budget=1,
        implement_route="task:awf-impl-v3",
        review_route="task:awf-review-v3",
        rework_route="task:awf-rework-v3",
        implementation_report=implementation,
        review_report=review,
    )
    launcher = ScriptedProviderLauncher()
    app = LocalRuntimeApplication(state, "writer-local-fixture", launcher)
    return Fixture(tmp_path, state, workspaces, repo, environment(tmp_path), spec, launcher, app)


def files(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def authority_path(fixture: Fixture) -> Path:
    return fixture.state / "runtime-v2" / "runs" / fixture.spec.run_id / "authority.json"


def mutate_authority(fixture: Fixture, mutation, *, rechecksum: bool = True) -> None:
    path = authority_path(fixture)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    mutation(envelope["payload"])
    if rechecksum:
        canonical = json.dumps(
            envelope["payload"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        envelope["checksum"] = hashlib.sha256(canonical).hexdigest()
    path.write_text(
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


class _InjectedBoundary(RuntimeError):
    pass


def authorize_without_launch(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch, label: str = "implement"
) -> LocalStageRequest:
    request = fixture.request(WorkflowStage.IMPLEMENT, label, 1)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            application_module,
            "render_provider_invocation",
            lambda _spec: (_ for _ in ()).throw(_InjectedBoundary()),
        )
        with pytest.raises(_InjectedBoundary):
            fixture.app.run(fixture.spec, request)
    return request


def transport_command(
    fixture: Fixture,
    request: LocalStageRequest,
    payload: dict[str, object] | None = None,
) -> tuple[CommandEnvelope, LocalStageRequest]:
    envelope = CommandEnvelope.create(
        run_id=fixture.spec.run_id,
        task_id=fixture.spec.task_id,
        run_spec_sha256=fixture.spec.sha256,
        source_role="architect",
        target_role="coder",
        route=fixture.spec.implement_route,
        source_invocation_id="owner-dispatch",
        source_authorization_sha256=digest("owner-dispatch-authorization"),
        target_invocation_id=request.invocation_id,
        payload=payload or {"task_id": fixture.spec.task_id, "intent": "implement"},
    )
    return envelope, replace(
        request,
        delivery_id=envelope.delivery_id,
        payload_sha256=envelope.payload_sha256.removeprefix("sha256:"),
    )


def pending_result(
    fixture: Fixture,
    boundary: LocalTransportBoundary,
    request: LocalStageRequest,
    causation_delivery_id: str,
):
    intent = AtomicRunStore(
        fixture.state, fixture.spec.run_id, "writer-local-fixture"
    ).pending_handoff()
    assert intent is not None
    effect = (
        AtomicRunStore(fixture.state, fixture.spec.run_id, "writer-local-fixture")
        .journal(intent.source_invocation_id)
        .snapshot()
        .validation_effect
    )
    assert effect is not None
    if intent.target_role == "reviewer":
        payload = {
            "source_invocation_id": intent.source_invocation_id,
            "effect_sha256": effect.effect_sha256,
        }
        source_role = "coder"
    else:
        payload = json.loads(
            normalize_rework_feedback(
                parse_review_report(
                    fixture.repo / fixture.spec.review_report,
                    fixture.spec.review_report,
                ).review.as_payload()
            )
        )
        source_role = "reviewer"
    return boundary.prepare_result(
        fixture.spec,
        intent,
        source_role=source_role,
        target_role=intent.target_role,
        route=intent.route,
        target_invocation_id=request.invocation_id,
        causation_delivery_id=causation_delivery_id,
        payload=payload,
    )


def terminal_command(fixture: Fixture) -> TerminalCommand:
    authority = json.loads(authority_path(fixture).read_text(encoding="utf-8"))["payload"]
    raw = next(
        event["command"] for event in reversed(authority["events"]) if event["kind"] == "terminal"
    )
    return TerminalCommand(
        raw["run_spec_sha256"],
        raw["source_invocation_id"],
        raw["source_authorization_sha256"],
        raw["delivery_id"],
        raw["payload_sha256"],
        TerminalOutcome(raw["outcome"]),
        raw["evidence_sha256"],
    )


def test_installed_application_completes_pass_and_replay_is_byte_stable(
    local_runtime: Fixture,
) -> None:
    fixture = local_runtime
    assert (
        fixture.app.run(
            fixture.spec, fixture.request(WorkflowStage.IMPLEMENT, "implement", 1)
        ).stage
        is WorkflowStage.REVIEW
    )
    review = fixture.request(WorkflowStage.REVIEW, "review", 1)
    final = fixture.app.run(fixture.spec, review)

    assert final.terminal is TerminalOutcome.COMPLETED
    assert final.outcome is DecisionOutcome.TERMINAL_IDEMPOTENT
    assert fixture.launcher.calls == ["invoke-implement", "invoke-review"]
    assert git(fixture.repo, "remote") == ""
    before = files(fixture.state)
    trusted_head = fixture.head()
    assert fixture.app.run(fixture.spec, review) == final
    assert fixture.app.status(fixture.spec.run_id) == final
    assert files(fixture.state) == before
    assert fixture.head() == trusted_head
    assert fixture.launcher.calls == ["invoke-implement", "invoke-review"]


def test_installed_application_completes_one_bounded_rework(
    local_runtime: Fixture,
) -> None:
    fixture = local_runtime
    fixture.app.run(fixture.spec, fixture.request(WorkflowStage.IMPLEMENT, "implement", 1))
    fixture.app.run(
        fixture.spec,
        fixture.request(WorkflowStage.REVIEW, "review-one", 1, verdict="REQUEST_CHANGES"),
    )
    assert fixture.app.status(fixture.spec.run_id).stage is WorkflowStage.REWORK
    fixture.app.run(
        fixture.spec,
        fixture.request(WorkflowStage.REWORK, "rework", 1),
    )
    final = fixture.app.run(fixture.spec, fixture.request(WorkflowStage.REVIEW, "review-two", 2))

    assert final.terminal is TerminalOutcome.COMPLETED
    assert fixture.launcher.calls == [
        "invoke-implement",
        "invoke-review-one",
        "invoke-rework",
        "invoke-review-two",
    ]
    assert (fixture.repo / "result.txt").read_text(encoding="utf-8") == "invoke-rework\n"


def test_installed_application_records_blocked_terminal(local_runtime: Fixture) -> None:
    fixture = local_runtime
    fixture.app.run(fixture.spec, fixture.request(WorkflowStage.IMPLEMENT, "implement", 1))
    final = fixture.app.run(
        fixture.spec,
        fixture.request(WorkflowStage.REVIEW, "review", 1, verdict="BLOCKED"),
    )
    assert final.terminal is TerminalOutcome.BLOCKED


@pytest.mark.parametrize(
    ("verdict", "terminal"),
    [("PASS", TerminalOutcome.COMPLETED), ("BLOCKED", TerminalOutcome.BLOCKED)],
)
def test_transport_boundary_preserves_pass_and_blocked_result_sequences(
    local_runtime: Fixture,
    verdict: str,
    terminal: TerminalOutcome,
) -> None:
    fixture = local_runtime
    boundary = LocalTransportBoundary(fixture.app)
    implement = fixture.request(
        WorkflowStage.IMPLEMENT,
        "implement",
        1,
        outgoing_target="invoke-review",
    )
    command, implement = transport_command(fixture, implement)
    assert boundary.accept(fixture.spec, implement, command.encode()).stage is WorkflowStage.REVIEW

    review = fixture.request(
        WorkflowStage.REVIEW,
        "review",
        1,
        verdict=verdict,
        outgoing_target="invoke-architect-decision",
    )
    review_result = pending_result(fixture, boundary, review, command.delivery_id)
    final = boundary.accept(
        fixture.spec,
        review,
        review_result.encode(),
        expected_causation_delivery_id=command.delivery_id,
    )

    assert final.terminal is terminal
    terminal_intent = terminal_command(fixture)
    terminal_result = boundary.prepare_result(
        fixture.spec,
        terminal_intent,
        source_role="reviewer",
        target_role="architect",
        route=f"result:{terminal.value}",
        target_invocation_id="invoke-architect-decision",
        causation_delivery_id=review_result.delivery_id,
        payload=parse_review_report(
            fixture.repo / fixture.spec.review_report,
            fixture.spec.review_report,
        ).review.as_payload(),
    )
    assert terminal_result.delivery_id == terminal_intent.delivery_id
    assert fixture.launcher.calls == ["invoke-implement", "invoke-review"]


def test_transport_boundary_preserves_bounded_rework_and_second_review(
    local_runtime: Fixture,
) -> None:
    fixture = local_runtime
    boundary = LocalTransportBoundary(fixture.app)
    implement = fixture.request(
        WorkflowStage.IMPLEMENT,
        "implement",
        1,
        outgoing_target="invoke-review-one",
    )
    initial, implement = transport_command(fixture, implement)
    boundary.accept(fixture.spec, implement, initial.encode())

    review_one = fixture.request(
        WorkflowStage.REVIEW,
        "review-one",
        1,
        verdict="REQUEST_CHANGES",
        outgoing_target="invoke-rework",
    )
    review_input = pending_result(fixture, boundary, review_one, initial.delivery_id)
    boundary.accept(
        fixture.spec,
        review_one,
        review_input.encode(),
        expected_causation_delivery_id=initial.delivery_id,
    )

    rework = fixture.request(
        WorkflowStage.REWORK,
        "rework",
        1,
        outgoing_target="invoke-review-two",
    )
    rework_input = pending_result(fixture, boundary, rework, review_input.delivery_id)
    boundary.accept(
        fixture.spec,
        rework,
        rework_input.encode(),
        expected_causation_delivery_id=review_input.delivery_id,
    )

    review_two = fixture.request(
        WorkflowStage.REVIEW,
        "review-two",
        2,
        outgoing_target="invoke-architect-decision",
    )
    second_review_input = pending_result(
        fixture,
        boundary,
        review_two,
        rework_input.delivery_id,
    )
    final = boundary.accept(
        fixture.spec,
        review_two,
        second_review_input.encode(),
        expected_causation_delivery_id=rework_input.delivery_id,
    )

    assert final.terminal is TerminalOutcome.COMPLETED
    assert fixture.launcher.calls == [
        "invoke-implement",
        "invoke-review-one",
        "invoke-rework",
        "invoke-review-two",
    ]


def test_valid_but_foreign_result_denies_before_application_or_store_mutation(
    local_runtime: Fixture,
) -> None:
    fixture = local_runtime
    boundary = LocalTransportBoundary(fixture.app)
    implement = fixture.request(
        WorkflowStage.IMPLEMENT,
        "implement",
        1,
        outgoing_target="invoke-review",
    )
    command, implement = transport_command(fixture, implement)
    boundary.accept(fixture.spec, implement, command.encode())
    review = fixture.request(
        WorkflowStage.REVIEW,
        "review",
        1,
        outgoing_target="invoke-architect-decision",
    )
    exact = pending_result(fixture, boundary, review, command.delivery_id)
    foreign = ResultEnvelope.create(
        run_id=exact.run_id,
        task_id=exact.task_id,
        run_spec_sha256=exact.run_spec_sha256,
        source_role=exact.source_role,
        target_role=exact.target_role,
        route=exact.route,
        source_invocation_id=exact.source_invocation_id,
        source_authorization_sha256=digest("foreign-authorization"),
        target_invocation_id=exact.target_invocation_id,
        causation_delivery_id=exact.causation_delivery_id,
        payload=exact.payload,
    )
    foreign_request = replace(
        review,
        delivery_id=foreign.delivery_id,
        payload_sha256=foreign.payload_sha256.removeprefix("sha256:"),
    )
    before = files(fixture.state)

    with pytest.raises(TransportError):
        boundary.accept(
            fixture.spec,
            foreign_request,
            foreign.encode(),
            expected_causation_delivery_id=command.delivery_id,
        )
    assert fixture.launcher.calls == ["invoke-implement"]
    assert files(fixture.state) == before


def test_provider_artifact_failure_is_durable_and_never_replays(local_runtime: Fixture) -> None:
    fixture = local_runtime
    request = fixture.request(
        WorkflowStage.IMPLEMENT, "missing-artifact", 1, mode="missing_artifact"
    )
    with pytest.raises(ApplicationError) as failure:
        fixture.app.run(fixture.spec, request)
    assert failure.value.outcome is DecisionOutcome.HANDLER_FAILURE_NO_ACK
    before = files(fixture.state)
    with pytest.raises(ApplicationError) as replay:
        fixture.app.run(fixture.spec, request)
    assert replay.value.outcome is DecisionOutcome.HANDLER_FAILURE_NO_ACK
    assert fixture.launcher.calls == ["invoke-missing-artifact"]
    assert files(fixture.state) == before


class _CrashingHandle:
    process_identity_sha256 = digest("crashing-process")

    def wait(self) -> ProcessResult:
        raise RuntimeError("simulated process observation boundary crash")


class _CrashingLauncher:
    def __init__(self) -> None:
        self.calls = 0

    def start(self, invocation: RenderedInvocation) -> _CrashingHandle:
        self.calls += 1
        return _CrashingHandle()


def test_launch_without_result_is_ambiguous_and_stop_cannot_guess(
    local_runtime: Fixture,
) -> None:
    fixture = local_runtime
    launcher = _CrashingLauncher()
    app = LocalRuntimeApplication(fixture.state, "writer-local-fixture", launcher)
    request = fixture.request(WorkflowStage.IMPLEMENT, "ambiguous", 1)
    with pytest.raises(RuntimeError, match="observation boundary"):
        app.run(fixture.spec, request)
    before = files(fixture.state)

    status = app.run(fixture.spec, request)
    assert status.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert launcher.calls == 1
    with pytest.raises(StoreError) as stop:
        app.stop(fixture.spec)
    assert stop.value.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert files(fixture.state) == before


def test_exact_transport_redelivery_preserves_provider_ambiguity_without_replay(
    local_runtime: Fixture,
) -> None:
    fixture = local_runtime
    launcher = _CrashingLauncher()
    app = LocalRuntimeApplication(fixture.state, "writer-local-fixture", launcher)
    boundary = LocalTransportBoundary(app)
    request = fixture.request(
        WorkflowStage.IMPLEMENT,
        "ambiguous",
        1,
        outgoing_target="invoke-review",
    )
    envelope, request = transport_command(fixture, request)

    with pytest.raises(RuntimeError, match="observation boundary"):
        boundary.accept(fixture.spec, request, envelope.encode())
    before = files(fixture.state)
    status = boundary.accept(fixture.spec, request, envelope.encode())

    assert status.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert launcher.calls == 1
    assert files(fixture.state) == before


def test_exact_local_stop_is_idempotent_and_denies_future_run(local_runtime: Fixture) -> None:
    fixture = local_runtime
    AtomicRunStore(fixture.state, fixture.spec.run_id, "writer-local-fixture").initialize(
        fixture.spec
    )
    stopped = fixture.app.stop(fixture.spec)
    before = files(fixture.state)
    assert stopped.stopped
    assert stopped.outcome is DecisionOutcome.OWNER_DECISION_REQUIRED
    assert fixture.app.stop(fixture.spec) == stopped
    assert (
        fixture.app.run(fixture.spec, fixture.request(WorkflowStage.IMPLEMENT, "after-stop", 1))
        == stopped
    )
    assert fixture.launcher.calls == []
    assert files(fixture.state) == before


def test_taskcard_and_trusted_head_drift_deny_before_provider(local_runtime: Fixture) -> None:
    fixture = local_runtime
    AtomicRunStore(fixture.state, fixture.spec.run_id, "writer-local-fixture").initialize(
        fixture.spec
    )
    request = fixture.request(WorkflowStage.IMPLEMENT, "identity-drift", 1)
    card = fixture.repo / fixture.spec.task_card
    card.write_text(card.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    before = files(fixture.state)
    with pytest.raises(ApplicationError) as card_failure:
        fixture.app.run(fixture.spec, request)
    assert card_failure.value.outcome is DecisionOutcome.DENY_BEFORE_PROVIDER
    assert fixture.launcher.calls == []
    assert files(fixture.state) == before


def test_subprocess_launcher_uses_structured_argv_bound_environment_and_file(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "input.txt"
    code = (
        "import os,pathlib,sys;"
        "data=pathlib.Path(sys.argv[1]).read_text();"
        "sys.stdout.write(os.environ['BOUND']+'|'+data+'|'+sys.stdin.read())"
    )
    from agent_workflow.runtime import RenderedInputFile

    rendered = RenderedInvocation(
        str(Path(sys.executable).resolve()),
        ("-c", code, str(target)),
        str(workspace.resolve()),
        stdin=b"stdin",
        environment=bind_environment({"BOUND": "exact"}),
        file_inputs=(RenderedInputFile(str(target), b"file"),),
    )
    result = SubprocessProviderLauncher().start(rendered).wait()
    assert result.return_code == 0
    assert result.stdout == b"exact|file|stdin"


FAULT_IDS = (
    "S-AUTH-START-PREPARED",
    "S-AUTH-START-MISSING-JOURNAL",
    "S-AUTH-START-AUTHORIZED-PREPARED",
    "S-AUTH-START-LAUNCH-NO-RESULT",
    "S-START-RESULT",
    "S-ARTIFACT",
    "S-RESULT-VALIDATE",
    "S-EFFECT-INTENT",
    "S-DUPLICATE-PRE-START",
    "S-DUPLICATE-TERMINAL",
    "S-STATE-DRIFT-CHECKSUM",
    "S-STATE-DRIFT-RUNSPEC-RECHECKSUM",
    "S-STATE-DRIFT-JOURNAL-RECHECKSUM",
    "S-GIT-DRIFT",
)


def shared_rows() -> dict[str, dict[str, object]]:
    fixture = json.loads(SHARED_CASES.read_text(encoding="utf-8"))
    rows = [row for case in fixture["cases"] for row in case.get("subcases", [case])]
    return {str(row["id"]): row for row in rows}


class _StartCrashLauncher:
    def __init__(self) -> None:
        self.calls = 0

    def start(self, _invocation: RenderedInvocation):
        self.calls += 1
        raise _InjectedBoundary()


@pytest.mark.parametrize("case_id", FAULT_IDS)
def test_all_shared_fault_rows_execute_against_installed_application(
    local_runtime: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    fixture = local_runtime
    row = shared_rows()[case_id]
    request = fixture.request(WorkflowStage.IMPLEMENT, "implement", 1)
    observed: DecisionOutcome

    if case_id == "S-AUTH-START-PREPARED":
        authorize_without_launch(fixture, monkeypatch)

        def orphan(payload):
            payload["events"] = []
            payload["sequence"] = 1

        mutate_authority(fixture, orphan)
        with pytest.raises(StoreError) as failure:
            fixture.app.status(fixture.spec.run_id)
        observed = failure.value.outcome
    elif case_id == "S-AUTH-START-MISSING-JOURNAL":
        authorize_without_launch(fixture, monkeypatch)
        mutate_authority(fixture, lambda payload: payload["journals"].clear())
        with pytest.raises(StoreError) as failure:
            fixture.app.status(fixture.spec.run_id)
        observed = failure.value.outcome
        assert failure.value.next_action == row["legal_next_action"]
    elif case_id in {"S-AUTH-START-AUTHORIZED-PREPARED", "S-DUPLICATE-PRE-START"}:
        authorize_without_launch(fixture, monkeypatch)
        before = files(fixture.state)
        observed = fixture.app.status(fixture.spec.run_id).outcome
        assert fixture.app.status(fixture.spec.run_id).outcome is observed
        assert files(fixture.state) == before
        assert fixture.launcher.calls == []
    elif case_id == "S-AUTH-START-LAUNCH-NO-RESULT":
        launcher = _StartCrashLauncher()
        app = LocalRuntimeApplication(fixture.state, "writer-local-fixture", launcher)
        with pytest.raises(_InjectedBoundary):
            app.run(fixture.spec, request)
        observed = app.status(fixture.spec.run_id).outcome
        assert app.run(fixture.spec, request).outcome is observed
        assert launcher.calls == 1
    elif case_id == "S-START-RESULT":
        launcher = _CrashingLauncher()
        app = LocalRuntimeApplication(fixture.state, "writer-local-fixture", launcher)
        with pytest.raises(RuntimeError):
            app.run(fixture.spec, request)
        observed = app.status(fixture.spec.run_id).outcome
        assert app.run(fixture.spec, request).outcome is observed
        assert launcher.calls == 1
    elif case_id == "S-ARTIFACT":
        bad = fixture.request(WorkflowStage.IMPLEMENT, "implement", 1, mode="missing_artifact")
        with pytest.raises(ApplicationError) as failure:
            fixture.app.run(fixture.spec, bad)
        observed = failure.value.outcome
        with pytest.raises(ApplicationError):
            fixture.app.run(fixture.spec, bad)
        assert fixture.launcher.calls == ["invoke-implement"]
    elif case_id == "S-RESULT-VALIDATE":
        with monkeypatch.context() as patcher:
            patcher.setattr(
                fixture.app,
                "_finish_coder",
                lambda *_args: (_ for _ in ()).throw(_InjectedBoundary()),
            )
            with pytest.raises(_InjectedBoundary):
                fixture.app.run(fixture.spec, request)
        observed = fixture.app.status(fixture.spec.run_id).outcome
        assert fixture.app.run(fixture.spec, request).stage is WorkflowStage.REVIEW
        assert fixture.launcher.calls == ["invoke-implement"]
    elif case_id == "S-EFFECT-INTENT":
        with monkeypatch.context() as patcher:
            patcher.setattr(
                AtomicRunStore,
                "record_handoff",
                lambda *_args: (_ for _ in ()).throw(_InjectedBoundary()),
            )
            with pytest.raises(_InjectedBoundary):
                fixture.app.run(fixture.spec, request)
        observed = fixture.app.status(fixture.spec.run_id).outcome
        assert fixture.head() != fixture.spec.frozen_base
        assert fixture.app.run(fixture.spec, request).stage is WorkflowStage.REVIEW
        assert fixture.launcher.calls == ["invoke-implement"]
    elif case_id == "S-DUPLICATE-TERMINAL":
        fixture.app.run(fixture.spec, request)
        review = fixture.request(WorkflowStage.REVIEW, "review", 1)
        fixture.app.run(fixture.spec, review)
        before = files(fixture.state)
        observed = fixture.app.run(fixture.spec, review).outcome
        assert files(fixture.state) == before
        assert fixture.launcher.calls == ["invoke-implement", "invoke-review"]
    elif case_id.startswith("S-STATE-DRIFT"):
        if case_id == "S-STATE-DRIFT-CHECKSUM":
            AtomicRunStore(fixture.state, fixture.spec.run_id, "writer-local-fixture").initialize(
                fixture.spec
            )
            mutate_authority(
                fixture,
                lambda payload: payload.__setitem__("run_id", "run-drift"),
                rechecksum=False,
            )
        elif case_id == "S-STATE-DRIFT-RUNSPEC-RECHECKSUM":
            AtomicRunStore(fixture.state, fixture.spec.run_id, "writer-local-fixture").initialize(
                fixture.spec
            )
            mutate_authority(
                fixture,
                lambda payload: payload["run_spec"].__setitem__(
                    "task_card_sha256", digest("drift")
                ),
            )
        else:
            authorize_without_launch(fixture, monkeypatch)

            def drift_journal(payload):
                payload["journals"]["invoke-implement"]["authorization"][
                    "invocation_spec_sha256"
                ] = digest("drift")

            mutate_authority(
                fixture,
                drift_journal,
            )
        with pytest.raises(StoreError) as failure:
            fixture.app.status(fixture.spec.run_id)
        observed = failure.value.outcome
    else:
        fixture.app.run(fixture.spec, request)
        review = fixture.request(WorkflowStage.REVIEW, "review", 1)
        with monkeypatch.context() as patcher:
            patcher.setattr(
                fixture.app,
                "_finish_review",
                lambda *_args: (_ for _ in ()).throw(_InjectedBoundary()),
            )
            with pytest.raises(_InjectedBoundary):
                fixture.app.run(fixture.spec, review)
        (fixture.repo / "drift.txt").write_text("drift\n", encoding="utf-8")
        git(fixture.repo, "add", "drift.txt", env=dict(fixture.env))
        git(fixture.repo, "commit", "-q", "-m", "inject drift", env=dict(fixture.env))
        with pytest.raises(ApplicationError) as failure:
            fixture.app.run(fixture.spec, review)
        observed = failure.value.outcome
        assert fixture.launcher.calls == ["invoke-implement", "invoke-review"]

    assert observed is DecisionOutcome(str(row["expected_outcome"]))
