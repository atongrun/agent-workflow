from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_workflow.manifest import ManifestError, derive_manifest, load_manifest, write_manifest


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
