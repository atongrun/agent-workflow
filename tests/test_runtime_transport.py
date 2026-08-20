from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_workflow.runtime import (
    CommandEnvelope,
    DecisionOutcome,
    LocalTransportBoundary,
    ResultEnvelope,
    TransportError,
    WorkflowStage,
)
from scripts.awf_delivery import canonical_payload_sha256, make_delivery_id

SHA0 = "0" * 64
SHA1 = "1" * 64


def command(payload: object | None = None) -> CommandEnvelope:
    return CommandEnvelope.create(
        run_id="task-runtime-v2-transport",
        task_id="runtime-v2-transport",
        run_spec_sha256=SHA0,
        source_role="architect",
        target_role="coder",
        route="task:awf-impl-v3",
        source_invocation_id="owner-dispatch",
        source_authorization_sha256=SHA1,
        target_invocation_id="invoke-implement",
        payload={"message": "实现\n并验证", "sequence": 1} if payload is None else payload,
    )


def result(cause: CommandEnvelope | None = None, payload: object | None = None) -> ResultEnvelope:
    cause = cause or command()
    return ResultEnvelope.create(
        run_id=cause.run_id,
        task_id=cause.task_id,
        run_spec_sha256=cause.run_spec_sha256,
        source_role="coder",
        target_role="reviewer",
        route="task:awf-review-v3",
        source_invocation_id=cause.target_invocation_id,
        source_authorization_sha256=SHA0,
        target_invocation_id="invoke-review",
        causation_delivery_id=cause.delivery_id,
        payload={"artifact_sha256": SHA1, "accepted": True} if payload is None else payload,
    )


def replace_raw(envelope: CommandEnvelope | ResultEnvelope, **changes: object) -> bytes:
    value = json.loads(envelope.encode())
    value.update(changes)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_command_and_result_are_canonical_immutable_and_stably_causal() -> None:
    first = command()
    downstream = result(first)

    assert CommandEnvelope.decode(first.encode()) == first
    assert ResultEnvelope.decode(downstream.encode()) == downstream
    assert first.encode() == CommandEnvelope.decode(first.encode()).encode()
    assert downstream.encode() == ResultEnvelope.decode(downstream.encode()).encode()
    assert downstream.causation_delivery_id == first.delivery_id
    assert first.delivery_id.startswith("awfv2:")
    assert downstream.delivery_id.startswith("awfv2:")

    mutable_copy = first.payload
    mutable_copy["sequence"] = 9
    assert first.payload["sequence"] == 1


def test_payload_hash_matches_current_canonical_oracle_but_delivery_version_is_distinct() -> None:
    envelope = command({"branch": "codex/example", "unicode": "豆三思"})

    assert envelope.payload_sha256 == canonical_payload_sha256(envelope.payload)
    assert envelope.delivery_id != make_delivery_id(
        envelope.source_role,
        envelope.route,
        envelope.payload_sha256,
        1,
    )
    assert envelope.delivery_id.startswith("awfv2:")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("run_id", "task-foreign"),
        ("task_id", "foreign"),
        ("run_spec_sha256", SHA1),
        ("source_role", "reviewer"),
        ("target_role", "reviewer"),
        ("route", "task:awf-rework-v3"),
        ("source_invocation_id", "owner-foreign"),
        ("source_authorization_sha256", SHA0),
        ("target_invocation_id", "invoke-foreign"),
        ("payload_sha256", "sha256:" + SHA1),
        ("delivery_id", "awfv2:" + SHA1),
    ],
)
def test_each_command_identity_drift_fails_closed(field: str, replacement: object) -> None:
    with pytest.raises(TransportError) as failure:
        CommandEnvelope.decode(replace_raw(command(), **{field: replacement}))
    assert failure.value.outcome is DecisionOutcome.DENY_BEFORE_PROVIDER


def test_payload_or_causation_mutation_changes_result_identity() -> None:
    cause = command()
    original = result(cause, {"value": 1})
    changed_payload = result(cause, {"value": 2})
    changed_cause = ResultEnvelope.create(
        run_id=original.run_id,
        task_id=original.task_id,
        run_spec_sha256=original.run_spec_sha256,
        source_role=original.source_role,
        target_role=original.target_role,
        route=original.route,
        source_invocation_id=original.source_invocation_id,
        source_authorization_sha256=original.source_authorization_sha256,
        target_invocation_id=original.target_invocation_id,
        causation_delivery_id="awfv2:" + SHA1,
        payload=original.payload,
    )

    assert original.delivery_id != changed_payload.delivery_id
    assert original.delivery_id != changed_cause.delivery_id


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b"{}",
        b'{"kind":"command","kind":"command"}',
        b'{"value":NaN}',
        b'{"value":1.5}',
        b" " + command().encode(),
        command().encode() + b"\n",
    ],
)
def test_malformed_duplicate_noncanonical_and_noninteger_json_is_denied(raw: bytes) -> None:
    with pytest.raises(TransportError):
        CommandEnvelope.decode(raw)


def test_deep_oversized_and_non_json_payloads_are_denied() -> None:
    deep: object = {"leaf": True}
    for _ in range(40):
        deep = {"next": deep}

    for payload in (deep, {"large": "x" * (256 * 1024)}, {"float": 1.5}, ["array"]):
        with pytest.raises(TransportError):
            command(payload)


class FakeApplication:
    def __init__(self, root: Path) -> None:
        self.state_root = root
        self.writer_id = "writer-transport-fixture"
        self.calls: list[object] = []

    def run(self, _run_spec: object, request: object) -> object:
        self.calls.append(request)
        return request


def fake_spec() -> SimpleNamespace:
    return SimpleNamespace(
        run_id="task-runtime-v2-transport",
        task_id="runtime-v2-transport",
        sha256=SHA0,
        implement_route="task:awf-impl-v3",
        review_route="task:awf-review-v3",
        rework_route="task:awf-rework-v3",
    )


def fake_request(envelope: CommandEnvelope) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_id=envelope.target_invocation_id,
        stage=WorkflowStage.IMPLEMENT,
        delivery_id=envelope.delivery_id,
        payload_sha256=envelope.payload_sha256.removeprefix("sha256:"),
    )


def test_local_receive_gate_calls_application_once_only_after_exact_command(tmp_path: Path) -> None:
    application = FakeApplication(tmp_path)
    boundary = LocalTransportBoundary(application)
    envelope = command()
    request = fake_request(envelope)

    assert boundary.accept(fake_spec(), request, envelope.encode()) is request
    assert application.calls == [request]


@pytest.mark.parametrize(
    "mutation",
    [
        {"delivery_id": "awfv2:" + SHA1},
        {"payload_sha256": SHA1},
        {"invocation_id": "invoke-foreign"},
        {"stage": WorkflowStage.REVIEW},
    ],
)
def test_local_receive_mismatch_never_calls_application_or_writes_state(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    application = FakeApplication(tmp_path)
    boundary = LocalTransportBoundary(application)
    envelope = command()
    request = fake_request(envelope)
    for key, value in mutation.items():
        setattr(request, key, value)

    before = list(tmp_path.rglob("*"))
    with pytest.raises(TransportError):
        boundary.accept(fake_spec(), request, envelope.encode())
    assert application.calls == []
    assert list(tmp_path.rglob("*")) == before


def test_top_level_schema_is_stage_blind_and_exact() -> None:
    command_keys = set(json.loads(command().encode()))
    result_keys = set(json.loads(result().encode()))
    prohibited = {
        "stage",
        "attempt",
        "rework_budget",
        "terminal",
        "state_root",
        "checkpoint",
        "outbox",
        "inbox",
        "ack",
        "provider",
    }

    assert not command_keys & prohibited
    assert result_keys == command_keys | {"causation_delivery_id"}
    with pytest.raises(TransportError):
        CommandEnvelope.decode(replace_raw(command(), stage="implement"))
