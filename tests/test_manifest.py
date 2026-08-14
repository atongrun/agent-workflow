from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_workflow.manifest import (
    ManifestError,
    compile_run_contract,
    default_manifest_path,
    derive_manifest,
    load_manifest,
    resolve_manifest_card,
    write_manifest,
)


def compiled_inputs(tmp_path: Path, route_version: str = "v3") -> dict:
    task_id = "DOGFOOD-001"
    run_manifest = derive_manifest(
        card(tmp_path / "card.md", task_id),
        branch=f"feature/{task_id}",
        tool="opencode",
        model="coder/model",
        reviewer_tool="pi",
        reviewer_model="reviewer/model",
        upstream_repo="owner/repo",
        head_repo="owner/fork",
    )
    suffix = "" if route_version == "v1" else f"-{route_version}"
    run_manifest["routes"] = {
        "implement": f"task:awf-impl{suffix}",
        "review": f"task:awf-review{suffix}",
        "rework": f"task:awf-rework{suffix}",
    }
    state_root = tmp_path / "state"

    def profile(role: str, tool: str, model: str, route: str) -> dict:
        values = {
            "format": "awf.node-profile.v1",
            "name": f"test-{role}",
            "role": role,
            "repo": str(tmp_path),
            "tool": tool,
            "model": model,
            "state_root": str(state_root),
            "on_type": route,
            "upstream_repo": "owner/repo",
            "head_repo": "owner/fork",
        }
        return {
            "role": role,
            "path": tmp_path / f"{role}.json",
            "sha256": f"sha256:{role}",
            "state_root": state_root,
            "values": values,
        }

    return {
        "repo": tmp_path,
        "run_id": f"task-{task_id}",
        "run_manifest": run_manifest,
        "run_manifest_path": tmp_path / "run-manifest.json",
        "authority_manifest": {"format": "awf.authority-manifest.v1"},
        "authority_manifest_path": tmp_path / "authority.json",
        "authority_binding": {"sha256": "sha256:authority"},
        "taskcard_binding": {
            "task_id": task_id,
            "implementation_report_path": run_manifest["report_paths"]["implementation"],
            "review_report_path": run_manifest["report_paths"]["review"],
        },
        "state_root": state_root,
        "state_root_sha256": "sha256:state",
        "profiles": [
            profile("coder", "opencode", "coder/model", run_manifest["routes"]["implement"]),
            profile("reviewer", "pi", "reviewer/model", run_manifest["routes"]["review"]),
        ],
        "compiler_version": "test",
    }


def card(path: Path, task_id: str = "DOGFOOD-001") -> Path:
    path.write_text(
        f"## Task ID\n\n{task_id}\n\n## Working Context\n\n"
        "- **Task branch**: `feature/dogfood-001`\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.skipif(os.name == "nt", reason="POSIX owner-only contract")
def test_manifest_derives_and_round_trips_owner_only(tmp_path: Path):
    values = derive_manifest(card(tmp_path / "card.md"))
    destination = write_manifest(tmp_path / ".awf" / "run-manifest.json", values)
    assert destination.stat().st_mode & 0o077 == 0
    assert load_manifest(destination)["task_id"] == "DOGFOOD-001"


def test_manifest_rejects_unknown_fields_and_never_accepts_secrets(tmp_path: Path):
    values = derive_manifest(card(tmp_path / "card.md"))
    values["secret"] = "must-not-be-accepted"
    with pytest.raises(ManifestError, match="unknown"):
        write_manifest(tmp_path / "manifest.json", values)


def test_manifest_replace_is_explicit(tmp_path: Path):
    values = derive_manifest(card(tmp_path / "card.md"))
    path = write_manifest(tmp_path / "manifest.json", values)
    with pytest.raises(ManifestError, match="already exists"):
        write_manifest(path, values, replace=False)


def test_manifest_resolves_repository_default_and_bound_card(tmp_path: Path):
    task_card = card(tmp_path / "card.md")
    values = derive_manifest(task_card)

    assert default_manifest_path(tmp_path) == tmp_path / ".awf" / "run-manifest.json"
    assert resolve_manifest_card(values, tmp_path) == task_card.resolve()


def test_manifest_derives_independent_coder_and_reviewer_models(tmp_path: Path):
    values = derive_manifest(
        card(tmp_path / "card.md"),
        tool="opencode",
        model="coder/model",
        reviewer_tool="pi",
        reviewer_model="reviewer/model",
    )

    assert values["models"] == {
        "tool": "opencode",
        "model": "coder/model",
        "reviewer_tool": "pi",
        "reviewer_model": "reviewer/model",
    }


def test_manifest_defaults_reviewer_selection_to_legacy_coder_selection(tmp_path: Path):
    values = derive_manifest(
        card(tmp_path / "card.md"),
        tool="opencode",
        model="legacy/model",
    )

    assert values["models"]["reviewer_tool"] == "opencode"
    assert values["models"]["reviewer_model"] == "legacy/model"


def test_manifest_rejects_partial_reviewer_selection(tmp_path: Path):
    values = derive_manifest(card(tmp_path / "card.md"), tool="opencode")
    del values["models"]["reviewer_model"]

    with pytest.raises(ManifestError, match="reviewer selection"):
        write_manifest(tmp_path / "manifest.json", values)


@pytest.mark.parametrize("route_version", ["v1", "v2", "v3"])
def test_run_contract_reports_explicit_v1_v3_compatibility(tmp_path: Path, route_version: str):
    report = compile_run_contract(**compiled_inputs(tmp_path, route_version))

    assert report["format"] == "awf.run-contract-report.v1"
    assert report["compatibility"] == {
        "status": "compatible",
        "run_manifest": "awf.run-manifest.v1",
        "route_versions": {
            "implement": route_version,
            "review": route_version,
            "rework": route_version,
        },
    }
    assert report["contract_sha256"].startswith("sha256:")


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("run", "run id"),
        ("artifact", "ImplementationReport"),
        ("tool", "tool/model"),
        ("state-root", "state root"),
        ("repository", "repository"),
        ("route", "route"),
    ],
)
def test_run_contract_table_rejects_cross_binding_drift(tmp_path: Path, drift: str, message: str):
    inputs = compiled_inputs(tmp_path)
    if drift == "run":
        inputs["run_id"] = "task-other"
    elif drift == "artifact":
        inputs["taskcard_binding"]["implementation_report_path"] = "wrong.md"
    elif drift == "tool":
        inputs["profiles"][0]["values"]["tool"] = "codex"
    elif drift == "state-root":
        inputs["profiles"][0]["state_root"] = tmp_path / "other-state"
    elif drift == "repository":
        inputs["profiles"][0]["values"]["repo"] = str(tmp_path / "other-repo")
    else:
        inputs["profiles"][0]["values"]["on_type"] = "task:awf-review-v3"

    with pytest.raises(ManifestError, match=message):
        compile_run_contract(**inputs)
