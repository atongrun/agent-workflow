"""Tests for the thin local node lifecycle surface."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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


def test_local_readiness_captures_only_tool_version_hash(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.repo.mkdir()
    calls: list[list[str]] = []
    config = {
        "AGENT_BUS_URL": "https://bus.invalid",
        "AWF_REVIEWER_TOKEN": "top-secret",
        "AWF_BUS_BIN": "agent-bus",
        "AWF_PI_BIN": "pi",
    }

    class Config:
        @staticmethod
        def load_config(path):
            return config

        @staticmethod
        def native_executable(value):
            return value

    class Listen:
        class ExecutionFailure(RuntimeError):
            pass

        @staticmethod
        def check_workspace_readiness(repo, role):
            return repo

        @staticmethod
        def run_command(argv, **kwargs):
            calls.append(argv)
            if argv == ["pi", "--version"]:
                return subprocess.CompletedProcess(argv, 0, "pi 1.2.3", "")
            return subprocess.CompletedProcess(argv, 0, "healthy", "")

    monkeypatch.setattr(node, "_operations_modules", lambda: (Config, Listen))
    monkeypatch.setattr(node.shutil, "which", lambda value: f"/tools/{value}")
    monkeypatch.setitem(
        sys.modules,
        "awf_network",
        SimpleNamespace(add_url_host_to_no_proxy=lambda environment, url: None),
    )

    result = node._local_readiness(profile)

    assert ["agent-bus", "doctor"] in calls
    assert ["pi", "--version"] in calls
    assert result.tool_version_sha256 == node._version_sha256("pi 1.2.3", "")
    assert result.config["AWF_REVIEWER_TOKEN"] == "top-secret"


def test_listener_snapshot_treats_profile_drift_as_stale(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    monkeypatch.setattr(
        node,
        "_process_record",
        lambda value: {"pid": 42, "profile_sha256": "sha256:old"},
    )
    monkeypatch.setattr(node, "_listener_lease", lambda value: {"pid": 42})
    monkeypatch.setattr(
        node,
        "_pid_alive",
        lambda pid: pytest.fail("a drifted process must not be treated as this profile"),
    )

    assert node._listener_snapshot(profile)["status"] == "stale"


def test_listener_lease_requires_exact_launch_identity_when_present(tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    lease = {
        "pid": 84,
        "launch_id": "a" * 32,
        "role": profile.role,
        "repo": str(profile.repo),
    }

    assert node._lease_matches(profile, lease, 42, "a" * 32)
    assert not node._lease_matches(profile, lease, 42, "b" * 32)
    assert not node._lease_matches(profile, lease, 84, "b" * 32)


def test_listener_lease_keeps_direct_pid_compatibility_without_launch_identity(tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    lease = {"pid": 42, "role": profile.role, "repo": str(profile.repo)}

    assert node._lease_matches(profile, lease, 42)
    assert not node._lease_matches(profile, lease, 7)


def test_listener_snapshot_accepts_distinct_pid_with_bound_launch_identity(
    monkeypatch, tmp_path: Path
):
    profile = node.load_profile(str(write_profile(tmp_path)))
    monkeypatch.setattr(
        node,
        "_process_record",
        lambda value: {
            "pid": 42,
            "launch_id": "a" * 32,
            "profile_sha256": profile.digest,
        },
    )
    monkeypatch.setattr(
        node,
        "_listener_lease",
        lambda value: {
            "pid": 84,
            "launch_id": "a" * 32,
            "role": profile.role,
            "repo": str(profile.repo),
        },
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid in {42, 84})

    assert node._listener_snapshot(profile)["status"] == "running"


def test_listener_snapshot_rejects_dead_listener_behind_live_launcher(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    monkeypatch.setattr(
        node,
        "_process_record",
        lambda value: {
            "pid": 42,
            "launch_id": "a" * 32,
            "profile_sha256": profile.digest,
        },
    )
    monkeypatch.setattr(
        node,
        "_listener_lease",
        lambda value: {
            "pid": 84,
            "launch_id": "a" * 32,
            "role": profile.role,
            "repo": str(profile.repo),
        },
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid == 42)

    assert node._listener_snapshot(profile)["status"] == "stale"


def readiness(profile: node.NodeProfile, **changes: object) -> node.LocalReadiness:
    values: dict[str, object] = {
        "config": {"AGENT_BUS_URL": "https://bus.invalid", "AWF_REVIEWER_TOKEN": "secret"},
        "repo": profile.repo,
        "bus_executable": "/tools/agent-bus",
        "tool_executable": "/tools/pi",
        "tool_version_sha256": "sha256:" + "1" * 64,
    }
    values.update(changes)
    return node.LocalReadiness(**values)


def test_doctor_json_emits_secret_free_reusable_snapshot(monkeypatch, capsys, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    observed = datetime(2026, 8, 9, 1, 2, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(node, "_local_readiness", lambda value: readiness(value))
    monkeypatch.setattr(
        node,
        "_listener_snapshot",
        lambda value: {
            "status": "running",
            "pid": 4321,
            "profile_sha256": value.digest,
            "lease_bound": True,
        },
    )
    monkeypatch.setattr(node, "_now", lambda: observed)

    assert node.doctor(profile, json_output=True, ttl_seconds=3600) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["format"] == "awf.node-readiness.v1"
    assert report["status"] == "ready"
    assert report["observed_at"] == "2026-08-09T01:02:03+00:00"
    assert report["valid_until"] == "2026-08-09T02:02:03+00:00"
    assert report["scope"] == "operator-discovery-only"
    assert report["awf_version"] == node.__version__
    assert report["runtime"] == {
        "platform": sys.platform,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }
    assert report["profile"] == {
        "name": "reviewer-mac",
        "role": "reviewer",
        "tool": "pi",
        "model": "",
    }
    assert report["profile_sha256"] == profile.digest
    assert report["fingerprint"].startswith("sha256:")
    assert report["listener"]["status"] == "running"
    assert report["remote_dispatch"] == {
        "status": "not_proven",
        "required_gate": "fast/deep-preflight",
    }
    serialized = json.dumps(report, sort_keys=True)
    assert "secret" not in serialized
    assert "bus.invalid" not in serialized
    assert str(profile.repo) not in serialized
    assert "/tools/" not in serialized


def test_doctor_fingerprint_changes_with_tool_version(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    listener = {
        "status": "stopped",
        "pid": None,
        "profile_sha256": "",
        "lease_bound": False,
    }
    monkeypatch.setattr(node, "_listener_snapshot", lambda value: listener)
    first = node.doctor_report(
        profile,
        readiness(profile),
        ttl_seconds=3600,
        observed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )
    second = node.doctor_report(
        profile,
        readiness(profile, tool_version_sha256="sha256:" + "2" * 64),
        ttl_seconds=3600,
        observed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    assert first["fingerprint"] != second["fingerprint"]


def test_doctor_rejects_invalid_snapshot_ttl(tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))

    with pytest.raises(node.NodeError, match="ttl-seconds"):
        node.doctor_report(
            profile,
            readiness(profile),
            ttl_seconds=0,
            observed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )


def test_cli_routes_doctor_json_and_ttl(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    def run(command, profile, **kwargs):
        captured.update({"command": command, "profile": profile, **kwargs})
        return 0

    monkeypatch.setattr(node, "run", run)
    profile = str(write_profile(tmp_path))

    assert (
        cli.main(
            [
                "node",
                "doctor",
                "--profile",
                profile,
                "--json",
                "--ttl-seconds",
                "900",
            ]
        )
        == 0
    )
    assert captured == {
        "command": "doctor",
        "profile": profile,
        "lines": 100,
        "run_id": "",
        "json_output": True,
        "ttl_seconds": 900,
    }


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
    assert len(record["launch_id"]) == 32
    assert record["profile_sha256"] == profile.digest
    assert Path(observed["argv"][1]).name == "awf_listen.py"
    assert observed["argv"][-2:] == ["--node-launch-id", record["launch_id"]]
    assert observed["cwd"] == profile.repo
    assert observed["stdin"] is node.subprocess.DEVNULL


def test_listener_start_waits_for_a_slow_windows_lease(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    elapsed = 0.0

    class Process:
        pid = 4321

        @staticmethod
        def poll():
            return None

    def monotonic():
        return elapsed

    def sleep(seconds: float):
        nonlocal elapsed
        elapsed += seconds

    def listener_lease(_profile):
        if elapsed < 4:
            return None
        return {
            "pid": 9876,
            "launch_id": "a" * 32,
            "role": profile.role,
            "repo": str(profile.repo),
        }

    monkeypatch.setattr(node.time, "monotonic", monotonic)
    monkeypatch.setattr(node.time, "sleep", sleep)
    monkeypatch.setattr(node, "_listener_lease", listener_lease)
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid == 9876)

    node._wait_for_listener_lease(profile, Process(), "a" * 32)

    assert elapsed >= 4


def test_listener_start_timeout_remains_bounded_and_fail_closed(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    elapsed = 0.0

    class Process:
        pid = 4321

        @staticmethod
        def poll():
            return None

    def monotonic():
        return elapsed

    def sleep(seconds: float):
        nonlocal elapsed
        elapsed += seconds

    monkeypatch.setattr(node.time, "monotonic", monotonic)
    monkeypatch.setattr(node.time, "sleep", sleep)
    monkeypatch.setattr(node, "_listener_lease", lambda _profile: None)

    with pytest.raises(node.NodeError, match="listener readiness timed out"):
        node._wait_for_listener_lease(profile, Process(), "a" * 32)

    assert elapsed >= node.LISTENER_START_TIMEOUT_SECONDS


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
            "listener": {"status": "running"},
        },
    )

    assert node.status(profile, "task-1", json_output=True) == 0
    assert json.loads(capsys.readouterr().out) == {
        "format": "awf.node-status.v1",
        "profile": profile.name,
        "run_id": "task-1",
        "listener": {"status": "running"},
    }


def test_status_preserves_stopped_health_exit_code(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    from agent_workflow import status as factual_status

    monkeypatch.setattr(
        factual_status,
        "snapshot",
        lambda value, run_id: {"listener": {"status": "stopped"}},
    )
    monkeypatch.setattr(factual_status, "print_human", lambda value: None)

    assert node.status(profile) == 3
    assert node.status(profile, json_output=True) == 3


def test_stop_refuses_to_signal_a_mismatched_process_record(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 42,
                "launch_id": "a" * 32,
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
                "launch_id": "a" * 32,
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
        lambda value: {
            "pid": 84,
            "launch_id": "a" * 32,
            "role": value.role,
            "repo": str(value.repo),
        },
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
                "launch_id": "a" * 32,
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
        lambda value: {
            "pid": 84,
            "launch_id": "a" * 32,
            "role": value.role,
            "repo": str(value.repo),
        },
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


def test_stop_refuses_dead_listener_behind_live_launcher(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 42,
                "launch_id": "a" * 32,
                "profile_sha256": profile.digest,
                "profile": str(profile.path),
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid == 42)
    monkeypatch.setattr(
        node,
        "_listener_lease",
        lambda value: {
            "pid": 84,
            "launch_id": "a" * 32,
            "role": value.role,
            "repo": str(value.repo),
        },
    )
    monkeypatch.setattr(
        node.os, "killpg", lambda *args: pytest.fail("must not signal"), raising=False
    )
    monkeypatch.setattr(
        node.os, "kill", lambda *args: pytest.fail("must not signal"), raising=False
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
        lambda command, profile, lines=100, run_id="", json_output=False, ttl_seconds=3600: (
            calls.append((command, profile, lines, run_id, json_output, ttl_seconds)) or 0
        ),
    )

    assert cli.main(["node", "doctor", "--profile", "reviewer-mac"]) == 0
    assert cli.main(["node", "logs", "--profile", str(tmp_path), "--lines", "12"]) == 0
    assert (
        cli.main(["node", "status", "--profile", "reviewer-mac", "--run", "task-1", "--json"]) == 0
    )
    assert calls == [
        ("doctor", "reviewer-mac", 100, "", False, 3600),
        ("logs", str(tmp_path), 12, "", False, 3600),
        ("status", "reviewer-mac", 100, "task-1", True, 3600),
    ]
