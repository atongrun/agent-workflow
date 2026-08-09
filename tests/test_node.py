"""Tests for the thin local node lifecycle surface."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_workflow import cli, node


def profile_values(tmp_path: Path, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "format": "awf.node-profile.v1",
        "name": "reviewer-mac",
        "role": "reviewer",
        "repo": str((tmp_path / "repo").resolve()),
        "tool": "pi",
        "upstream_repo": "owner/project",
        "head_repo": "contributor/project",
        "config": str((tmp_path / "dispatch.env").resolve()),
        "state_root": str((tmp_path / "state").resolve()),
    }
    values.update(changes)
    return values


def write_profile(tmp_path: Path, **changes: object) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile_values(tmp_path, **changes)), encoding="utf-8")
    return path


def test_named_profile_uses_the_cross_platform_config_home(monkeypatch, tmp_path: Path):
    config_home = tmp_path / "config"
    profile = config_home / "awf" / "profiles" / "reviewer-mac.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps(profile_values(tmp_path)), encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("APPDATA", str(config_home))

    loaded = node.load_profile("reviewer-mac")

    assert loaded.path == profile
    assert loaded.role == "reviewer"


@pytest.mark.parametrize("secret", ["AGENT_BUS_URL", "AWF_REVIEWER_TOKEN"])
def test_profile_schema_rejects_secrets(tmp_path: Path, secret: str):
    path = write_profile(tmp_path, **{secret: "must-not-live-here"})

    with pytest.raises(node.NodeError, match="Additional properties"):
        node.load_profile(str(path))


def test_profile_rejects_relative_repo(tmp_path: Path):
    path = write_profile(tmp_path, repo="relative/repo")

    with pytest.raises(node.NodeError, match="repo must be an absolute path"):
        node.load_profile(str(path))


@pytest.mark.parametrize("field", ["state_root", "log_file"])
def test_node_write_paths_cannot_dirty_the_role_repository(monkeypatch, tmp_path: Path, field: str):
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    target = repo / ("state" if field == "state_root" else "listener.log")
    path = write_profile(tmp_path, repo=str(repo), **{field: str(target)})
    monkeypatch.setattr(
        node.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("listener must not start"),
    )

    assert node.run("start", str(path)) == 1
    assert not target.exists()
    state_root = target if field == "state_root" else (tmp_path / "state").resolve()
    assert not (state_root / "nodes" / "reviewer-mac" / "process.json").exists()


def test_profile_preserves_pi_reviewer_only_boundary(tmp_path: Path):
    path = write_profile(tmp_path, role="coder", tool="pi")

    with pytest.raises(node.NodeError, match="reviewer-only"):
        node.load_profile(str(path))


def test_architect_profile_makes_the_no_model_boundary_explicit(tmp_path: Path):
    valid = write_profile(tmp_path, role="architect", tool="none")
    assert node.load_profile(str(valid)).role == "architect"

    invalid = write_profile(tmp_path, role="architect", tool="codex")
    with pytest.raises(node.NodeError, match="tool must be none"):
        node.load_profile(str(invalid))


def test_start_writes_bound_process_record_and_uses_packaged_listener(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.repo.mkdir()
    monkeypatch.setattr(node, "_load_runtime_config", lambda value: ({}, value.repo))
    monkeypatch.setattr(node, "_process_record", lambda value: None)
    observed: dict[str, object] = {}

    class Process:
        pid = 4321

        @staticmethod
        def poll():
            return None

    def popen(argv, **kwargs):
        observed.update({"argv": argv, **kwargs})
        return Process()

    monkeypatch.setattr(node.subprocess, "Popen", popen)
    monkeypatch.setattr(node, "_wait_for_listener_lease", lambda *args: None)

    assert node.start(profile) == 0
    record = json.loads(profile.process_path.read_text(encoding="utf-8"))
    assert record["pid"] == 4321
    assert record["profile_sha256"] == profile.digest
    assert Path(observed["argv"][1]).name == "awf_listen.py"
    assert observed["cwd"] == profile.repo
    assert observed["stdin"] is node.subprocess.DEVNULL


def test_start_fails_before_spawn_when_readiness_fails(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))

    def denied(_profile):
        raise node.NodeError("workspace denied")

    monkeypatch.setattr(node, "_load_runtime_config", denied)
    monkeypatch.setattr(
        node.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("listener must not start"),
    )

    with pytest.raises(node.NodeError, match="workspace denied"):
        node.start(profile)


def test_status_rejects_profile_drift(tmp_path: Path):
    path = write_profile(tmp_path)
    profile = node.load_profile(str(path))
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 42,
                "profile_sha256": "sha256:old",
                "profile": str(profile.path),
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(node.NodeError, match="profile changed"):
        node.status(profile)


def test_status_json_is_a_read_only_snapshot(monkeypatch, capsys, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    from agent_workflow import status as factual_status

    monkeypatch.setattr(
        factual_status,
        "snapshot",
        lambda value, run_id: {
            "format": "awf.node-status.v1",
            "profile": value.name,
            "run_id": run_id,
        },
    )

    assert node.status(profile, "task-1", json_output=True) == 0
    assert json.loads(capsys.readouterr().out) == {
        "format": "awf.node-status.v1",
        "profile": profile.name,
        "run_id": "task-1",
    }


def test_stop_refuses_to_signal_a_mismatched_process_record(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 42,
                "profile_sha256": profile.digest,
                "profile": str(profile.path),
                "role": "coder",
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        node.os, "killpg", lambda *args: pytest.fail("must not signal"), raising=False
    )

    with pytest.raises(node.NodeError, match="refusing to signal"):
        node.stop(profile)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_stop_signals_the_bound_posix_process_group(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 42,
                "profile_sha256": profile.digest,
                "profile": str(profile.path),
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        node,
        "_listener_lease",
        lambda value: {"pid": 42, "role": value.role, "repo": str(value.repo)},
    )
    signals = []
    monkeypatch.setattr(
        node.os, "killpg", lambda pid, sig: signals.append((pid, sig)), raising=False
    )
    monkeypatch.setattr(node, "_wait_for_stop", lambda *args: True)

    assert node.stop(profile) == 0
    assert signals == [(42, node.signal.SIGINT)]


@pytest.mark.skipif(os.name != "nt", reason="Windows process-group contract")
def test_stop_signals_the_bound_windows_process_group(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 42,
                "profile_sha256": profile.digest,
                "profile": str(profile.path),
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        node,
        "_listener_lease",
        lambda value: {"pid": 42, "role": value.role, "repo": str(value.repo)},
    )
    signals = []
    monkeypatch.setattr(node.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(node, "_wait_for_stop", lambda *args: True)

    assert node.stop(profile) == 0
    assert signals == [(42, node.signal.CTRL_BREAK_EVENT)]


def test_stop_refuses_live_pid_without_matching_listener_lease(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 42,
                "profile_sha256": profile.digest,
                "profile": str(profile.path),
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(node, "_listener_lease", lambda value: None)
    monkeypatch.setattr(
        node.os, "killpg", lambda *args: pytest.fail("must not signal"), raising=False
    )

    with pytest.raises(node.NodeError, match="lease does not match"):
        node.stop(profile)


def test_logs_returns_only_the_requested_tail(capsys, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.log_path.parent.mkdir(parents=True)
    profile.log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert node.logs(profile, 2) == 0
    assert capsys.readouterr().out == "two\nthree\n"


def test_node_errors_are_concise_without_traceback(capsys, tmp_path: Path):
    result = node.run("doctor", str(tmp_path / "missing.json"))

    assert result == 1
    assert "profile is unavailable or invalid" in capsys.readouterr().err


def test_cli_routes_all_node_commands(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(
        node,
        "run",
        lambda command, profile, lines=100, run_id="", json_output=False: calls.append(
            (command, profile, lines, run_id, json_output)
        )
        or 0,
    )

    assert cli.main(["node", "doctor", "--profile", "reviewer-mac"]) == 0
    assert cli.main(["node", "logs", "--profile", str(tmp_path), "--lines", "12"]) == 0
    assert (
        cli.main(
            ["node", "status", "--profile", "reviewer-mac", "--run", "task-1", "--json"]
        )
        == 0
    )
    assert calls == [
        ("doctor", "reviewer-mac", 100, "", False),
        ("logs", str(tmp_path), 12, "", False),
        ("status", "reviewer-mac", 100, "task-1", True),
    ]
