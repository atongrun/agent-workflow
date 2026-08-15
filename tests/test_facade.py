"""Focused tests for the payload-blind beginner facade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow import cli, facade, node
from agent_workflow.manifest import load_compiled_report, load_manifest


def _card(repo: Path) -> Path:
    card = repo / "card.md"
    contract = {
        "allowed_paths": [
            ".awf/artifacts/impl-report-SYNTH-001.md",
            ".awf/artifacts/review-report-SYNTH-001.md",
        ],
        "verification_commands": [["{python}", "-m", "compileall", "src"]],
    }
    card.write_text(
        "# Synthetic facade journey\n\n"
        "## Task ID\n\nSYNTH-001\n\n"
        "- **Task branch**: `codex/SYNTH-001`\n\n"
        "<!-- awf-postflight\n"
        + json.dumps(contract, indent=2)
        + "\n-->\n",
        encoding="utf-8",
    )
    return card


def test_seven_command_synthetic_journey_uses_generated_contracts(
    monkeypatch, tmp_path: Path
):
    repo = tmp_path / "project"
    repo.mkdir()
    card = _card(repo)
    config_home = tmp_path / "config" / "awf"
    state_root = tmp_path / "state" / "agent-workflow"
    monkeypatch.setattr(node, "default_config_home", lambda: config_home)
    monkeypatch.setattr(node, "default_state_root", lambda: state_root)

    commands = 0
    assert (
        cli.main(
            [
                "init",
                "--repo",
                str(repo),
                "--card",
                str(card),
                "--machine",
                "mac-lab",
                "--project",
                "sample",
                "--coder-runtime",
                "codex",
                "--coder-model",
                "coder-model",
                "--reviewer-runtime",
                "pi",
                "--reviewer-model",
                "reviewer-model",
                "--upstream-repo",
                "owner/project",
                "--head-repo",
                "contributor/project",
            ]
        )
        == 0
    )
    commands += 1

    profiles = tuple(
        node.load_profile(str(config_home / "profiles" / f"sample-mac-lab-{role}.json"))
        for role in ("coder", "reviewer")
    )
    manifest = load_manifest(repo / ".awf" / "run-manifest.json")
    contract = load_compiled_report(repo / ".awf" / "run-contract.json")
    assert manifest["state_root"] == str(state_root.resolve())
    assert manifest["models"] == {
        "tool": "codex",
        "model": "coder-model",
        "reviewer_tool": "pi",
        "reviewer_model": "reviewer-model",
    }
    assert {profile.name for profile in profiles} == {
        "sample-mac-lab-coder",
        "sample-mac-lab-reviewer",
    }
    assert {
        binding["profile_source"]
        for binding in contract["bindings"]["profiles"].values()
    } == {"authoring"}

    observed: list[str] = []
    monkeypatch.setattr(
        node,
        "doctor",
        lambda profile, **_kwargs: observed.append(f"doctor:{profile.role}") or 0,
    )
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {"installed": True, "installation": {"status": "current"}},
    )
    monkeypatch.setattr(
        node,
        "start",
        lambda profile, **_kwargs: observed.append(f"start:{profile.role}") or 0,
    )
    monkeypatch.setattr(
        node,
        "status",
        lambda profile, run_id, **_kwargs: observed.append(
            f"status:{profile.role}:{run_id}"
        )
        or 0,
    )
    monkeypatch.setattr(
        node,
        "stop",
        lambda profile: observed.append(f"stop:{profile.role}") or 0,
    )

    assert cli.main(["doctor", "--repo", str(repo), "--explain"]) == 0
    commands += 1
    assert cli.main(["start", "--repo", str(repo)]) == 0
    commands += 1
    installed_profiles = tuple(
        node.NodeProfile(
            path=config_home / "installed-profiles" / f"{profile.role}.json",
            values=profile.values,
            source_path=profile.path,
        )
        for profile in profiles
    )
    monkeypatch.setattr(
        node,
        "load_installed_profile",
        lambda value: (
            installed_profiles[0]
            if "coder" in value
            else installed_profiles[1]
            if "reviewer" in value
            else None
        ),
    )
    assert cli.main(["run", "check", "--repo", str(repo)]) == 0
    commands += 1
    monkeypatch.setattr(
        cli,
        "cmd_run",
        lambda args: observed.append(f"run:{Path(args.card).resolve()}") or 0,
    )
    assert cli.main(["run", "--repo", str(repo)]) == 0
    commands += 1
    explicit: list[bool] = []
    monkeypatch.setattr(
        cli,
        "cmd_run",
        lambda args: explicit.append(getattr(args, "facade", False)) or 0,
    )
    assert cli.main(["run", "--repo", str(repo), "--card", str(card)]) == 0
    assert explicit == [True]
    assert cli.main(["status", "--repo", str(repo), "--explain"]) == 0
    commands += 1
    assert cli.main(["stop", "--repo", str(repo)]) == 0
    commands += 1

    assert commands == 7
    assert f"run:{card.resolve()}" in observed
    assert observed.count("doctor:coder") == 1
    assert observed.count("doctor:reviewer") == 1
    assert observed.count("start:coder") == 1
    assert observed.count("start:reviewer") == 1
    assert observed.count("stop:coder") == 1
    assert observed.count("stop:reviewer") == 1


def test_start_and_drain_gate_every_profile_before_mutation(monkeypatch, tmp_path: Path):
    state_root = tmp_path / "state"
    repo = tmp_path / "repo"
    profiles = tuple(
        node.NodeProfile(
            path=tmp_path / f"{role}.json",
            values={
                "format": node.PROFILE_FORMAT,
                "name": f"project-machine-{role}",
                "role": role,
                "repo": str(repo),
                "tool": "codex",
                "state_root": str(state_root),
                "lifecycle": {"mode": "managed", "manager": "auto", "scope": "user"},
            },
        )
        for role in ("coder", "reviewer")
    )
    project = facade.ProjectContract(
        repo=repo,
        manifest_path=repo / ".awf/run-manifest.json",
        contract_path=repo / ".awf/run-contract.json",
        manifest={},
        contract={"identity": {"run_id": "task-SYNTH-001"}},
        profiles=profiles,
    )
    monkeypatch.setattr(facade, "load_project", lambda _repo: project)
    mutations: list[str] = []
    monkeypatch.setattr(
        node,
        "install",
        lambda profile: mutations.append(f"install:{profile.role}"),
    )
    monkeypatch.setattr(
        node,
        "start",
        lambda profile, **_kwargs: mutations.append(f"start:{profile.role}"),
    )
    monkeypatch.setattr(node, "stop", lambda profile: mutations.append(f"stop:{profile.role}"))

    facts = iter(
        [
            {"installed": False, "installation": {"status": "not_installed"}},
            {"installed": None, "installation": {"status": "stale"}},
        ]
    )
    monkeypatch.setattr(node, "lifecycle_facts", lambda _profile: next(facts))
    with pytest.raises(facade.FacadeError, match="installation evidence is stale"):
        facade.start(repo)
    assert mutations == []

    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {"installed": False, "installation": {"status": "not_installed"}},
    )
    monkeypatch.setattr(
        node,
        "load_installed_profile",
        lambda value: profiles[0] if "coder" in value else profiles[1],
    )
    assert facade.start(repo) == 0
    assert mutations == [
        "install:coder",
        "start:coder",
        "install:reviewer",
        "start:reviewer",
    ]

    mutations.clear()
    queues = iter(
        [
            {"status": "observed", "pending": 0},
            {"status": "observed", "pending": 1},
        ]
    )
    monkeypatch.setattr(facade.factual_status, "_queue", lambda _profile: next(queues))
    with pytest.raises(facade.FacadeError, match="pending deliveries=1"):
        facade.drain(repo)
    assert mutations == []

    monkeypatch.setattr(
        facade.factual_status,
        "_queue",
        lambda _profile: {"status": "observed", "pending": 0},
    )
    assert facade.drain(repo) == 0
    assert mutations == ["stop:coder", "stop:reviewer"]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("read-only facade command reached a forbidden mutation")

    monkeypatch.setattr(node, "install", forbidden)
    monkeypatch.setattr(node, "start", forbidden)
    monkeypatch.setattr(node, "stop", forbidden)
    monkeypatch.setattr(cli, "cmd_dispatch", forbidden)
    monkeypatch.setattr(cli, "cmd_resume", forbidden)
    monkeypatch.setattr(cli, "cmd_feedback", forbidden)
    read_only: list[str] = []
    monkeypatch.setattr(
        node,
        "doctor",
        lambda profile, **_kwargs: read_only.append(f"doctor:{profile.role}") or 0,
    )
    monkeypatch.setattr(
        node,
        "status",
        lambda profile, _run_id, **_kwargs: read_only.append(f"status:{profile.role}") or 0,
    )
    assert facade.doctor(repo, explain=True) == 0
    assert facade.check(repo, lambda current: current.contract) is project
    assert facade.status(repo, explain=True) == 0
    assert read_only == [
        "doctor:coder",
        "doctor:reviewer",
        "status:coder",
        "status:reviewer",
    ]

    legacy: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli,
        "cmd_status",
        lambda args: legacy.append((args.run, args.state_root)) or 0,
    )
    assert (
        cli.main(
            [
                "status",
                "--run",
                "task-legacy",
                "--state-root",
                str(state_root),
            ]
        )
        == 0
    )
    assert legacy == [("task-legacy", str(state_root))]
