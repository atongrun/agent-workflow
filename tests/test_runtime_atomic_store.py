from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path

import pytest

import agent_workflow.runtime.store as runtime_store
from agent_workflow.runtime import (
    AUTHORITY_FORMAT,
    AtomicInvocationJournal,
    AtomicRunStore,
    AtomicStatusReader,
    AuthorizationCommand,
    DecisionOutcome,
    HandoffCommand,
    JournalAuthorization,
    LaunchIntent,
    ProcessObservation,
    ProviderResult,
    ProviderSelection,
    RunSpec,
    RunStore,
    StatusReader,
    StopCommand,
    StoreError,
    TerminalCommand,
    TerminalOutcome,
    ValidationEffect,
    WorkflowStage,
    WriterBusy,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def root_digest(root: Path) -> str:
    value = "awf-state-root-v1\0" + str(root.resolve())
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def make_spec(
    root: Path,
    *,
    run_id: str = "task-runtime-v2-rts-031",
    implement_attempts: int = 1,
    review_attempts: int = 2,
    rework_budget: int = 1,
) -> RunSpec:
    return RunSpec(
        run_id=run_id,
        task_id="runtime-v2-rts-031",
        task_card="docs/tasks/runtime-v2-rts-031-atomic-store-journal.md",
        task_card_sha256=digest("task-card"),
        repository="atongrun/agent-workflow",
        frozen_base="a" * 40,
        task_branch="codex/runtime-v2-rts-031-atomic-store-journal",
        state_root_sha256=root_digest(root),
        semantic_contract_sha256=digest("frozen-contract"),
        coder=ProviderSelection("opencode", "coder/model"),
        reviewer=ProviderSelection("pi", "reviewer/model"),
        implement_attempts=implement_attempts,
        review_attempts=review_attempts,
        rework_budget=rework_budget,
        implement_route="task:awf-impl-v3",
        review_route="task:awf-review-v3",
        rework_route="task:awf-rework-v3",
        implementation_report=".awf/artifacts/impl-rts-031.md",
        review_report=".awf/artifacts/review-rts-031.md",
    )


def initialized_store(root: Path, *, rework_budget: int = 1) -> tuple[AtomicRunStore, RunSpec]:
    spec = make_spec(root, rework_budget=rework_budget)
    store = AtomicRunStore(root, spec.run_id, "writer-rts-031")
    snapshot = store.initialize(spec)
    assert snapshot.sequence == 1
    assert snapshot.stage is WorkflowStage.IMPLEMENT
    return store, spec


def authorize(
    store: AtomicRunStore,
    spec: RunSpec,
    stage: WorkflowStage,
    label: str,
    attempt: int,
) -> tuple[AuthorizationCommand, AtomicInvocationJournal]:
    role = "reviewer" if stage is WorkflowStage.REVIEW else "coder"
    incoming = store.pending_handoff()
    command = AuthorizationCommand(
        run_spec_sha256=spec.sha256,
        invocation_id=f"invoke-{label}",
        authorization_sha256=digest(f"authorization-{label}"),
        stage=stage,
        role=role,
        attempt=attempt,
        delivery_id=incoming.delivery_id if incoming else f"delivery-{label}",
        payload_sha256=incoming.payload_sha256 if incoming else digest(f"payload-{label}"),
    )
    fact = JournalAuthorization(
        run_spec_sha256=spec.sha256,
        invocation_id=command.invocation_id,
        authorization_sha256=command.authorization_sha256,
        invocation_spec_sha256=digest(f"invocation-spec-{label}"),
    )
    assert store.authorize(command, fact).outcome is DecisionOutcome.SAFE_CONTINUE
    journal = store.journal(command.invocation_id)
    assert isinstance(journal, AtomicInvocationJournal)
    return command, journal


def complete_provider(
    journal: AtomicInvocationJournal,
    command: AuthorizationCommand,
    label: str,
) -> ValidationEffect:
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
    return ValidationEffect(
        command.authorization_sha256,
        result.result_sha256,
        digest(f"artifact-{label}"),
        digest(f"effect-{label}"),
    )


def handoff(
    store: AtomicRunStore,
    spec: RunSpec,
    source: AuthorizationCommand,
    effect: ValidationEffect,
    label: str,
) -> HandoffCommand:
    review_bound = source.stage in {WorkflowStage.IMPLEMENT, WorkflowStage.REWORK}
    command = HandoffCommand(
        run_spec_sha256=spec.sha256,
        source_invocation_id=source.invocation_id,
        source_authorization_sha256=source.authorization_sha256,
        delivery_id=f"delivery-handoff-{label}",
        payload_sha256=digest(f"handoff-payload-{label}"),
        route=spec.review_route if review_bound else spec.rework_route,
        target_role="reviewer" if review_bound else "coder",
    )
    assert store.record_handoff(command, effect).outcome is DecisionOutcome.SAFE_CONTINUE
    return command


def terminal(
    store: AtomicRunStore,
    spec: RunSpec,
    source: AuthorizationCommand,
    effect: ValidationEffect,
    outcome: TerminalOutcome = TerminalOutcome.COMPLETED,
) -> TerminalCommand:
    command = TerminalCommand(
        run_spec_sha256=spec.sha256,
        source_invocation_id=source.invocation_id,
        source_authorization_sha256=source.authorization_sha256,
        delivery_id="delivery-terminal",
        payload_sha256=digest("terminal-payload"),
        outcome=outcome,
        evidence_sha256=digest("terminal-evidence"),
    )
    assert store.record_terminal(command, effect).outcome is DecisionOutcome.SAFE_CONTINUE
    return command


def files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def load_envelope(store: AtomicRunStore) -> dict[str, object]:
    return json.loads(store.path.read_text(encoding="utf-8"))


def write_envelope(store: AtomicRunStore, envelope: dict[str, object]) -> None:
    store.path.write_bytes(canonical(envelope) + b"\n")


def rechecksum(envelope: dict[str, object]) -> None:
    envelope["checksum"] = hashlib.sha256(canonical(envelope["payload"])).hexdigest()


def test_store_is_one_envelope_one_lock_and_exact_idempotent(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    before = store.path.read_bytes()
    reopened = AtomicRunStore(tmp_path, spec.run_id, "writer-rts-031")

    assert isinstance(store, RunStore)
    assert isinstance(AtomicStatusReader(tmp_path, spec.run_id), StatusReader)
    assert reopened.initialize(spec).sequence == 1
    assert store.path.read_bytes() == before
    changed = dataclasses.replace(spec, task_card_sha256=digest("changed-task-card"))
    with pytest.raises(StoreError, match="immutable RunSpec drift"):
        reopened.initialize(changed)
    assert store.path.read_bytes() == before
    assert files(tmp_path) == {
        f"runtime-v2/runs/{spec.run_id}/authority.json": before,
    }
    envelope = load_envelope(store)
    assert envelope["format"] == AUTHORITY_FORMAT
    assert envelope["payload"]["journals"] == {}
    forbidden = {"checkpoint", "outbox", "inbox"}
    assert not any(any(term in name for term in forbidden) for name in files(tmp_path))


def test_full_implement_review_rework_review_terminal_route(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    implement, impl_journal = authorize(store, spec, WorkflowStage.IMPLEMENT, "implement", 1)
    impl_effect = complete_provider(impl_journal, implement, "implement")
    handoff(store, spec, implement, impl_effect, "implement-review")
    status = AtomicStatusReader(tmp_path, spec.run_id)
    assert status.snapshot(spec.run_id).stage is WorkflowStage.REVIEW

    review_one, review_one_journal = authorize(store, spec, WorkflowStage.REVIEW, "review-one", 1)
    review_one_effect = complete_provider(review_one_journal, review_one, "review-one")
    handoff(store, spec, review_one, review_one_effect, "review-rework")
    assert status.snapshot(spec.run_id).stage is WorkflowStage.REWORK

    rework, rework_journal = authorize(store, spec, WorkflowStage.REWORK, "rework", 1)
    rework_effect = complete_provider(rework_journal, rework, "rework")
    handoff(store, spec, rework, rework_effect, "rework-review")
    status = AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert status.stage is WorkflowStage.REVIEW
    assert status.cause == "review authorization is required"

    review_two, review_two_journal = authorize(store, spec, WorkflowStage.REVIEW, "review-two", 2)
    review_two_effect = complete_provider(review_two_journal, review_two, "review-two")
    command = terminal(store, spec, review_two, review_two_effect)
    final = AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert final.terminal is TerminalOutcome.COMPLETED
    assert final.outcome is DecisionOutcome.TERMINAL_IDEMPOTENT
    assert final.next_action == "status or exact stop only"

    before = store.path.read_bytes()
    replay = store.record_terminal(command, review_two_effect)
    assert replay.outcome is DecisionOutcome.TERMINAL_IDEMPOTENT
    assert replay.sequence == final.sequence
    assert store.path.read_bytes() == before


def test_recovery_status_never_guesses_provider_replay(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    command, journal = authorize(store, spec, WorkflowStage.IMPLEMENT, "recover", 1)
    status = AtomicStatusReader(tmp_path, spec.run_id)
    before = files(tmp_path)
    ready = status.snapshot(spec.run_id)
    assert ready.first_blocker is None
    assert ready.outcome is DecisionOutcome.SAFE_CONTINUE
    assert ready.next_action == "invoke once after exact gates and journal revalidation"
    assert files(tmp_path) == before

    launch = LaunchIntent(command.authorization_sha256, digest("rendered-recover"))
    launch_snapshot = journal.record_launch_intent(launch)
    ambiguous = status.snapshot(spec.run_id)
    assert launch_snapshot.result is None
    assert ambiguous.first_blocker == "provider outcome is ambiguous"
    assert ambiguous.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert ambiguous.next_action == "preserve exact process/workspace/evidence for owner decision"

    process = ProcessObservation(command.authorization_sha256, digest("process-recover"))
    journal.record_process_observation(process)
    process_ambiguous = status.snapshot(spec.run_id)
    assert process_ambiguous.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    result = ProviderResult(
        command.authorization_sha256,
        process.process_identity_sha256,
        0,
        digest("result-recover"),
    )
    journal.record_result(result)
    recoverable = status.snapshot(spec.run_id)
    assert recoverable.first_blocker is None
    assert recoverable.outcome is DecisionOutcome.SAFE_CONTINUE
    assert recoverable.next_action == (
        "skip provider and run frozen postflight against exact durable workspace"
    )


def test_exact_journal_and_handoff_replays_are_stable(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    command, journal = authorize(store, spec, WorkflowStage.IMPLEMENT, "stable", 1)
    authorization = journal.snapshot()
    exact = JournalAuthorization(
        authorization.run_spec_sha256,
        authorization.invocation_id,
        authorization.authorization_sha256,
        authorization.invocation_spec_sha256,
    )
    before = store.path.read_bytes()
    assert store.authorize(command, exact).outcome is DecisionOutcome.SAFE_IDEMPOTENT_REPLAY
    assert store.path.read_bytes() == before

    launch = LaunchIntent(command.authorization_sha256, digest("stable-rendered"))
    journal.record_launch_intent(launch)
    before = store.path.read_bytes()
    first = journal.snapshot()
    assert journal.record_launch_intent(launch) == first
    assert store.path.read_bytes() == before

    effect = complete_provider_from_launch(journal, command, "stable")
    snapshot = journal.snapshot()
    assert snapshot.process_observation is not None
    assert snapshot.result is not None
    before = store.path.read_bytes()
    assert journal.record_process_observation(snapshot.process_observation) == snapshot
    assert journal.record_result(snapshot.result) == snapshot
    assert store.path.read_bytes() == before
    outgoing = handoff(store, spec, command, effect, "stable")
    before = store.path.read_bytes()
    resend = store.record_handoff(outgoing, effect)
    assert resend.outcome is DecisionOutcome.SAFE_STABLE_RESEND
    assert store.path.read_bytes() == before


def complete_provider_from_launch(
    journal: AtomicInvocationJournal,
    command: AuthorizationCommand,
    label: str,
) -> ValidationEffect:
    process = ProcessObservation(command.authorization_sha256, digest(f"process-{label}"))
    result = ProviderResult(
        command.authorization_sha256, process.process_identity_sha256, 0, digest(f"result-{label}")
    )
    journal.record_process_observation(process)
    journal.record_result(result)
    return ValidationEffect(
        command.authorization_sha256,
        result.result_sha256,
        digest(f"artifact-{label}"),
        digest(f"effect-{label}"),
    )


def test_conflicting_and_out_of_order_facts_deny_without_mutation(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    command, journal = authorize(store, spec, WorkflowStage.IMPLEMENT, "ordered", 1)

    before = store.path.read_bytes()
    process = ProcessObservation(command.authorization_sha256, digest("process-ordered"))
    with pytest.raises(StoreError):
        journal.record_process_observation(process)
    assert store.path.read_bytes() == before

    launch = LaunchIntent(command.authorization_sha256, digest("rendered-ordered"))
    journal.record_launch_intent(launch)
    before = store.path.read_bytes()
    with pytest.raises(StoreError):
        changed = dataclasses.replace(launch, rendered_invocation_sha256=digest("drift"))
        journal.record_launch_intent(changed)
    with pytest.raises(StoreError):
        journal.record_result(
            ProviderResult(
                command.authorization_sha256,
                process.process_identity_sha256,
                0,
                digest("early"),
            )
        )
    assert store.path.read_bytes() == before


def test_stage_attempt_route_and_rework_budgets_fail_closed(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path, rework_budget=0)
    bad = AuthorizationCommand(
        spec.sha256,
        "invoke-attempt-two",
        digest("attempt-two-auth"),
        WorkflowStage.IMPLEMENT,
        "coder",
        2,
        "delivery-attempt-two",
        digest("attempt-two-payload"),
    )
    fact = JournalAuthorization(
        spec.sha256,
        bad.invocation_id,
        bad.authorization_sha256,
        digest("attempt-two-spec"),
    )
    before = store.path.read_bytes()
    with pytest.raises(StoreError):
        store.authorize(bad, fact)
    assert store.path.read_bytes() == before

    implement, journal = authorize(store, spec, WorkflowStage.IMPLEMENT, "zero-rework", 1)
    effect = complete_provider(journal, implement, "zero-rework")
    wrong = HandoffCommand(
        spec.sha256,
        implement.invocation_id,
        implement.authorization_sha256,
        "delivery-wrong-route",
        digest("wrong-route-payload"),
        spec.rework_route,
        "coder",
    )
    before = store.path.read_bytes()
    with pytest.raises(StoreError):
        store.record_handoff(wrong, effect)
    assert store.path.read_bytes() == before

    handoff(store, spec, implement, effect, "zero-review")
    review, review_journal = authorize(store, spec, WorkflowStage.REVIEW, "zero-review", 1)
    review_effect = complete_provider(review_journal, review, "zero-review")
    request_rework = HandoffCommand(
        spec.sha256,
        review.invocation_id,
        review.authorization_sha256,
        "delivery-zero-rework-request",
        digest("zero-rework-request"),
        spec.rework_route,
        "coder",
    )
    before = store.path.read_bytes()
    with pytest.raises(StoreError, match="rework capacity"):
        store.record_handoff(request_rework, review_effect)
    assert store.path.read_bytes() == before


def test_status_and_stale_lock_are_strictly_read_only(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    store.lock_path.write_bytes(b"retained-stale-lock")
    before = files(tmp_path)

    status = AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert status.first_blocker == "exact writer lock is active"
    assert status.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert status.owner == "owner"
    assert files(tmp_path) == before
    with pytest.raises(WriterBusy) as caught:
        authorize(store, spec, WorkflowStage.IMPLEMENT, "locked", 1)
    assert caught.value.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert files(tmp_path) == before


def test_replace_failure_preserves_authority_and_temp_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, spec = initialized_store(tmp_path)
    authority_before = store.path.read_bytes()

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(runtime_store.os, "replace", fail_replace)
    with pytest.raises(WriterBusy) as caught:
        authorize(store, spec, WorkflowStage.IMPLEMENT, "replace-failure", 1)
    assert caught.value.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert store.path.read_bytes() == authority_before
    assert not store.lock_path.exists()
    assert list(store.run_dir.glob(".authority.json.tmp-*"))


def test_conflicting_lock_token_is_preserved_after_ambiguous_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, spec = initialized_store(tmp_path)
    real_replace = os.replace

    def replace_and_conflict(source: Path, target: Path) -> None:
        real_replace(source, target)
        store.lock_path.write_bytes(b"foreign-lock-token")

    monkeypatch.setattr(runtime_store.os, "replace", replace_and_conflict)
    with pytest.raises(WriterBusy, match="lock changed"):
        authorize(store, spec, WorkflowStage.IMPLEMENT, "lock-conflict", 1)
    assert store.lock_path.read_bytes() == b"foreign-lock-token"
    assert "invoke-lock-conflict" in load_envelope(store)["payload"]["journals"]


@pytest.mark.parametrize("fault", ["checksum", "unknown", "semantic", "sequence", "ordering"])
def test_corrupt_or_rechecksummed_drift_never_authorizes(tmp_path: Path, fault: str) -> None:
    store, spec = initialized_store(tmp_path)
    command, journal = authorize(store, spec, WorkflowStage.IMPLEMENT, "corrupt", 1)
    envelope = load_envelope(store)
    payload = envelope["payload"]
    if fault == "checksum":
        envelope["checksum"] = "0" * 64
    elif fault == "unknown":
        payload["unexpected"] = True
        rechecksum(envelope)
    elif fault == "semantic":
        payload["events"][0]["command"]["attempt"] = 2
        rechecksum(envelope)
    elif fault == "sequence":
        payload["sequence"] += 10
        rechecksum(envelope)
    else:
        payload["journals"][command.invocation_id]["process_observation"] = {
            "authorization_sha256": command.authorization_sha256,
            "process_identity_sha256": digest("impossible-process"),
        }
        rechecksum(envelope)
    write_envelope(store, envelope)
    broken = store.path.read_bytes()
    with pytest.raises(StoreError):
        journal.snapshot()
    with pytest.raises(StoreError):
        AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert store.path.read_bytes() == broken


def test_duplicate_keys_new_schema_and_writer_drift_fail_closed(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    valid = store.path.read_text(encoding="utf-8").strip()
    store.path.write_text(valid[:-1] + ',"format":"duplicate"}\n', encoding="utf-8")
    duplicate = store.path.read_bytes()
    with pytest.raises(StoreError, match="duplicate key"):
        AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert store.path.read_bytes() == duplicate

    store.path.write_text(valid + "\n", encoding="utf-8")
    envelope = load_envelope(store)
    envelope["payload"]["schema_version"] = 3
    rechecksum(envelope)
    write_envelope(store, envelope)
    newer = store.path.read_bytes()
    with pytest.raises(StoreError) as caught:
        AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert caught.value.outcome is DecisionOutcome.OWNER_DECISION_REQUIRED
    assert store.path.read_bytes() == newer

    store.path.write_text(valid + "\n", encoding="utf-8")
    wrong_writer = AtomicRunStore(tmp_path, spec.run_id, "other-writer")
    before = store.path.read_bytes()
    with pytest.raises(StoreError, match="writer identity drift"):
        wrong_writer.initialize(spec)
    assert store.path.read_bytes() == before


def test_missing_foreign_and_symlink_authority_cannot_authorize(tmp_path: Path) -> None:
    missing = AtomicStatusReader(tmp_path, "task-missing")
    with pytest.raises(StoreError) as caught:
        missing.snapshot("task-missing")
    assert caught.value.outcome is DecisionOutcome.EXTERNAL_OBSERVATION_UNKNOWN

    source_root = tmp_path / "source"
    source_store, source_spec = initialized_store(source_root)
    foreign_root = tmp_path / "foreign"
    foreign = AtomicRunStore(foreign_root, source_spec.run_id, "writer-rts-031")
    foreign.run_dir.mkdir(parents=True)
    foreign.path.write_bytes(source_store.path.read_bytes())
    before = foreign.path.read_bytes()
    with pytest.raises(StoreError, match="state-root identity drift"):
        AtomicStatusReader(foreign_root, source_spec.run_id).snapshot(source_spec.run_id)
    assert foreign.path.read_bytes() == before

    if os.name != "nt":
        real_root = tmp_path / "real"
        real_root.mkdir()
        linked_root = tmp_path / "linked"
        linked_root.symlink_to(real_root, target_is_directory=True)
        with pytest.raises(StoreError, match="symbolic link"):
            AtomicRunStore(linked_root, "task-linked", "writer-linked")


def test_unsupported_and_conflicting_terminal_preserve_exact_authority(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    implement, implement_journal = authorize(
        store, spec, WorkflowStage.IMPLEMENT, "terminal-impl", 1
    )
    implement_effect = complete_provider(implement_journal, implement, "terminal-impl")
    handoff(store, spec, implement, implement_effect, "terminal-review")
    review, review_journal = authorize(store, spec, WorkflowStage.REVIEW, "terminal-review", 1)
    effect = complete_provider(review_journal, review, "terminal-review")
    unsupported = TerminalCommand(
        spec.sha256,
        review.invocation_id,
        review.authorization_sha256,
        "delivery-terminal",
        digest("unsupported-payload"),
        TerminalOutcome.FAILED,
        digest("unsupported-evidence"),
    )
    before = store.path.read_bytes()
    with pytest.raises(StoreError, match="has no owner"):
        store.record_terminal(unsupported, effect)
    assert store.path.read_bytes() == before

    accepted = terminal(store, spec, review, effect, TerminalOutcome.BLOCKED)
    before = store.path.read_bytes()
    result = review_journal.snapshot().result
    assert result is not None
    assert review_journal.record_result(result).result == result
    assert store.path.read_bytes() == before
    conflicting = dataclasses.replace(accepted, outcome=TerminalOutcome.COMPLETED)
    with pytest.raises(StoreError) as caught:
        store.record_terminal(conflicting, effect)
    assert caught.value.outcome is DecisionOutcome.TERMINAL_CONFLICT


def test_exact_local_stop_is_single_writer_idempotent_and_blocks_mutation(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    initial = AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    command = StopCommand(spec.sha256, spec.run_id, initial.sequence)

    decision = store.record_stop(command)
    assert decision.outcome is DecisionOutcome.SAFE_CONTINUE
    stopped = AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert stopped.stopped is True
    assert stopped.terminal is None
    assert stopped.outcome is DecisionOutcome.OWNER_DECISION_REQUIRED
    assert stopped.first_blocker == "run is locally stopped"

    before = files(tmp_path)
    replay = store.record_stop(command)
    assert replay.outcome is DecisionOutcome.SAFE_IDEMPOTENT_REPLAY
    assert files(tmp_path) == before

    changed = dataclasses.replace(command, expected_sequence=command.expected_sequence + 1)
    with pytest.raises(StoreError, match="stop identity conflicts"):
        store.record_stop(changed)
    with pytest.raises(StoreError, match="illegal after local stop"):
        authorize(store, spec, WorkflowStage.IMPLEMENT, "after-stop", 1)
    assert files(tmp_path) == before


def test_local_stop_denies_ambiguous_process_and_preserves_terminal(tmp_path: Path) -> None:
    store, spec = initialized_store(tmp_path)
    command, journal = authorize(store, spec, WorkflowStage.IMPLEMENT, "ambiguous-stop", 1)
    journal.record_launch_intent(LaunchIntent(command.authorization_sha256, digest("rendered")))
    before = files(tmp_path)
    snapshot = AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    with pytest.raises(StoreError) as caught:
        store.record_stop(StopCommand(spec.sha256, spec.run_id, snapshot.sequence))
    assert caught.value.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert files(tmp_path) == before

    terminal_store, terminal_spec = initialized_store(tmp_path / "terminal")
    review, review_journal = authorize(
        terminal_store, terminal_spec, WorkflowStage.IMPLEMENT, "stop-implement", 1
    )
    effect = complete_provider(review_journal, review, "stop-implement")
    handoff(terminal_store, terminal_spec, review, effect, "stop-review")
    review, review_journal = authorize(
        terminal_store, terminal_spec, WorkflowStage.REVIEW, "stop-review", 1
    )
    effect = complete_provider(review_journal, review, "stop-review")
    terminal(terminal_store, terminal_spec, review, effect)
    final = AtomicStatusReader(tmp_path / "terminal", terminal_spec.run_id).snapshot(
        terminal_spec.run_id
    )
    terminal_store.record_stop(
        StopCommand(terminal_spec.sha256, terminal_spec.run_id, final.sequence)
    )
    stopped = AtomicStatusReader(tmp_path / "terminal", terminal_spec.run_id).snapshot(
        terminal_spec.run_id
    )
    assert stopped.terminal is TerminalOutcome.COMPLETED
    assert stopped.stopped is True
    assert store.path.read_bytes() == before


def test_authority_symlink_is_never_followed(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("symlink creation is not an unprivileged Windows fixture")
    store, spec = initialized_store(tmp_path)
    target = tmp_path / "foreign-authority.json"
    target.write_bytes(store.path.read_bytes())
    store.path.unlink()
    store.path.symlink_to(target)
    before = target.read_bytes()
    with pytest.raises(StoreError, match="symbolic link"):
        AtomicStatusReader(tmp_path, spec.run_id).snapshot(spec.run_id)
    assert target.read_bytes() == before


@pytest.mark.parametrize("operation", ["status", "journal", "mutation"])
@pytest.mark.parametrize("component_name", ["runtime-v2", "runs", "run-id"])
def test_runtime_path_symlink_denies_every_store_entry(
    tmp_path: Path, operation: str, component_name: str
) -> None:
    if os.name == "nt":
        pytest.skip("symlink creation is not an unprivileged Windows fixture")
    state_root = tmp_path / operation
    store, spec = initialized_store(state_root)
    _, journal = authorize(store, spec, WorkflowStage.IMPLEMENT, f"linked-{operation}", 1)
    components = {
        "runtime-v2": store.state_root / "runtime-v2",
        "runs": store.run_dir.parent,
        "run-id": store.run_dir,
    }
    component = components[component_name]
    target = tmp_path / f"real-{operation}-{component_name}"
    authority_suffix = store.path.relative_to(component)
    lock_suffix = store.lock_path.relative_to(component)
    component.rename(target)
    component.symlink_to(target, target_is_directory=True)
    authority = target / authority_suffix
    before = authority.read_bytes()

    with pytest.raises(StoreError, match="symbolic link or reparse point") as caught:
        if operation == "status":
            AtomicStatusReader(state_root, spec.run_id).snapshot(spec.run_id)
        elif operation == "journal":
            journal.snapshot()
        else:
            store.initialize(spec)
    assert caught.value.outcome is DecisionOutcome.DENY_BEFORE_PROVIDER
    assert authority.read_bytes() == before
    assert not (target / lock_suffix).exists()
