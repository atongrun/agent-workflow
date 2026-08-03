from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import awf_terminal_recovery as recovery


RUN_ID = "task-dousansi-dogfood-001-empty-state-v4"
EVENT_ID = 118
DELIVERY_ID = "awf:" + "d" * 64
PAYLOAD_SHA256 = "sha256:" + "e" * 64
SOURCE_COMMIT = "8" * 40


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_state(tmp_path: Path, *, phase: str = "pr_tuple_verified") -> Path:
    state_root = tmp_path / "state"
    workspace = state_root / "runs" / "event-118" / "model-workspace"
    workspace.mkdir(parents=True)
    ledger = {
        "format": recovery.LEDGER_FORMAT,
        "run_id": RUN_ID,
        "terminal_state": "",
        "events": [
            {
                "event_id": EVENT_ID,
                "role": "reviewer",
                "delivery_id": DELIVERY_ID,
                "payload_sha256": PAYLOAD_SHA256,
                "status": "authorized",
            }
        ],
    }
    checkpoint = {
        "format": recovery.CHECKPOINT_FORMAT,
        "role": "reviewer",
        "input_delivery_id": DELIVERY_ID,
        "input_payload_sha256": PAYLOAD_SHA256,
        "source_commit": SOURCE_COMMIT,
        "phase": phase,
        "facts": {
            "model_event_id": EVENT_ID,
            "model_workspace": str(workspace),
            "model_manifest_sha256": "sha256:" + "a" * 64,
            "review_report_sha256": "b" * 64,
        },
    }
    write_json(
        state_root / "control-plane" / "runs" / RUN_ID / "ledger.json",
        ledger,
    )
    write_json(recovery.checkpoint_path(state_root, "reviewer", DELIVERY_ID), checkpoint)
    return state_root


def prepare(state_root: Path) -> Path:
    return recovery.prepare_authorization(
        state_root=state_root,
        run_id=RUN_ID,
        event_id=EVENT_ID,
        role="reviewer",
        delivery_id=DELIVERY_ID,
        payload_sha256=PAYLOAD_SHA256,
        source_commit=SOURCE_COMMIT,
        reason="Explicit operator recovery of the same durable delivery",
    )


def test_prepare_binds_exact_ledger_checkpoint_and_workspace(tmp_path: Path):
    state_root = make_state(tmp_path)

    path = prepare(state_root)
    record = json.loads(path.read_text(encoding="utf-8"))

    assert record["status"] == "authorized"
    assert record["attempts"] == 0
    assert record["event_id"] == EVENT_ID
    assert record["delivery_id"] == DELIVERY_ID
    assert record["binding_sha256"] == recovery._binding_sha256(record)
    assert record["evidence"]["checkpoint_phase"] == "pr_tuple_verified"
    assert record["evidence"]["review_report_sha256"] == "b" * 64


@pytest.mark.parametrize("phase", ["model_not_started", "model_started", "model_completed"])
def test_prepare_rejects_checkpoint_before_trusted_import(tmp_path: Path, phase: str):
    state_root = make_state(tmp_path, phase=phase)

    with pytest.raises(recovery.RecoveryDenied, match="safe completed-model boundary"):
        prepare(state_root)


def test_prepare_rejects_mismatched_model_event(tmp_path: Path):
    state_root = make_state(tmp_path)
    path = recovery.checkpoint_path(state_root, "reviewer", DELIVERY_ID)
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["facts"]["model_event_id"] = 119
    write_json(path, checkpoint)

    with pytest.raises(recovery.RecoveryDenied, match="model event"):
        prepare(state_root)


def test_requeue_rejects_authorization_binding_drift(tmp_path: Path):
    state_root = make_state(tmp_path)
    path = prepare(state_root)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["source_commit"] = "9" * 40
    write_json(path, record)

    with pytest.raises(recovery.RecoveryDenied, match="checksum"):
        recovery.execute_requeue(
            state_root=state_root,
            event_id=EVENT_ID,
            config_path=tmp_path / "dispatch.env",
        )


def test_requeue_uses_strict_role_identity_once(monkeypatch, tmp_path: Path):
    state_root = make_state(tmp_path)
    path = prepare(state_root)
    calls = []
    monkeypatch.setattr(
        recovery,
        "load_config",
        lambda _path: {
            "AGENT_BUS_URL": "https://bus.example.test",
            "AWF_REVIEWER_TOKEN": "reviewer-secret",
            "AWF_BUS_BIN": "agent-bus",
        },
    )

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(recovery, "run_command", fake_run)

    first = recovery.execute_requeue(
        state_root=state_root,
        event_id=EVENT_ID,
        config_path=tmp_path / "dispatch.env",
    )
    second = recovery.execute_requeue(
        state_root=state_root,
        event_id=EVENT_ID,
        config_path=tmp_path / "dispatch.env",
    )

    assert first == second == path
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["agent-bus", "requeue", "118"]
    assert kwargs["env"]["AGENT_BUS_AGENT"] == "reviewer"
    assert kwargs["env"]["AGENT_BUS_TOKEN"] == "reviewer-secret"
    assert kwargs["secrets"] == ("reviewer-secret",)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "requeued"


def test_requeue_locks_ambiguous_failure_against_retry(monkeypatch, tmp_path: Path):
    state_root = make_state(tmp_path)
    path = prepare(state_root)
    monkeypatch.setattr(
        recovery,
        "load_config",
        lambda _path: {
            "AGENT_BUS_URL": "https://bus.example.test",
            "AWF_REVIEWER_TOKEN": "reviewer-secret",
        },
    )
    calls = 0

    def fake_run(_argv, **_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=1, stdout="", stderr="failed")

    monkeypatch.setattr(recovery, "run_command", fake_run)

    with pytest.raises(recovery.RecoveryDenied, match="ambiguous"):
        recovery.execute_requeue(
            state_root=state_root,
            event_id=EVENT_ID,
            config_path=tmp_path / "dispatch.env",
        )
    with pytest.raises(recovery.RecoveryDenied, match="no longer executable"):
        recovery.execute_requeue(
            state_root=state_root,
            event_id=EVENT_ID,
            config_path=tmp_path / "dispatch.env",
        )

    assert calls == 1
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "ambiguous"


def test_checkpoint_path_matches_delivery_hash(tmp_path: Path):
    expected = hashlib.sha256(DELIVERY_ID.encode()).hexdigest()

    assert recovery.checkpoint_path(tmp_path, "reviewer", DELIVERY_ID).name == f"{expected}.json"
