from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from agent_workflow.runtime import (
    AtomicRunStore,
    AtomicStatusReader,
    AuthorizationCommand,
    DecisionOutcome,
    HandoffCommand,
    JournalAuthorization,
    LaunchIntent,
    OutgoingIntent,
    OutgoingIntentDispatcher,
    ProcessObservation,
    ProviderResult,
    ProviderSelection,
    ResultEnvelope,
    RunSpec,
    StoreError,
    TransportSendObservation,
    TransportSendReceipt,
    TransportSendState,
    ValidationEffect,
    WorkflowStage,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def make_spec(root: Path) -> RunSpec:
    state_root_sha256 = hashlib.sha256(
        ("awf-state-root-v1\0" + str(root.resolve())).encode()
    ).hexdigest()
    return RunSpec(
        run_id="task-runtime-v2-rts-041",
        task_id="runtime-v2-rts-041",
        task_card="docs/tasks/runtime-v2-rts-041-outgoing-intent-adapter.md",
        task_card_sha256=digest("task-card"),
        repository="atongrun/agent-workflow",
        frozen_base="a" * 40,
        task_branch="codex/runtime-v2-rts-041-outgoing-intent-adapter",
        state_root_sha256=state_root_sha256,
        semantic_contract_sha256=digest("frozen-contract"),
        coder=ProviderSelection("opencode", "coder/model"),
        reviewer=ProviderSelection("pi", "reviewer/model"),
        implement_attempts=1,
        review_attempts=2,
        rework_budget=1,
        implement_route="task:awf-impl-v3",
        review_route="task:awf-review-v3",
        rework_route="task:awf-rework-v3",
        implementation_report=".awf/artifacts/impl-rts-041.md",
        review_report=".awf/artifacts/review-rts-041.md",
    )


def prepared_store(root: Path) -> tuple[AtomicRunStore, RunSpec, OutgoingIntent]:
    spec = make_spec(root)
    store = AtomicRunStore(root, spec.run_id, "writer-rts-041")
    store.initialize(spec)
    command = AuthorizationCommand(
        spec.sha256,
        "invoke-implement",
        digest("authorization"),
        WorkflowStage.IMPLEMENT,
        "coder",
        1,
        "awfv2:" + digest("incoming-delivery"),
        digest("incoming-payload"),
    )
    authorization = JournalAuthorization(
        spec.sha256,
        command.invocation_id,
        command.authorization_sha256,
        digest("invocation-spec"),
    )
    store.authorize(command, authorization)
    journal = store.journal(command.invocation_id)
    journal.record_launch_intent(LaunchIntent(command.authorization_sha256, digest("rendered")))
    process = ProcessObservation(command.authorization_sha256, digest("process"))
    journal.record_process_observation(process)
    result = ProviderResult(
        command.authorization_sha256,
        process.process_identity_sha256,
        0,
        digest("result"),
    )
    journal.record_result(result)
    effect = ValidationEffect(
        command.authorization_sha256,
        result.result_sha256,
        digest("artifact"),
        digest("effect"),
    )
    envelope = ResultEnvelope.create(
        run_id=spec.run_id,
        task_id=spec.task_id,
        run_spec_sha256=spec.sha256,
        source_role="coder",
        target_role="reviewer",
        route=spec.review_route,
        source_invocation_id=command.invocation_id,
        source_authorization_sha256=command.authorization_sha256,
        target_invocation_id="invoke-review",
        causation_delivery_id=command.delivery_id,
        payload={"effect_sha256": effect.effect_sha256},
    )
    intent = OutgoingIntent.from_envelope(envelope)
    handoff = HandoffCommand(
        spec.sha256,
        command.invocation_id,
        command.authorization_sha256,
        envelope.delivery_id,
        envelope.payload_sha256.removeprefix("sha256:"),
        spec.review_route,
        "reviewer",
    )
    store.record_handoff(handoff, effect, intent)
    return store, spec, intent


def authority_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class FakeSender:
    def __init__(
        self,
        store: AtomicRunStore,
        result: TransportSendReceipt | Exception | BaseException,
    ) -> None:
        self.store, self.result = store, result
        self.calls: list[tuple[str, str, str, bytes]] = []

    def send(
        self,
        *,
        delivery_id: str,
        target_role: str,
        route: str,
        envelope: bytes,
    ) -> TransportSendReceipt:
        status = self.store.outgoing_status()
        assert status.state is TransportSendState.ATTEMPTING
        assert status.observation is not None
        self.calls.append((delivery_id, target_role, route, envelope))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_outgoing_intent_is_exact_canonical_result_envelope() -> None:
    envelope = ResultEnvelope.create(
        run_id="task-runtime-v2-rts-041",
        task_id="runtime-v2-rts-041",
        run_spec_sha256=digest("spec"),
        source_role="coder",
        target_role="reviewer",
        route="task:awf-review-v3",
        source_invocation_id="invoke-implement",
        source_authorization_sha256=digest("authorization"),
        target_invocation_id="invoke-review",
        causation_delivery_id="awfv2:" + digest("cause"),
        payload={"unicode": "边界", "value": 1},
    )
    intent = OutgoingIntent.from_envelope(envelope)

    assert intent.envelope_bytes == envelope.encode()
    assert intent.envelope.encode() == envelope.encode()
    with pytest.raises(ValueError, match="SHA-256"):
        dataclasses.replace(intent, envelope_sha256=digest("drift"))
    with pytest.raises(ValueError):
        dataclasses.replace(intent, envelope_json=intent.envelope_json + " ")
    with pytest.raises(ValueError, match="canonical result envelope"):
        dataclasses.replace(intent, target_role="coder")


def test_intent_and_effect_commit_atomically_and_status_is_read_only(tmp_path: Path) -> None:
    store, spec, intent = prepared_store(tmp_path)
    before = authority_files(tmp_path)

    assert store.pending_outgoing() == intent
    status = store.outgoing_status()
    reader_status = AtomicStatusReader(tmp_path, spec.run_id).outgoing(spec.run_id)
    assert status == reader_status
    assert status.state is TransportSendState.PREPARED
    assert status.outcome is DecisionOutcome.SAFE_CONTINUE
    assert status.next_action == "send the exact bound intent once"
    assert authority_files(tmp_path) == before
    assert set(before) == {f"runtime-v2/runs/{spec.run_id}/authority.json"}


def test_success_records_attempt_before_send_and_exact_replay_sends_zero(tmp_path: Path) -> None:
    store, _spec, intent = prepared_store(tmp_path)
    sender = FakeSender(store, TransportSendReceipt(True, digest("sender-success")))
    dispatcher = OutgoingIntentDispatcher(store, sender)

    decision = dispatcher.dispatch()

    assert decision.outcome is DecisionOutcome.SAFE_CONTINUE
    assert sender.calls == [
        (intent.delivery_id, intent.target_role, intent.route, intent.envelope_bytes)
    ]
    status = store.outgoing_status()
    assert status.state is TransportSendState.SENT
    assert status.next_action == "none"
    before = authority_files(tmp_path)
    replay = dispatcher.dispatch()
    assert replay.outcome is DecisionOutcome.SAFE_IDEMPOTENT_REPLAY
    assert len(sender.calls) == 1
    assert authority_files(tmp_path) == before


@pytest.mark.parametrize(
    "result",
    [
        TransportSendReceipt(False, digest("sender-false")),
        TransportSendReceipt(None, digest("sender-unknown")),
        RuntimeError("redacted transport failure"),
    ],
)
def test_false_unknown_and_exception_are_ambiguous_without_resend(
    tmp_path: Path,
    result: TransportSendReceipt | Exception,
) -> None:
    store, _spec, _intent = prepared_store(tmp_path)
    sender = FakeSender(store, result)
    dispatcher = OutgoingIntentDispatcher(store, sender)

    decision = dispatcher.dispatch()

    assert decision.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert decision.owner == "owner"
    assert store.outgoing_status().state is TransportSendState.AMBIGUOUS
    before = authority_files(tmp_path)
    replay = dispatcher.dispatch()
    assert replay.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert len(sender.calls) == 1
    assert authority_files(tmp_path) == before


class SimulatedCrash(BaseException):
    pass


def test_crash_visible_attempting_never_reenters_sender(tmp_path: Path) -> None:
    store, _spec, _intent = prepared_store(tmp_path)
    sender = FakeSender(store, SimulatedCrash())
    dispatcher = OutgoingIntentDispatcher(store, sender)

    with pytest.raises(SimulatedCrash):
        dispatcher.dispatch()

    assert store.outgoing_status().state is TransportSendState.ATTEMPTING
    before = authority_files(tmp_path)
    replay = dispatcher.dispatch()
    assert replay.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert len(sender.calls) == 1
    assert authority_files(tmp_path) == before


def test_conflicting_observation_and_corrupt_intent_fail_closed(tmp_path: Path) -> None:
    store, spec, intent = prepared_store(tmp_path)
    attempting = TransportSendObservation(
        spec.sha256,
        intent.delivery_id,
        intent.envelope_sha256,
        "send-attempt",
        TransportSendState.ATTEMPTING,
        digest("attempting"),
    )
    store.record_send_observation(attempting)
    before = authority_files(tmp_path)
    conflicting = dataclasses.replace(attempting, attempt_id="send-conflict")
    with pytest.raises(StoreError, match="conflicts"):
        store.record_send_observation(conflicting)
    assert authority_files(tmp_path) == before

    authority = json.loads(store.path.read_text(encoding="utf-8"))
    handoff = next(event for event in authority["payload"]["events"] if event["kind"] == "handoff")
    handoff["intent"]["envelope_json"] += " "
    authority["checksum"] = hashlib.sha256(canonical(authority["payload"])).hexdigest()
    store.path.write_bytes(canonical(authority) + b"\n")
    corrupt = store.path.read_bytes()
    with pytest.raises(StoreError):
        AtomicStatusReader(tmp_path, spec.run_id).outgoing(spec.run_id)
    assert store.path.read_bytes() == corrupt


def test_outgoing_adapter_has_no_transport_or_authority_expansion() -> None:
    root = Path(__file__).parents[1]
    outgoing = (root / "src/agent_workflow/runtime/outgoing.py").read_text(encoding="utf-8")
    store = (root / "src/agent_workflow/runtime/store.py").read_text(encoding="utf-8")
    forbidden = (
        "socket.",
        "requests.",
        "httpx.",
        "subprocess.",
        "agent-bus",
        "ack(",
        "checkpoint/",
        "outbox/",
        "inbox/",
    )

    assert not any(token in outgoing.lower() for token in forbidden)
    assert "WorkflowStage" not in outgoing
    assert "AtomicRunStore" not in outgoing
    assert "transport_send" in store
