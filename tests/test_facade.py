"""Focused tests for the payload-blind beginner facade."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_workflow import cli, facade, node
from agent_workflow.manifest import load_compiled_report, load_manifest


def _machine_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (repo / "README.md").write_text("project\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "upstream",
            "https://github.com/owner/project.git",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "fork",
            "https://github.com/contributor/project.git",
        ],
        check=True,
    )
    return repo


def _capabilities(tmp_path: Path, *available: str) -> dict[str, object]:
    config = tmp_path / "dispatch.env"
    return {
        "repo": str(tmp_path / "project"),
        "git": "/tools/git",
        "github": "/tools/gh",
        "config_path": str(config),
        "configured_keys": frozenset(
            {"AGENT_BUS_URL", "AWF_ARCH_TOKEN", "AWF_CODER_TOKEN", "AWF_REVIEWER_TOKEN"}
        ),
        "agent_bus": {
            "executable": "/tools/agent-bus",
            "capabilities": ("agent-bus.listen.on-argv.v1",),
            "provenance_sha256": "sha256:" + "1" * 64,
        },
        "tools": {
            tool: {
                "available": tool in available,
                "executable": f"/tools/{tool}" if tool in available else "",
                "version_sha256": "sha256:" + "2" * 64 if tool in available else "",
            }
            for tool in ("codex", "opencode", "pi")
        },
    }


def test_dependency_discovery_is_capability_first_and_read_only(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = tmp_path / "dispatch.env"
    config = {
        "AGENT_BUS_URL": "https://bus.invalid",
        "AWF_BUS_BIN": "agent-bus",
        "AWF_ARCH_TOKEN": "secret",
        "AWF_PI_BIN": "pi",
    }
    commands: list[list[str]] = []

    class Config:
        class ConfigError(RuntimeError):
            pass

        @staticmethod
        def load_config(path):
            assert path == config_path
            return config

        @staticmethod
        def native_executable(value):
            return value

    def checked(argv, **_kwargs):
        commands.append(argv)
        stdout = str(repo) if "--show-toplevel" in argv else "tool version"
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(facade, "_run_checked", checked)
    monkeypatch.setattr(facade.node, "_operations_modules", lambda: (Config, object()))
    monkeypatch.setattr(
        facade.node,
        "probe_agent_bus_client",
        lambda value: {
            "executable": "/tools/agent-bus",
            "capabilities": ("agent-bus.listen.on-argv.v1",),
            "provenance_sha256": "sha256:" + "1" * 64,
        },
    )
    monkeypatch.setattr(
        facade.shutil,
        "which",
        lambda value: f"/tools/{value}" if value in {"git", "gh", "agent-bus", "pi"} else None,
    )

    facts = facade.discover_machine_capabilities(repo, config_path=config_path)

    assert facts["agent_bus"]["capabilities"] == ("agent-bus.listen.on-argv.v1",)
    assert facts["tools"]["pi"]["available"] is True
    assert facts["tools"]["opencode"]["available"] is False
    assert all("doctor" not in argv for argv in commands)
    assert not facade.default_machine_config_path(repo).exists()


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
        "<!-- awf-postflight\n" + json.dumps(contract, indent=2) + "\n-->\n",
        encoding="utf-8",
    )
    return card


def test_seven_command_synthetic_journey_uses_generated_contracts(monkeypatch, tmp_path: Path):
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
    assert {binding["profile_source"] for binding in contract["bindings"]["profiles"].values()} == {
        "authoring"
    }

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
        lambda profile, run_id, **_kwargs: observed.append(f"status:{profile.role}:{run_id}") or 0,
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


def test_machine_init_reuses_one_opencode_for_distinct_coder_reviewer_workspaces(
    monkeypatch, tmp_path: Path
) -> None:
    repo = _machine_repo(tmp_path)
    config_home = tmp_path / "config" / "awf"
    state_root = tmp_path / "state" / "agent-workflow"
    monkeypatch.setattr(node, "default_config_home", lambda: config_home)
    monkeypatch.setattr(node, "default_state_root", lambda: state_root)

    contract, warnings = facade.initialize_machine(
        repo=repo,
        machine="windows-lab",
        project="sample",
        bindings={
            "coder": ("opencode", "deepseek"),
            "reviewer": ("opencode", "deepseek"),
        },
        capabilities=_capabilities(tmp_path, "opencode"),
        lifecycle="managed",
        upstream_repo="",
        head_repo="",
        upstream_remote="upstream",
        head_remote="fork",
        base_ref="main",
        finding_enabled=False,
        replace=False,
    )

    assert [profile.role for profile in contract.profiles] == ["coder", "reviewer"]
    assert len({profile.repo for profile in contract.profiles}) == 2
    assert {profile.values["tool"] for profile in contract.profiles} == {"opencode"}
    assert len({profile.config_path for profile in contract.profiles}) == 1
    assert {profile.values["model"] for profile in contract.profiles} == {"deepseek"}
    assert all(profile.values["finding_enabled"] is False for profile in contract.profiles)
    assert all(profile.values["enable_preflight"] is True for profile in contract.profiles)
    assert all(profile.repo.is_dir() for profile in contract.profiles)
    assert warnings == (
        "Coder and Reviewer use the same agent tool and model; review independence may be weaker.",
    )
    checked: list[str] = []
    monkeypatch.setattr(
        node,
        "doctor",
        lambda profile, **_kwargs: checked.append(profile.role) or 0,
    )
    assert facade.doctor(repo) == 0
    assert checked == ["coder", "reviewer"]


def test_machine_init_supports_pi_architect_only(monkeypatch, tmp_path: Path) -> None:
    repo = _machine_repo(tmp_path)
    config_home = tmp_path / "config" / "awf"
    monkeypatch.setattr(node, "default_config_home", lambda: config_home)
    monkeypatch.setattr(node, "default_state_root", lambda: tmp_path / "state")

    contract, warnings = facade.initialize_machine(
        repo=repo,
        machine="mac",
        project="sample",
        bindings={"architect": ("pi", "")},
        capabilities=_capabilities(tmp_path, "pi"),
        lifecycle="managed",
        upstream_repo="",
        head_repo="",
        upstream_remote="upstream",
        head_remote="fork",
        base_ref="main",
        finding_enabled=False,
        replace=False,
    )

    assert warnings == ()
    assert len(contract.profiles) == 1
    profile = contract.profiles[0]
    assert profile.role == "architect"
    assert profile.values["tool"] == "pi"
    assert profile.values["model"] == ""
    assert profile.values["on_type"] == "decision:awf-ready-v3"
    assert profile.values["enable_preflight"] is True
    assert node.load_profile(str(profile.path)).digest == profile.digest
    machine = json.loads(contract.config_path.read_text(encoding="utf-8"))
    assert machine["roles"]["architect"]["model_selection"] == {
        "mode": "tool-default",
        "ref": "",
    }


def _activation_profile(tmp_path: Path, role: str) -> node.NodeProfile:
    return node.NodeProfile(
        tmp_path / f"{role}.json",
        {
            "format": node.PROFILE_FORMAT,
            "name": f"machine-{role}",
            "role": role,
            "repo": str((tmp_path / role).resolve()),
            "tool": "pi" if role == "architect" else "opencode",
            "model": "",
            "on_type": "decision:awf-ready-v3" if role == "architect" else f"task:awf-{role}-v3",
            "state_root": str((tmp_path / "state").resolve()),
            "lifecycle": {"mode": "managed", "manager": "auto", "scope": "user"},
            "enable_preflight": True,
        },
    )


def test_activate_machine_starts_each_exact_role_and_waits_for_ready(monkeypatch, tmp_path):
    profiles = (_activation_profile(tmp_path, "coder"), _activation_profile(tmp_path, "reviewer"))
    contract = facade.MachineContract(
        repo=tmp_path,
        config_path=tmp_path / ".awf/machine.json",
        machine="windows",
        project="sample",
        finding_enabled=False,
        profiles=profiles,
    )
    started: list[str] = []
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {"installed": True, "running": False, "installation": {}},
    )
    monkeypatch.setattr(node, "load_installed_profile", lambda _value: None)
    monkeypatch.setattr(node, "start", lambda profile: started.append(profile.role) or 0)
    monkeypatch.setattr(node, "doctor", lambda _profile, **_kwargs: 0)
    monkeypatch.setattr(node, "_local_readiness", lambda _profile: object())
    monkeypatch.setattr(
        node,
        "doctor_report",
        lambda profile, *_args, **_kwargs: {
            "profile": {"role": profile.role},
            "configured": True,
            "installed": True,
            "running": True,
            "connected": True,
            "listener": {"lease_bound": True},
        },
    )

    ready = facade.activate_machine(contract, readiness_timeout_seconds=1)

    assert started == ["coder", "reviewer"]
    assert [item["profile"]["role"] for item in ready] == ["coder", "reviewer"]


def test_activate_machine_rolls_back_only_newly_started_exact_listeners(monkeypatch, tmp_path):
    profiles = (_activation_profile(tmp_path, "coder"), _activation_profile(tmp_path, "reviewer"))
    contract = facade.MachineContract(
        repo=tmp_path,
        config_path=tmp_path / ".awf/machine.json",
        machine="windows",
        project="sample",
        finding_enabled=False,
        profiles=profiles,
    )
    stopped: list[str] = []
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda _profile: {"installed": True, "running": False, "installation": {}},
    )
    monkeypatch.setattr(node, "load_installed_profile", lambda _value: None)

    def start(profile):
        if profile.role == "reviewer":
            raise node.NodeError("reviewer listener failed")
        return 0

    monkeypatch.setattr(node, "start", start)
    monkeypatch.setattr(node, "doctor", lambda _profile, **_kwargs: 0)
    monkeypatch.setattr(node, "_local_readiness", lambda _profile: object())
    monkeypatch.setattr(
        node,
        "doctor_report",
        lambda profile, *_args, **_kwargs: {
            "profile": {"role": profile.role},
            "configured": True,
            "installed": True,
            "running": True,
            "connected": True,
            "listener": {"lease_bound": True},
        },
    )
    monkeypatch.setattr(node, "stop", lambda profile: stopped.append(profile.role) or 0)

    with pytest.raises(facade.FacadeError, match="configuration was preserved"):
        facade.activate_machine(contract, readiness_timeout_seconds=1)

    assert stopped == ["coder"]


def test_three_role_machine_has_static_supported_bindings_and_distinct_workspaces(
    monkeypatch, tmp_path: Path
) -> None:
    repo = _machine_repo(tmp_path)
    monkeypatch.setattr(node, "default_config_home", lambda: tmp_path / "config" / "awf")
    monkeypatch.setattr(node, "default_state_root", lambda: tmp_path / "state")

    contract, _warnings = facade.initialize_machine(
        repo=repo,
        machine="one-machine",
        project="sample",
        bindings={
            "architect": ("pi", "architect-model"),
            "coder": ("opencode", "execution-model"),
            "reviewer": ("opencode", "execution-model"),
        },
        capabilities=_capabilities(tmp_path, "pi", "opencode"),
        lifecycle="managed",
        upstream_repo="",
        head_repo="",
        upstream_remote="upstream",
        head_remote="fork",
        base_ref="main",
        finding_enabled=False,
        replace=False,
    )

    assert [profile.role for profile in contract.profiles] == list(facade.ROLE_ORDER)
    assert len({profile.name for profile in contract.profiles}) == 3
    assert len({profile.repo for profile in contract.profiles}) == 3


def test_machine_init_rejects_unsupported_binding_before_mutation(
    monkeypatch, tmp_path: Path
) -> None:
    repo = _machine_repo(tmp_path)
    config_home = tmp_path / "config" / "awf"
    monkeypatch.setattr(node, "default_config_home", lambda: config_home)
    monkeypatch.setattr(node, "default_state_root", lambda: tmp_path / "state")

    with pytest.raises(facade.FacadeError, match="architect does not support"):
        facade.initialize_machine(
            repo=repo,
            machine="mac",
            project="sample",
            bindings={"architect": ("opencode", "model")},
            capabilities=_capabilities(tmp_path, "opencode"),
            lifecycle="managed",
            upstream_repo="",
            head_repo="",
            upstream_remote="upstream",
            head_remote="fork",
            base_ref="main",
            finding_enabled=False,
            replace=False,
        )

    assert not facade.default_machine_config_path(repo).exists()
    assert not (config_home / "profiles").exists()
    assert not (config_home / "workspaces").exists()


def test_machine_init_rejects_invalid_explicit_model_ref_before_mutation(
    monkeypatch, tmp_path: Path
) -> None:
    repo = _machine_repo(tmp_path)
    config_home = tmp_path / "config" / "awf"
    monkeypatch.setattr(node, "default_config_home", lambda: config_home)
    monkeypatch.setattr(node, "default_state_root", lambda: tmp_path / "state")

    with pytest.raises(facade.FacadeError, match="tool-native token"):
        facade.initialize_machine(
            repo=repo,
            machine="mac",
            project="sample",
            bindings={"architect": ("pi", " provider/model ")},
            capabilities=_capabilities(tmp_path, "pi"),
            lifecycle="managed",
            upstream_repo="",
            head_repo="",
            upstream_remote="upstream",
            head_remote="fork",
            base_ref="main",
            finding_enabled=False,
            replace=False,
        )

    assert not facade.default_machine_config_path(repo).exists()
    assert not (config_home / "profiles").exists()


def test_machine_config_rejects_profile_binding_drift(monkeypatch, tmp_path: Path) -> None:
    repo = _machine_repo(tmp_path)
    config_home = tmp_path / "config" / "awf"
    monkeypatch.setattr(node, "default_config_home", lambda: config_home)
    monkeypatch.setattr(node, "default_state_root", lambda: tmp_path / "state")
    contract, _warnings = facade.initialize_machine(
        repo=repo,
        machine="mac",
        project="sample",
        bindings={"architect": ("pi", "model")},
        capabilities=_capabilities(tmp_path, "pi"),
        lifecycle="managed",
        upstream_repo="",
        head_repo="",
        upstream_remote="upstream",
        head_remote="fork",
        base_ref="main",
        finding_enabled=False,
        replace=False,
    )
    profile_path = contract.profiles[0].path
    values = json.loads(profile_path.read_text(encoding="utf-8"))
    values["model"] = "drifted-model"
    profile_path.write_text(json.dumps(values), encoding="utf-8")

    with pytest.raises(facade.FacadeError, match="profile binding drifted"):
        facade.load_machine(repo)


@pytest.mark.parametrize("replace_existing", [False, True])
@pytest.mark.parametrize("failure_target", ["reviewer-profile", "machine-config"])
def test_machine_init_file_batch_rolls_back_fresh_and_replace_failures(
    monkeypatch,
    tmp_path: Path,
    replace_existing: bool,
    failure_target: str,
) -> None:
    repo = _machine_repo(tmp_path)
    config_home = tmp_path / "config" / "awf"
    monkeypatch.setattr(node, "default_config_home", lambda: config_home)
    monkeypatch.setattr(node, "default_state_root", lambda: tmp_path / "state")
    capabilities = _capabilities(tmp_path, "opencode")
    common = {
        "repo": repo,
        "machine": "lab",
        "project": "sample",
        "capabilities": capabilities,
        "lifecycle": "managed",
        "upstream_repo": "",
        "head_repo": "",
        "upstream_remote": "upstream",
        "head_remote": "fork",
        "base_ref": "main",
        "finding_enabled": False,
    }
    if replace_existing:
        facade.initialize_machine(
            **common,
            bindings={
                "coder": ("opencode", "old-model"),
                "reviewer": ("opencode", "old-model"),
            },
            replace=False,
        )

    profile_paths = {
        role: config_home / "profiles" / f"sample-lab-{role}.json" for role in ("coder", "reviewer")
    }
    machine_path = facade.default_machine_config_path(repo)
    watched = (*profile_paths.values(), machine_path)
    before = {path: path.read_bytes() for path in watched if path.exists()}
    target = profile_paths["reviewer"] if failure_target == "reviewer-profile" else machine_path
    real_replace = facade._replace_file

    def fail_selected_stage(source: Path, destination: Path) -> None:
        if Path(destination) == target and "backup-" not in Path(source).name:
            raise OSError("injected batch commit failure")
        real_replace(Path(source), Path(destination))

    monkeypatch.setattr(facade, "_replace_file", fail_selected_stage)

    with pytest.raises(facade.FacadeError, match="rolled back"):
        facade.initialize_machine(
            **common,
            bindings={
                "coder": ("opencode", "new-model"),
                "reviewer": ("opencode", "new-model"),
            },
            replace=replace_existing,
        )

    if replace_existing:
        assert {path: path.read_bytes() for path in watched} == before
        restored = facade.load_machine(repo)
        assert {profile.values["model"] for profile in restored.profiles} == {"old-model"}
    else:
        assert all(not path.exists() for path in watched)
        assert not (config_home / "workspaces" / "sample-lab-coder").exists()
        assert not (config_home / "workspaces" / "sample-lab-reviewer").exists()
    assert not list((config_home / "profiles").glob("awf-init-profiles-*"))
    assert not list(machine_path.parent.glob(".machine.json.stage-*"))
    assert not list(machine_path.parent.glob(".machine.json.backup-*"))
