"""Phase 0 regressions for the machine-owned implementation artifact contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.operations import (
    awf_artifact_contract,  # noqa: E402
    awf_dispatch,  # noqa: E402
    awf_listen,  # noqa: E402
    awf_role,  # noqa: E402
)


def write_card(path: Path, allowed_paths: list[str]) -> None:
    contract = {
        "allowed_paths": allowed_paths,
        "verification_commands": [["{python}", "-c", "raise SystemExit(0)"]],
    }
    path.write_text(
        "# Controlled card\n\n<!-- awf-postflight\n" + json.dumps(contract, indent=2) + "\n-->\n",
        encoding="utf-8",
    )


def test_dispatch_compiles_one_report_path_used_by_listener_executor_and_postflight(tmp_path):
    task_id = "phase0-contract-one"
    report_path = awf_artifact_contract.compile_implementation_report_path(task_id)
    review_path = awf_artifact_contract.compile_review_report_path(task_id)
    card = tmp_path / "task.md"
    write_card(card, ["result.txt", report_path, review_path])

    stage_contract = awf_artifact_contract.compile_stage_artifact_contract(
        card_path=card,
        task_id=task_id,
        requested_report_path="",
    )
    payload = awf_dispatch.build_payload(
        event_type="task:awf-impl-v3",
        task_id=task_id,
        branch=f"agent/{task_id}",
        card="task.md",
        commit="a" * 40,
        tool="opencode",
        model="provider/model",
        report=stage_contract.implementation_report_path,
        review_report=f".awf/artifacts/review-report-{task_id}.md",
        provenance=None,
    )
    handler = awf_listen.build_handler("python", "awf_role.py", "coder")

    assert payload["report"] == report_path
    assert "--report {payload.report}" in handler
    awf_artifact_contract.validate_stage_artifact_contract(
        card_path=card,
        task_id=task_id,
        required_report_path=str(payload["report"]),
    )
    assert (
        awf_role.resolve_repo_file(str(tmp_path), str(payload["report"]), "ImplementationReport")
        == tmp_path / report_path
    )
    run_contract = awf_artifact_contract.compile_run_artifact_contract(
        repo=tmp_path,
        card_path=card,
        task_id=task_id,
        implementation_report_path=report_path,
        review_report_path=review_path,
    )
    assert run_contract.taskcard_path == "task.md"
    assert run_contract.review_report_path == review_path


def test_owner_report_path_survives_a_distinct_delivery_task_id(tmp_path):
    owner_task_id = "DOUSANSI-RC2-DOGFOOD-001"
    delivery_task_id = "dousansi-rc2-dogfood-001-first-bean-20260809"
    report_path = awf_artifact_contract.compile_implementation_report_path(owner_task_id)
    card = tmp_path / "task.md"
    write_card(card, ["src/bean.ts", report_path])

    stage_contract = awf_artifact_contract.compile_stage_artifact_contract(
        card_path=card,
        task_id=delivery_task_id,
        requested_report_path=report_path,
    )
    received_contract = awf_artifact_contract.validate_stage_artifact_contract(
        card_path=card,
        task_id=delivery_task_id,
        required_report_path=report_path,
    )

    assert stage_contract.implementation_report_path == report_path
    assert received_contract == stage_contract


def test_v4_taskcard_and_v5_delivery_fail_before_model_with_explicit_fields(tmp_path):
    v4_path = awf_artifact_contract.compile_implementation_report_path("task-v4")
    v5_path = awf_artifact_contract.compile_implementation_report_path("task-v5")
    card = tmp_path / "task.md"
    write_card(card, ["result.txt", v4_path])

    with pytest.raises(
        awf_artifact_contract.ArtifactContractError,
        match=r"TaskCard allowed_paths.*delivery\.report",
    ):
        awf_artifact_contract.validate_stage_artifact_contract(
            card_path=card,
            task_id="task-v5",
            required_report_path=v5_path,
        )


def test_taskcard_cannot_declare_a_second_implementation_report_source(tmp_path):
    expected = awf_artifact_contract.compile_implementation_report_path("task")
    card = tmp_path / "task.md"
    write_card(card, ["result.txt", expected, "reports/impl-report-task.md"])

    with pytest.raises(
        awf_artifact_contract.ArtifactContractError,
        match=r"TaskCard allowed_paths.*delivery\.report",
    ):
        awf_artifact_contract.validate_stage_artifact_contract(
            card_path=card,
            task_id="task",
            required_report_path=expected,
        )


@pytest.mark.parametrize(
    "requested",
    [
        "../impl.md",
        r".awf\artifacts\impl-report-task.md",
        "C:/work/impl.md",
        "reports/impl-report-task.md",
    ],
)
def test_report_path_must_be_compiled_under_artifact_root(tmp_path, requested):
    expected = awf_artifact_contract.compile_implementation_report_path("task")
    card = tmp_path / "task.md"
    write_card(card, [expected])

    with pytest.raises(awf_artifact_contract.ArtifactContractError):
        awf_artifact_contract.compile_stage_artifact_contract(
            card_path=card,
            task_id="task",
            requested_report_path=requested,
        )
