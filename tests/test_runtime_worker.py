from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from agent_workflow.runtime import CommandEnvelope, FreshRunSpec, ModelSelection, WorkflowStage
from agent_workflow.runtime.worker import (
    WorkerError,
    command_authorization_sha256,
    prepare_worker_command,
)
from tests.test_runtime_single_card import fresh_spec


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def command(
    tmp_path: Path, *, explicit_ref: str = "coder/model"
) -> tuple[CommandEnvelope, FreshRunSpec]:
    spec = fresh_spec(tmp_path)
    coder = dataclasses.replace(
        spec.coder,
        model_selection=ModelSelection("explicit", explicit_ref),
    )
    spec = dataclasses.replace(spec, coder=coder)
    invocation_id = "invoke-coder-1"
    input_text = "implement the frozen TaskCard"
    authorization = command_authorization_sha256(
        run_spec_sha256=spec.sha256,
        invocation_id=invocation_id,
        stage=WorkflowStage.IMPLEMENT,
        attempt=1,
        expected_commit=spec.frozen_base,
        input_text=input_text,
        role="coder",
    )
    envelope = CommandEnvelope.create(
        run_id=spec.run_id,
        task_id=spec.task_id,
        run_spec_sha256=spec.sha256,
        source_role="architect",
        target_role="coder",
        route=spec.implement_route,
        source_invocation_id="owner-dispatch",
        source_authorization_sha256=digest("owner-dispatch"),
        target_invocation_id=invocation_id,
        payload={
            "run_spec": spec.to_mapping(),
            "authorization_sha256": authorization,
            "stage": "implement",
            "attempt": 1,
            "input_text": input_text,
            "expected_commit": spec.frozen_base,
            "provider_executable": "/usr/bin/true",
            "provider_args": ["attach-input"],
        },
    )
    return envelope, spec


def test_worker_reserves_exact_command_before_provider_and_replays_identity(tmp_path: Path) -> None:
    envelope, spec = command(tmp_path)

    first = prepare_worker_command(
        envelope_bytes=envelope.encode(),
        local_binding=spec.coder,
        state_root=tmp_path / "state",
    )
    second = prepare_worker_command(
        envelope_bytes=envelope.encode(),
        local_binding=spec.coder,
        state_root=tmp_path / "state",
    )

    assert first.authorization_sha256 == second.authorization_sha256
    assert first.journal_path == second.journal_path
    journal = json.loads(first.journal_path.read_text(encoding="utf-8"))
    assert journal["launch_intent"] is None
    assert journal["result_envelope"] is None


def test_worker_denies_model_mode_or_ref_drift_before_provider(tmp_path: Path) -> None:
    envelope, spec = command(tmp_path)
    default_binding = dataclasses.replace(
        spec.coder,
        model_selection=ModelSelection("tool-default", ""),
    )

    with pytest.raises(WorkerError, match="binding drifted"):
        prepare_worker_command(
            envelope_bytes=envelope.encode(),
            local_binding=default_binding,
            state_root=tmp_path / "state",
        )


def test_worker_denies_authorization_or_durable_command_conflict(tmp_path: Path) -> None:
    envelope, spec = command(tmp_path)
    prepared = prepare_worker_command(
        envelope_bytes=envelope.encode(),
        local_binding=spec.coder,
        state_root=tmp_path / "state",
    )
    journal = json.loads(prepared.journal_path.read_text(encoding="utf-8"))
    journal["command_sha256"] = "0" * 64
    prepared.journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with pytest.raises(WorkerError, match="conflicts"):
        prepare_worker_command(
            envelope_bytes=envelope.encode(),
            local_binding=spec.coder,
            state_root=tmp_path / "state",
        )

    invalid = CommandEnvelope.create(
        run_id=envelope.run_id,
        task_id=envelope.task_id,
        run_spec_sha256=envelope.run_spec_sha256,
        source_role=envelope.source_role,
        target_role=envelope.target_role,
        route=envelope.route,
        source_invocation_id=envelope.source_invocation_id,
        source_authorization_sha256=envelope.source_authorization_sha256,
        target_invocation_id=envelope.target_invocation_id,
        payload={**envelope.payload, "authorization_sha256": "0" * 64},
    )
    with pytest.raises(WorkerError, match="authorization identity drifted"):
        prepare_worker_command(
            envelope_bytes=invalid.encode(),
            local_binding=spec.coder,
            state_root=tmp_path / "other-state",
        )
