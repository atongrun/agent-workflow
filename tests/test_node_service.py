"""Contract tests for explicit session and service-managed node lifecycles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_workflow import node, node_service


def write_profile(tmp_path: Path, *, lifecycle: dict[str, object] | None = None) -> Path:
    values: dict[str, object] = {
        "format": "awf.node-profile.v1",
        "name": "coder-win",
        "role": "coder",
        "repo": str((tmp_path / "repo").resolve()),
        "tool": "opencode",
        "upstream_repo": "owner/project",
        "head_repo": "contributor/project",
        "config": str((tmp_path / "dispatch.env").resolve()),
        "state_root": str((tmp_path / "state").resolve()),
    }
    if lifecycle is not None:
        values["lifecycle"] = lifecycle
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_existing_profile_defaults_to_session_lifecycle(tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))

    assert profile.lifecycle_mode == "session"


def test_winsw_service_profile_requires_account_binary_and_digest(tmp_path: Path):
    path = write_profile(
        tmp_path,
        lifecycle={"mode": "service", "manager": "winsw", "scope": "system"},
    )

    with pytest.raises(node.NodeError, match="service_account"):
        node.load_profile(str(path))


def test_non_windows_manager_rejects_windows_credentials_and_binary(tmp_path: Path):
    winsw = tmp_path / "WinSW.exe"
    winsw.write_bytes(b"winsw")
    path = write_profile(
        tmp_path,
        lifecycle={
            "mode": "service",
            "manager": "systemd",
            "scope": "user",
            "service_account": ".\\awf-coder",
            "winsw_executable": str(winsw),
            "winsw_sha256": "sha256:" + hashlib.sha256(b"winsw").hexdigest(),
        },
    )

    with pytest.raises(node.NodeError, match="Windows-only"):
        node.load_profile(str(path))


def test_session_start_fails_closed_inside_ssh_without_override(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    monkeypatch.setenv("SSH_CONNECTION", "client server")
    monkeypatch.setattr(node, "_load_runtime_config", lambda value: ({}, value.repo))

    with pytest.raises(node.NodeError, match="session-bound"):
        node.start(profile)


def test_session_start_allows_explicit_temporary_override(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    monkeypatch.setenv("SSH_CLIENT", "client")
    monkeypatch.setattr(node, "_load_runtime_config", lambda value: ({}, value.repo))
    monkeypatch.setattr(node, "_start_locked", lambda value: 0)

    assert node.start(profile, allow_session_bound=True) == 0


def test_foreground_runs_complete_profile_listener_in_same_process(monkeypatch, tmp_path: Path):
    profile = node.load_profile(
        str(write_profile(tmp_path, lifecycle=None))
    )
    profile.values["enable_preflight"] = True
    observed: list[str] = []
    listener = SimpleNamespace(main=lambda argv: observed.extend(argv) or 17)
    monkeypatch.setattr(node, "_local_readiness", lambda value: object())
    monkeypatch.setattr(node, "_operations_modules", lambda: (object(), listener))
    monkeypatch.setattr(node, "_foreground_record", lambda value, launch_id: None)
    monkeypatch.setattr(node, "_clear_foreground_record", lambda value, launch_id: None)

    assert node.foreground(profile) == 17
    assert "--state-root" in observed
    assert "--upstream-repo" in observed
    assert "--head-repo" in observed
    assert "--enable-preflight" in observed
    assert "--node-launch-id" in observed


@pytest.mark.parametrize(
    ("platform", "os_name", "expected"),
    [("darwin", "posix", "launchd"), ("linux", "posix", "systemd"), ("win32", "nt", "winsw")],
)
def test_auto_manager_resolves_only_to_native_platform(platform, os_name, expected):
    assert node_service.resolve_manager("auto", platform=platform, os_name=os_name) == expected


def test_winsw_renderer_is_profile_first_and_contains_no_secret(tmp_path: Path):
    profile = SimpleNamespace(
        name="coder-win",
        path=(tmp_path / "profile.json").resolve(),
        repo=(tmp_path / "repo").resolve(),
        log_path=(tmp_path / "listener.log").resolve(),
    )

    rendered = node_service.render_winsw(profile, service_id="awf-node-coder-win")

    assert "node foreground --profile" in rendered
    assert str(profile.path) in rendered
    assert "LocalSystem" not in rendered
    assert "password" not in rendered.lower()
    assert "AGENT_BUS_TOKEN" not in rendered


def test_service_actions_dispatch_only_to_adapter(monkeypatch, tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))
    calls: list[str] = []
    adapter = SimpleNamespace(
        install=lambda: calls.append("install") or 0,
        start=lambda: calls.append("start") or 0,
        stop=lambda: calls.append("stop") or 0,
        restart=lambda: calls.append("restart") or 0,
        uninstall=lambda: calls.append("uninstall") or 0,
    )
    monkeypatch.setattr(node_service, "adapter_for", lambda value: adapter)

    for action in ("install", "start", "stop", "restart", "uninstall"):
        assert node_service.run_action(profile, action) == 0

    assert calls == ["install", "start", "stop", "restart", "uninstall"]


def test_service_health_requires_manager_lease_and_profile_agreement():
    assert node_service.service_health(
        manager_running=True,
        process_owner_matches=True,
        profile_digest_matches=True,
        lease_bound=True,
        orphaned=False,
    ) == "running"
    assert node_service.service_health(
        manager_running=False,
        process_owner_matches=True,
        profile_digest_matches=True,
        lease_bound=True,
        orphaned=True,
    ) == "degraded"
