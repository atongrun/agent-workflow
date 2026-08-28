"""Focused tests for disposable acceptance lifecycle closeout."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from agent_workflow import acceptance_lifecycle, node


def _profile(tmp_path: Path) -> node.NodeProfile:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    source = tmp_path / "profile.json"
    source.write_text(
        json.dumps(
            {
                "format": node.PROFILE_FORMAT,
                "name": "acceptance-coder",
                "role": "coder",
                "repo": str(workspace),
                "tool": "opencode",
                "upstream_repo": "owner/project",
                "head_repo": "contributor/project",
                "state_root": str(tmp_path / "state"),
                "lifecycle": {"mode": "managed", "manager": "auto", "scope": "user"},
            }
        ),
        encoding="utf-8",
    )
    return node.load_profile(str(source))


def test_closeout_preserves_frozen_evidence_and_removes_exact_workspace(
    monkeypatch, tmp_path: Path
):
    profile = _profile(tmp_path)
    manifest = tmp_path / "acceptance.json"
    facts = {
        "running": False,
        "running_observation": {"status": "stopped"},
        "installation": {
            "manager": "systemd",
            "manager_id": "awf-acceptance-coder.service",
            "status": "not_installed",
        },
    }
    monkeypatch.setattr(node, "lifecycle_facts", lambda _profile: facts)
    monkeypatch.setattr(node, "stop", lambda _profile: 0)
    monkeypatch.setattr(node, "uninstall", lambda _profile: pytest.fail("must not uninstall"))

    acceptance_lifecycle.create_manifest(
        manifest, run_id="acceptance-01", profiles=(profile,), workspaces=(profile.repo,)
    )
    result = acceptance_lifecycle.closeout(manifest)

    assert result["state"] == "CLOSED"
    assert (tmp_path / "acceptance.closeout.json").is_file()
    assert not profile.repo.exists()
    assert profile.path.exists()


def test_closeout_fails_closed_before_mutation_for_drift(monkeypatch, tmp_path: Path):
    profile = _profile(tmp_path)
    manifest = tmp_path / "acceptance.json"
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {
            "running": False,
            "running_observation": {"status": "stopped"},
            "installation": {
                "manager": "systemd",
                "manager_id": "awf-acceptance-coder.service",
                "status": "not_installed",
            },
        },
    )
    acceptance_lifecycle.create_manifest(
        manifest, run_id="acceptance-02", profiles=(profile,), workspaces=(profile.repo,)
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["profiles"][0]["profile_sha256"] = "sha256:" + "0" * 64
    manifest.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(node, "stop", lambda _profile: pytest.fail("must not stop"))

    with pytest.raises(acceptance_lifecycle.AcceptanceLifecycleError, match="identity drifted"):
        acceptance_lifecycle.closeout(manifest)
    assert profile.repo.exists()
    assert (tmp_path / "acceptance.closeout.json").is_file()


def test_closeout_uses_exact_installed_snapshot_and_manager_identity(monkeypatch, tmp_path: Path):
    profile = _profile(tmp_path)
    monkeypatch.setattr(node, "_installed_profiles_root", lambda: tmp_path / "installed-profiles")
    snapshot = node._snapshot_path(profile)
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(json.dumps(profile.values), encoding="utf-8")
    installed = node.NodeProfile(
        path=snapshot,
        values=profile.values,
        source_path=profile.path,
        source_aliases=(profile.path,),
    )
    manifest = tmp_path / "acceptance.json"
    state = {"installed": True}

    def installed_profile(_value: str):
        return installed if state["installed"] else None

    def facts(selected: node.NodeProfile):
        assert selected is installed
        return {
            "running_observation": {"status": "stopped"},
            "installation": {
                "manager": "systemd",
                "manager_id": "awf-acceptance-coder.service",
                "status": "current" if state["installed"] else "not_installed",
            },
        }

    monkeypatch.setattr(node, "load_installed_profile", installed_profile)
    monkeypatch.setattr(node, "lifecycle_facts", facts)
    monkeypatch.setattr(node, "stop", lambda selected: 0 if selected is installed else 1)

    def uninstall(selected: node.NodeProfile):
        assert selected is installed
        state["installed"] = False
        snapshot.unlink()
        return 0

    monkeypatch.setattr(node, "uninstall", uninstall)
    acceptance_lifecycle.create_manifest(
        manifest, run_id="acceptance-03", profiles=(profile,), workspaces=(profile.repo,)
    )
    assert json.loads(manifest.read_text(encoding="utf-8"))["profiles"][0]["manager_id"] == (
        "awf-acceptance-coder.service"
    )
    result = acceptance_lifecycle.closeout(manifest)

    assert result["state"] == "CLOSED"
    assert not profile.repo.exists()


def test_frozen_without_validated_never_relaxes_preexisting_workspace_deletion(
    monkeypatch, tmp_path: Path
):
    profile = _profile(tmp_path)
    subprocess.run(["git", "config", "user.name", "Acceptance Test"], check=True, cwd=profile.repo)
    subprocess.run(
        ["git", "config", "user.email", "acceptance@example.invalid"],
        check=True,
        cwd=profile.repo,
    )
    tracked = profile.repo / "tracked.txt"
    tracked.write_text("owner state\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], check=True, cwd=profile.repo)
    subprocess.run(["git", "commit", "-m", "fixture"], check=True, cwd=profile.repo)
    manifest = tmp_path / "acceptance.json"
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {
            "running_observation": {"status": "stopped"},
            "installation": {
                "manager": "systemd",
                "manager_id": "awf-acceptance-coder.service",
                "status": "not_installed",
            },
        },
    )
    acceptance_lifecycle.create_manifest(
        manifest, run_id="acceptance-dirty", profiles=(profile,), workspaces=(profile.repo,)
    )
    tracked.unlink()

    with pytest.raises(
        acceptance_lifecycle.AcceptanceLifecycleError,
        match="workspace status is unavailable",
    ):
        acceptance_lifecycle.closeout(manifest)
    with pytest.raises(
        acceptance_lifecycle.AcceptanceLifecycleError,
        match="workspace status is unavailable",
    ):
        acceptance_lifecycle.closeout(manifest)

    assert profile.repo.exists()
    assert not (tmp_path / "acceptance.validated.json").exists()
    assert (tmp_path / "acceptance.closeout.json").is_file()


def test_explicit_frozen_recovery_accepts_only_mirrored_review_report(monkeypatch, tmp_path: Path):
    profile = _profile(tmp_path)
    project = profile.repo / ".awf" / "project.yaml"
    project.parent.mkdir(parents=True)
    project.write_text("kind: Project\n", encoding="utf-8")
    subprocess.run(["git", "add", str(project)], check=True, cwd=profile.repo)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Acceptance Test",
            "-c",
            "user.email=acceptance@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        cwd=profile.repo,
    )
    report = profile.repo / ".awf" / "artifacts" / "review-report-task.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Review Report\n\nPASS\n", encoding="utf-8")
    oversized = (
        profile.state_root
        / "event-11"
        / "model-workspace-test"
        / ".awf"
        / "artifacts"
        / report.name
    )
    oversized.parent.mkdir(parents=True)
    oversized.write_bytes(b"x" * (acceptance_lifecycle._MAX_RETAINED_REVIEW_REPORT_BYTES + 1))
    mirror = (
        profile.state_root
        / "event-12"
        / "model-workspace-test"
        / ".awf"
        / "artifacts"
        / report.name
    )
    mirror.parent.mkdir(parents=True)
    mirror.write_bytes(report.read_bytes())
    manifest = profile.state_root / "plan-runs" / "plan-1" / "acceptance.json"
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {
            "running_observation": {"status": "stopped"},
            "installation": {
                "manager": "systemd",
                "manager_id": "awf-acceptance-coder.service",
                "status": "not_installed",
            },
        },
    )
    monkeypatch.setattr(node, "stop", lambda _profile: 0)
    monkeypatch.setattr(node, "uninstall", lambda _profile: pytest.fail("must not uninstall"))
    acceptance_lifecycle.create_manifest(
        manifest,
        run_id="acceptance-mirrored-review",
        profiles=(profile,),
        workspaces=(profile.repo,),
    )

    with pytest.raises(
        acceptance_lifecycle.AcceptanceLifecycleError,
        match="workspace status is unavailable",
    ):
        acceptance_lifecycle.closeout(manifest)
    result = acceptance_lifecycle.closeout(manifest, authorize_frozen_recovery=True)

    assert result["state"] == "CLOSED"
    assert mirror.is_file()
    assert not profile.repo.exists()


def test_closeout_resumes_exact_frozen_partial_workspace_removal(monkeypatch, tmp_path: Path):
    profile = _profile(tmp_path)
    subprocess.run(["git", "config", "user.name", "Acceptance Test"], check=True, cwd=profile.repo)
    subprocess.run(
        ["git", "config", "user.email", "acceptance@example.invalid"],
        check=True,
        cwd=profile.repo,
    )
    tracked = profile.repo / "tracked.txt"
    tracked.write_text("evidence\n", encoding="utf-8")
    source = profile.repo / "src"
    source.mkdir()
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt", "src/module.py"], check=True, cwd=profile.repo)
    subprocess.run(["git", "commit", "-m", "fixture"], check=True, cwd=profile.repo)
    manifest = tmp_path / "acceptance.json"
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {
            "running_observation": {"status": "stopped"},
            "installation": {
                "manager": "systemd",
                "manager_id": "awf-acceptance-coder.service",
                "status": "not_installed",
            },
        },
    )
    acceptance_lifecycle.create_manifest(
        manifest, run_id="acceptance-partial", profiles=(profile,), workspaces=(profile.repo,)
    )
    frozen = {
        "format": acceptance_lifecycle.CLOSEOUT_FORMAT,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "state": "FROZEN",
    }
    (tmp_path / "acceptance.closeout.json").write_text(
        json.dumps(frozen, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tracked.unlink()
    cache = profile.repo / "src/__pycache__"
    cache.mkdir(parents=True)
    (cache / "generated.pyc").write_bytes(b"cache")

    result = acceptance_lifecycle.closeout(manifest, authorize_frozen_recovery=True)

    assert result["state"] == "CLOSED"
    assert not profile.repo.exists()
