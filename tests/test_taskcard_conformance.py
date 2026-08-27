from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.manifest import ManifestError, derive_manifest
from agent_workflow.operations.awf_taskcard import (
    TaskCardContractError,
    reviewer_selection_contract,
)
from agent_workflow.plan_loop import PlanLoopError, validate_taskcard_binding
from agent_workflow.runtime.architect import (
    assemble_architect_taskcard,
    parse_architect_task_semantic,
    persist_architect_taskcard,
)
from agent_workflow.runtime.artifact import (
    ArtifactError,
    compile_implementation_report_path,
    compile_review_report_path,
    compile_run_artifact_contract,
    parse_postflight_contract,
)

ROOT = Path(__file__).parents[1]
TASK_ID = "RC2-P4-CONFORMANCE"
FROZEN_BASE = "a" * 40
CODER = {"tool": "opencode", "model": ""}
REVIEWER = {"tool": "codex", "model": "review/model"}


def assembled_card() -> bytes:
    semantic = parse_architect_task_semantic(
        json.dumps(
            {
                "task_id": TASK_ID,
                "objective": "Prove one TaskCard contract.",
                "scope": ["Add the shared conformance fixture."],
                "change_paths": ["tests/test_taskcard_conformance.py"],
                "constraints": ["Do not broaden authority."],
                "acceptance_criteria": ["Every applicable reader agrees."],
                "verification_commands": [["{python}", "-m", "pytest", "-q"]],
            }
        ).encode("utf-8")
    )
    return assemble_architect_taskcard(
        semantic,
        frozen_base=FROZEN_BASE,
        repository="owner/project",
        base_ref="main",
        coder=CODER,
        reviewer=REVIEWER,
    )


def write_card(repo: Path, raw: bytes) -> Path:
    card = repo / "docs" / "tasks" / f"{TASK_ID}.md"
    card.parent.mkdir(parents=True)
    card.write_bytes(raw)
    return card


def test_trusted_assembled_taskcard_passes_every_applicable_reader(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    card = repo / "docs" / "tasks" / f"{TASK_ID}.md"
    card.parent.mkdir(parents=True)
    raw = assembled_card()

    fact = persist_architect_taskcard(repo=str(repo), destination=str(card), stdout=raw)
    task_id, branch = validate_taskcard_binding(
        raw,
        frozen_base=FROZEN_BASE,
        coder=CODER,
        reviewer=REVIEWER,
    )
    manifest = derive_manifest(card, tool="opencode", model="")
    selection = reviewer_selection_contract(
        raw.decode("utf-8"), fallback_tool="opencode", fallback_model=""
    )
    postflight = parse_postflight_contract(card, "/bound/python")
    run = compile_run_artifact_contract(
        repo=repo,
        card_path=card,
        task_id=TASK_ID,
        implementation_report_path=compile_implementation_report_path(TASK_ID),
        review_report_path=compile_review_report_path(TASK_ID),
    )

    assert fact.path == f"docs/tasks/{TASK_ID}.md"
    assert (task_id, branch) == (TASK_ID, f"agent/{TASK_ID}")
    assert (manifest["task_id"], manifest["branch"]) == (TASK_ID, branch)
    assert manifest["models"] == {
        "tool": "opencode",
        "model": "",
        "reviewer_tool": "codex",
        "reviewer_model": "review/model",
    }
    assert (selection.coder.tool, selection.reviewer.tool) == ("opencode", "codex")
    assert run.allowed_paths == postflight.allowed_paths
    assert postflight.verification_commands[0][0] == "/bound/python"


def test_generated_taskcard_identity_mismatch_fails_every_identity_reader(tmp_path: Path) -> None:
    raw = assembled_card().replace(f"agent/{TASK_ID}".encode(), b"agent/other", 1)
    repo = tmp_path / "repo"
    card = write_card(repo, raw)

    with pytest.raises(ArtifactError, match="identity"):
        persist_architect_taskcard(
            repo=str(repo),
            destination=str(repo / "docs" / "tasks" / "other.md"),
            stdout=raw,
        )
    with pytest.raises(PlanLoopError, match="identity"):
        validate_taskcard_binding(
            raw,
            frozen_base=FROZEN_BASE,
            coder=CODER,
            reviewer=REVIEWER,
        )
    with pytest.raises(ManifestError, match="Task branch"):
        derive_manifest(card, tool="opencode", model="")


def test_generated_taskcard_invalid_task_id_fails_early_identity_readers(tmp_path: Path) -> None:
    raw = assembled_card().replace(
        f"\n{TASK_ID}\n\n## Goal".encode(), b"\nnot a safe id\n\n## Goal", 1
    )
    repo = tmp_path / "repo"
    card = write_card(repo, raw)

    with pytest.raises(ArtifactError, match="missing Task ID"):
        persist_architect_taskcard(
            repo=str(repo),
            destination=str(repo / "docs" / "tasks" / "other.md"),
            stdout=raw,
        )
    with pytest.raises(PlanLoopError, match="identity"):
        validate_taskcard_binding(
            raw,
            frozen_base=FROZEN_BASE,
            coder=CODER,
            reviewer=REVIEWER,
        )
    with pytest.raises(ManifestError, match="usable Task ID"):
        derive_manifest(card, tool="opencode", model="")


def test_postflight_shape_mismatch_fails_persistence_and_runtime_readers(tmp_path: Path) -> None:
    raw = assembled_card().replace(
        b'  "verification_commands":',
        b'  "unexpected": true,\n  "verification_commands":',
        1,
    )
    repo = tmp_path / "repo"
    card = write_card(repo, raw)

    with pytest.raises(ArtifactError, match="unexpected awf-postflight keys"):
        persist_architect_taskcard(
            repo=str(repo),
            destination=str(repo / "docs" / "tasks" / "other.md"),
            stdout=raw,
        )
    with pytest.raises(ArtifactError, match="unexpected awf-postflight keys"):
        parse_postflight_contract(card, "/bound/python")
    with pytest.raises(ArtifactError, match="unexpected awf-postflight keys"):
        compile_run_artifact_contract(
            repo=repo,
            card_path=card,
            task_id=TASK_ID,
            implementation_report_path=compile_implementation_report_path(TASK_ID),
            review_report_path=compile_review_report_path(TASK_ID),
        )


def test_duplicate_machine_blocks_fail_closed_at_early_readers(tmp_path: Path) -> None:
    raw = assembled_card() + b"\n<!-- awf-postflight\n{}\n-->\n"
    repo = tmp_path / "repo"
    card = write_card(repo, raw)

    with pytest.raises(ArtifactError, match="exactly one awf-postflight"):
        persist_architect_taskcard(
            repo=str(repo),
            destination=str(repo / "docs" / "tasks" / "other.md"),
            stdout=raw,
        )
    with pytest.raises(ArtifactError, match="exactly one awf-postflight"):
        parse_postflight_contract(card, "/bound/python")

    duplicate_selection = (
        assembled_card()
        + (
            "\n<!-- awf-reviewer-selection\n"
            + json.dumps({"coder": CODER, "reviewer": REVIEWER})
            + "\n-->\n"
        ).encode()
    )
    with pytest.raises(TaskCardContractError, match="exactly one reviewer selection"):
        reviewer_selection_contract(
            duplicate_selection.decode(), fallback_tool="opencode", fallback_model=""
        )
    duplicate_card = write_card(tmp_path / "duplicate", duplicate_selection)
    with pytest.raises(ManifestError, match="reviewer selection"):
        derive_manifest(duplicate_card, tool="opencode", model="")


def test_explicit_selection_override_conflicts_fail_during_manifest_derivation(
    tmp_path: Path,
) -> None:
    card = write_card(tmp_path / "repo", assembled_card())

    with pytest.raises(ManifestError, match="coder selection conflicts"):
        derive_manifest(card, tool="pi", model="")
    with pytest.raises(ManifestError, match="reviewer selection conflicts"):
        derive_manifest(
            card,
            tool="opencode",
            model="",
            reviewer_tool="pi",
            reviewer_model="review/model",
        )


def test_legacy_tracked_taskcard_keeps_its_historical_branch_shape() -> None:
    card = ROOT / "docs" / "tasks" / "rc2-phase1a-operations-package.md"

    manifest = derive_manifest(card, tool="opencode", model="")

    assert manifest["task_id"] == "RC2-P1A-OPERATIONS-PACKAGE"
    assert manifest["branch"] == "codex/rc2-phase1a-operations-package"
