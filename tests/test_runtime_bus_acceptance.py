from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_workflow.runtime import (
    AtomicRunStore,
    CommandEnvelope,
    DecisionOutcome,
    OutgoingIntentDispatcher,
    ResultEnvelope,
    TransportSendState,
)
from tests.fixtures import runtime_v2_bus_acceptance as acceptance

REPO = Path(__file__).resolve().parents[1]
SCOPE = "rts042-focused-001"
CANDIDATE = "a" * 40


def fake_bus(tmp_path: Path) -> Path:
    path = (tmp_path / "agent-bus").resolve()
    path.write_text("acceptance-only fake executable\n", encoding="utf-8")
    return path


def result_fixture(tmp_path: Path):
    root = tmp_path / "state"
    binding = acceptance.state_root_binding(root)
    spec = acceptance.make_spec(REPO, SCOPE, CANDIDATE, binding)
    command = acceptance.make_command(spec, SCOPE)
    output = acceptance.expected_child_sha256(SCOPE, "windows-command")
    store, intent = acceptance.prepare_result_store(
        root, spec, command, output, acceptance.digest("child-process")
    )
    return root, spec, command, store, intent


def test_command_and_result_envelopes_are_canonical_and_causal(tmp_path: Path) -> None:
    root = tmp_path / "state"
    spec = acceptance.make_spec(REPO, SCOPE, CANDIDATE, acceptance.state_root_binding(root))
    command = acceptance.make_command(spec, SCOPE)
    noncanonical = json.dumps(json.loads(command.encode()), ensure_ascii=False, indent=2)
    decoded = CommandEnvelope.decode(acceptance.canonical_payload(noncanonical))

    assert decoded.encode() == command.encode()
    values = acceptance.transition_values(
        spec,
        command,
        acceptance.expected_child_sha256(SCOPE, "windows-command"),
    )
    result = values[-1]
    assert ResultEnvelope.decode(result.encode()) == result
    assert result.causation_delivery_id == command.delivery_id
    assert result.source_role == "coder"
    assert result.target_role == "reviewer"
    assert result.route == spec.review_route

    drifted = json.loads(command.encode())
    drifted["target_invocation_id"] = "foreign-invocation"
    with pytest.raises(ValueError, match="delivery identity"):
        CommandEnvelope.decode(acceptance.canonical_payload(json.dumps(drifted)))
    with pytest.raises(acceptance.AcceptanceError, match="duplicate key"):
        acceptance.canonical_payload('{"a":1,"a":2}')


def test_real_sender_port_records_attempt_before_call_and_sent_replay_is_zero(
    tmp_path: Path,
) -> None:
    _root, _spec, _command, store, intent = result_fixture(tmp_path)
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        assert store.outgoing_status().state is TransportSendState.ATTEMPTING
        assert kwargs["shell"] is False
        assert kwargs["stdin"] is subprocess.DEVNULL
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"untrusted output", b"")

    sender = acceptance.AgentBusSender(
        fake_bus(tmp_path),
        "coder",
        runner=runner,
        environment={"AGENT_BUS_AGENT": "coder", "AGENT_BUS_TOKEN": "not-persisted"},
    )
    dispatcher = OutgoingIntentDispatcher(store, sender)

    decision = dispatcher.dispatch()

    assert decision.outcome is DecisionOutcome.SAFE_CONTINUE
    assert store.outgoing_status().state is TransportSendState.SENT
    assert len(calls) == 1
    assert calls[0][-1].encode() == intent.envelope_bytes
    assert calls[0][calls[0].index("--type") + 1] == intent.route
    replay = dispatcher.dispatch()
    assert replay.outcome is DecisionOutcome.SAFE_IDEMPOTENT_REPLAY
    assert len(calls) == 1
    authority = tmp_path / "state" / "runtime-v2" / "runs" / _spec.run_id / "authority.json"
    assert b"not-persisted" not in authority.read_bytes()
    assert b"untrusted output" not in authority.read_bytes()


@pytest.mark.parametrize("failure", [1, "timeout"])
def test_real_sender_failure_is_ambiguous_and_never_replayed(
    tmp_path: Path, failure: int | str
) -> None:
    _root, _spec, _command, store, _intent = result_fixture(tmp_path)
    calls = 0

    def runner(argv, **_kwargs):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 20, output=b"secret")
        return subprocess.CompletedProcess(argv, failure, b"secret", b"private")

    sender = acceptance.AgentBusSender(
        fake_bus(tmp_path),
        "coder",
        runner=runner,
        environment={"AGENT_BUS_AGENT": "coder", "AGENT_BUS_TOKEN": "not-persisted"},
    )
    dispatcher = OutgoingIntentDispatcher(store, sender)

    decision = dispatcher.dispatch()

    assert decision.outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert store.outgoing_status().state is TransportSendState.AMBIGUOUS
    assert dispatcher.dispatch().outcome is DecisionOutcome.AMBIGUOUS_NO_REPLAY
    assert calls == 1


def test_two_real_handler_children_complete_exact_command_and_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD^{commit}"], text=True
    ).strip()
    root = tmp_path / "state"
    evidence = tmp_path / "evidence"
    binding = acceptance.state_root_binding(root)
    bus = fake_bus(tmp_path)
    sent: list[bytes] = []

    class LocalSender(acceptance.AgentBusSender):
        def __init__(self, bus_bin: Path, source_role: str) -> None:
            def runner(argv, **_kwargs):
                sent.append(argv[-1].encode())
                return subprocess.CompletedProcess(argv, 0, b"ok", b"")

            super().__init__(
                bus_bin,
                source_role,
                runner=runner,
                environment={"AGENT_BUS_AGENT": source_role, "AGENT_BUS_TOKEN": "ephemeral"},
            )

    monkeypatch.setattr(acceptance, "AgentBusSender", LocalSender)
    spec = acceptance.make_spec(REPO, SCOPE, candidate, binding)
    command = acceptance.make_command(spec, SCOPE)
    command_args = SimpleNamespace(
        scope=SCOPE,
        repo=REPO,
        candidate_sha=candidate,
        state_root_binding=binding,
        state_root=root,
        evidence_dir=evidence,
        bus_bin=bus,
        event_id="101",
        event_type=spec.implement_route,
        payload=json.dumps(json.loads(command.encode()), ensure_ascii=False, indent=2),
    )

    monkeypatch.setenv("AGENT_BUS_AGENT", "coder")
    acceptance.handle_command(command_args)

    target = json.loads((evidence / f"{SCOPE}-target.json").read_text())
    assert target["command_event_id"] == 101
    assert target["send_state"] == "sent"
    assert target["child_return_code"] == 0
    assert len(sent) == 1
    result = ResultEnvelope.decode(sent[0])
    assert result.causation_delivery_id == command.delivery_id

    result_args = SimpleNamespace(
        scope=SCOPE,
        repo=REPO,
        candidate_sha=candidate,
        state_root_binding=binding,
        evidence_dir=evidence,
        event_id="102",
        event_type=spec.review_route,
        payload=json.dumps(json.loads(result.encode()), ensure_ascii=False, indent=2),
    )
    monkeypatch.setenv("AGENT_BUS_AGENT", "reviewer")
    acceptance.handle_result(result_args)

    source = json.loads((evidence / f"{SCOPE}-source.json").read_text())
    assert source["result_event_id"] == 102
    assert source["command_delivery_id"] == command.delivery_id
    assert source["result_delivery_id"] == result.delivery_id
    assert source["child_return_code"] == 0
    store = AtomicRunStore(root, spec.run_id, f"writer-{spec.task_id}")
    assert store.outgoing_status().state is TransportSendState.SENT


def test_foreign_result_denies_before_result_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD^{commit}"], text=True
    ).strip()
    root = tmp_path / "state"
    spec = acceptance.make_spec(REPO, SCOPE, candidate, acceptance.state_root_binding(root))
    command = acceptance.make_command(spec, SCOPE)
    result = acceptance.transition_values(
        spec,
        command,
        acceptance.expected_child_sha256(SCOPE, "windows-command"),
    )[-1]
    raw = json.loads(result.encode())
    raw["causation_delivery_id"] = "awfv2:" + hashlib.sha256(b"foreign").hexdigest()
    calls = 0

    def forbidden_child(_scope: str, _phase: str):
        nonlocal calls
        calls += 1
        raise AssertionError("child must not start")

    monkeypatch.setattr(acceptance, "run_child", forbidden_child)
    monkeypatch.setenv("AGENT_BUS_AGENT", "reviewer")
    args = SimpleNamespace(
        scope=SCOPE,
        repo=REPO,
        candidate_sha=candidate,
        state_root_binding=spec.state_root_sha256,
        evidence_dir=tmp_path / "evidence",
        event_id="102",
        event_type=spec.review_route,
        payload=json.dumps(raw),
    )

    with pytest.raises(ValueError, match="delivery identity"):
        acceptance.handle_result(args)
    assert calls == 0


def test_acceptance_fixture_has_no_production_or_ack_mutation_surface() -> None:
    path = REPO / "tests/fixtures/runtime_v2_bus_acceptance.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert not imports & {"socket", "requests", "httpx", "scripts.awf_role", "scripts.awf_listen"}
    assert "--on " not in source
    assert "--ack" not in source
    assert "requeue" not in source
    assert "retry" not in source
    assert "shell=True" not in source
    assert "subprocess.Popen" in source
    assert "OutgoingIntentDispatcher" in source
    assert set(acceptance.parser()._subparsers._group_actions[0].choices) == {
        "send-command",
        "handle-command",
        "handle-result",
    }
