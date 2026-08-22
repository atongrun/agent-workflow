"""Contract tests for the managed node lifecycle reconcile loop."""

from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from agent_workflow import node, node_service


def profile_values(tmp_path: Path, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "format": "awf.node-profile.v1",
        "name": "reviewer-win",
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


def managed_lifecycle(**changes: object) -> dict[str, object]:
    lifecycle: dict[str, object] = {
        "mode": "managed",
        "manager": "auto",
        "scope": "user",
    }
    lifecycle.update(changes)
    return lifecycle


def load_managed_profile(tmp_path: Path, **lifecycle_changes: object) -> node.NodeProfile:
    return node.load_profile(
        str(write_profile(tmp_path, lifecycle=managed_lifecycle(**lifecycle_changes)))
    )


def desired_path(profile: node.NodeProfile) -> Path:
    return profile.node_dir / "desired-state.json"


def write_desired(profile: node.NodeProfile, state: str, generation: int = 1) -> None:
    profile.node_dir.mkdir(parents=True)
    desired_path(profile).write_text(
        json.dumps(
            {
                "format": "awf.node-desired-state.v1",
                "state": state,
                "profile": str(profile.path),
                "profile_sha256": profile.digest,
                "generation": generation,
            }
        ),
        encoding="utf-8",
    )


def write_managed_incarnation(
    profile: node.NodeProfile,
    *,
    process_creation_filetime: int | None,
    process_pid: int = 4321,
    lease_pid: int = 8765,
    lease_root: bool = True,
) -> tuple[Path, Path]:
    profile.node_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "pid": process_pid,
        "launch_id": "a" * 32,
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "state_root": str(profile.state_root),
        "state_root_sha256": node.state_root_binding(profile.state_root),
        "role": profile.role,
        "repo": str(profile.repo),
    }
    if process_creation_filetime is not None:
        record["process_creation_filetime"] = process_creation_filetime
    profile.process_path.write_text(json.dumps(record), encoding="utf-8")
    lease_path = profile.state_root / "listeners" / f"{profile.role}.json"
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease = {
        "pid": lease_pid,
        "launch_id": "a" * 32,
        "role": profile.role,
        "repo": str(profile.repo),
    }
    if lease_root:
        lease.update(
            state_root=str(profile.state_root),
            state_root_sha256=node.state_root_binding(profile.state_root),
        )
    lease_path.write_text(json.dumps(lease), encoding="utf-8")
    return profile.process_path, lease_path


def test_profile_without_lifecycle_keeps_session_compatibility(tmp_path: Path):
    profile = node.load_profile(str(write_profile(tmp_path)))

    assert node.lifecycle_mode(profile) == "session"


def test_managed_lifecycle_rejects_removed_windows_service_fields(tmp_path: Path):
    profile = load_managed_profile(tmp_path)

    assert node.lifecycle_mode(profile) == "managed"
    assert node.lifecycle_settings(profile) == {
        "mode": "managed",
        "manager": "auto",
        "scope": "user",
    }

    for field in ("service_account", "winsw_executable", "winsw_sha256", "password"):
        path = write_profile(tmp_path, lifecycle=managed_lifecycle(**{field: "forbidden"}))
        with pytest.raises(node.NodeError, match=field):
            node.load_profile(str(path))


def test_desired_state_is_profile_bound_generationed_and_written_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    writes: list[tuple[Path, dict[str, object]]] = []

    monkeypatch.setattr(
        node,
        "_atomic_write",
        lambda path, value: writes.append((path, value)),
    )

    value = node.write_desired_state(profile, "running", generation=7)

    assert writes == [(desired_path(profile), value)]
    assert value == {
        "format": "awf.node-desired-state.v1",
        "state": "running",
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "generation": 7,
    }


def test_reconcile_stopped_desired_state_does_not_start_listener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    write_desired(profile, "stopped")
    monkeypatch.setattr(
        node,
        "foreground",
        lambda value: pytest.fail("stopped desired state must not start foreground"),
    )

    assert node.reconcile(profile) == 0


def test_reconcile_running_calls_foreground_and_clean_exit_writes_stopped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    write_desired(profile, "running", generation=3)
    monkeypatch.setattr(node, "foreground", lambda value: 0)

    assert node.reconcile(profile) == 0
    desired = json.loads(desired_path(profile).read_text(encoding="utf-8"))
    assert desired["state"] == "stopped"
    assert desired["profile_sha256"] == profile.digest
    assert desired["generation"] > 3


def test_reconcile_running_keeps_desired_state_after_nonzero_foreground_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    write_desired(profile, "running", generation=4)
    monkeypatch.setattr(node, "foreground", lambda value: 17)

    assert node.reconcile(profile) == 17
    desired = json.loads(desired_path(profile).read_text(encoding="utf-8"))
    assert desired["state"] == "running"
    assert desired["generation"] == 4


def test_task_reconcile_retries_only_transient_bus_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    attempts = 0
    sleeps: list[int] = []

    def reconcile(_profile: node.NodeProfile) -> int:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise node.TransientBusReadinessError("transient Bus health")
        return 0

    monkeypatch.setattr(node, "reconcile", reconcile)
    monkeypatch.setattr(node, "_read_desired_state", lambda value: {"state": "running"})
    monkeypatch.setattr(node_service.time, "sleep", sleeps.append)

    assert node_service._task_reconcile_with_retry(profile) == 0
    assert attempts == 3
    assert sleeps == [15, 15]

    attempts = 0
    sleeps.clear()

    def transient(_profile: node.NodeProfile) -> int:
        raise node.TransientBusReadinessError("transient Bus health")

    monkeypatch.setattr(node, "reconcile", transient)
    monkeypatch.setattr(node, "_read_desired_state", lambda value: {"state": "stopped"})

    assert node_service._task_reconcile_with_retry(profile) == 0
    assert sleeps == []

    attempts = 0

    def exhausted(_profile: node.NodeProfile) -> int:
        nonlocal attempts
        attempts += 1
        raise node.TransientBusReadinessError("transient Bus health")

    monkeypatch.setattr(node, "reconcile", exhausted)
    monkeypatch.setattr(node, "_read_desired_state", lambda value: {"state": "running"})
    with pytest.raises(node.TransientBusReadinessError):
        node_service._task_reconcile_with_retry(profile)
    assert attempts == 4
    assert sleeps == [15, 15, 15]


def test_task_reconcile_does_not_retry_nontransient_node_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    attempts = 0

    def reconcile(_profile: node.NodeProfile) -> int:
        nonlocal attempts
        attempts += 1
        raise node.NodeError("identity drift")

    monkeypatch.setattr(node, "reconcile", reconcile)
    monkeypatch.setattr(
        node_service.time,
        "sleep",
        lambda seconds: pytest.fail("nontransient error must not sleep"),
    )

    with pytest.raises(node.NodeError, match="identity drift"):
        node_service._task_reconcile_with_retry(profile)
    assert attempts == 1


def test_start_and_stop_persist_desired_state_before_manager_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    calls: list[tuple[str, object]] = []

    class Manager:
        def start(self):
            calls.append(("manager.start", None))
            return 0

        def stop(self):
            calls.append(("manager.stop", None))
            return 0

    def write_state(_profile: node.NodeProfile, state: str, **kwargs: object):
        calls.append(("desired", state))
        return {"state": state}

    monkeypatch.setattr(node, "write_desired_state", write_state)
    monkeypatch.setattr(node, "_resolve_managed_manager", lambda value: Manager())
    monkeypatch.setattr(
        node_service,
        "require_installed",
        lambda value: calls.append(("installation.current", None)),
    )

    assert node.start(profile) == 0
    assert node.stop(profile) == 0
    assert calls == [
        ("installation.current", None),
        ("desired", "running"),
        ("manager.start", None),
        ("desired", "stopped"),
        ("manager.stop", None),
    ]

    calls.clear()

    def not_installed(value: node.NodeProfile):
        raise node_service.NodeServiceError(
            f"managed lifecycle is not installed; run awf node install --profile {value.path}"
        )

    monkeypatch.setattr(node_service, "require_installed", not_installed)
    with pytest.raises(node_service.NodeServiceError, match="awf node install --profile"):
        node.start(profile)
    assert calls == []


def test_install_leaves_managed_node_stopped_until_explicit_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path)
    monkeypatch.setattr(node, "default_config_home", lambda: tmp_path / "config")

    class Manager:
        def install(self):
            return 0

    monkeypatch.setattr(node, "_resolve_managed_manager", lambda value: Manager())

    assert node.install(profile) == 0
    assert json.loads(desired_path(profile).read_text(encoding="utf-8"))["state"] == "stopped"


def test_install_snapshot_survives_deleted_authoring_profile_and_stops_exact_listener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from agent_workflow import status as factual_status

    source = write_profile(
        tmp_path,
        lifecycle=managed_lifecycle(manager="task-scheduler"),
    )
    profile = node.load_profile(str(source))
    calls: list[list[str]] = []

    def manager_for(value: node.NodeProfile):
        return node_service.TaskSchedulerAdapter(
            value,
            run_command=lambda argv, **kwargs: calls.append(argv) or "",
            current_user=node_service._current_windows_user(),
        )

    monkeypatch.setattr(node, "default_config_home", lambda: tmp_path / "config")
    monkeypatch.setattr(node, "_resolve_managed_manager", manager_for)

    assert node.install(profile) == 0
    installed = node.load_installed_profile(str(source))
    assert installed is not None
    assert installed.path.is_relative_to((tmp_path / "config" / "installed-profiles").resolve())
    install_record = json.loads(
        (installed.node_dir / "managed" / "install.json").read_text(encoding="utf-8")
    )
    definition = Path(str(install_record["definition"])).read_text(encoding="utf-8")
    assert install_record["profile"] == str(installed.path)
    assert install_record["profile_source"] == str(source.resolve())
    assert str(installed.path) in definition
    assert str(source.resolve()) not in definition
    assert node._load_operational_profile(str(installed.path)).authoring_path == source.resolve()

    source.unlink()
    resolved = node._load_operational_profile(str(source))
    launch_id = "a" * 32
    resolved.node_dir.mkdir(parents=True, exist_ok=True)
    resolved.process_path.write_text(
        json.dumps(
            {
                "format": "awf.node-process.v1",
                "pid": 4321,
                "process_creation_filetime": 777,
                "launch_id": launch_id,
                "profile": str(resolved.path),
                "profile_sha256": resolved.digest,
                "state_root": str(resolved.state_root),
                "state_root_sha256": node.state_root_binding(resolved.state_root),
                "role": resolved.role,
                "repo": str(resolved.repo),
            }
        ),
        encoding="utf-8",
    )
    lease_path = resolved.state_root / "listeners" / f"{resolved.role}.json"
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "launch_id": launch_id,
                "role": resolved.role,
                "repo": str(resolved.repo),
                "state_root": str(resolved.state_root),
                "state_root_sha256": node.state_root_binding(resolved.state_root),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(node, "_windows_process_creation_filetime", lambda pid: 777)
    observed_profiles: list[Path] = []
    monkeypatch.setattr(
        factual_status,
        "snapshot",
        lambda value, run_id: (
            observed_profiles.append(value.path) or {"listener": {"status": "running"}}
        ),
    )
    monkeypatch.setattr(factual_status, "print_human", lambda value: None)

    assert node.run("status", str(source)) == 0
    assert observed_profiles == [resolved.path]

    calls.clear()
    assert node.stop(resolved) == 0
    taskkill = next(argv for argv in calls if argv[0].lower().endswith("taskkill.exe"))
    assert taskkill[taskkill.index("/PID") + 1] == "4321"


def test_managed_stop_refuses_wrong_installed_identity_before_manager_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "launch_id": "a" * 32,
                "profile": str(profile.path),
                "profile_sha256": "sha256:" + "f" * 64,
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    lease_path = profile.state_root / "listeners" / f"{profile.role}.json"
    lease_path.parent.mkdir(parents=True)
    lease_path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "launch_id": "a" * 32,
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "",
        current_user=node_service._current_windows_user(),
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: True)

    with pytest.raises(node_service.NodeServiceError, match="profile identity drift"):
        manager.stop()
    assert calls == []


@pytest.mark.parametrize(
    ("manager_name", "adapter_type"),
    [
        ("systemd", node_service.SystemdAdapter),
        ("launchd", node_service.LaunchdAdapter),
    ],
)
def test_posix_managed_stop_refuses_identity_drift_before_manager_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    manager_name: str,
    adapter_type: type,
):
    profile = load_managed_profile(tmp_path, manager=manager_name)
    profile.node_dir.mkdir(parents=True)
    profile.process_path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "launch_id": "a" * 32,
                "profile": str(profile.path),
                "profile_sha256": "sha256:" + "f" * 64,
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    lease_path = profile.state_root / "listeners" / f"{profile.role}.json"
    lease_path.parent.mkdir(parents=True)
    lease_path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "launch_id": "a" * 32,
                "role": profile.role,
                "repo": str(profile.repo),
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(node_service, "_require_installed", lambda value, manager: {})
    monkeypatch.setattr(
        node_service,
        "_run",
        lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: True)

    with pytest.raises(node_service.NodeServiceError, match="profile identity drift"):
        adapter_type(profile).stop()
    assert calls == []


@pytest.mark.parametrize("manager_name", ["systemd", "launchd", "task-scheduler"])
@pytest.mark.parametrize("root_evidence", ["missing", "partial", "drifted"])
def test_managed_stop_requires_exact_process_state_root_before_native_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    manager_name: str,
    root_evidence: str,
):
    profile = load_managed_profile(tmp_path, manager=manager_name)
    profile.node_dir.mkdir(parents=True)
    record = {
        "pid": 4321,
        "launch_id": "a" * 32,
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "role": profile.role,
        "repo": str(profile.repo),
    }
    if root_evidence == "partial":
        record["state_root"] = str(profile.state_root)
    elif root_evidence == "drifted":
        record.update(
            state_root=str(tmp_path / "other-state"),
            state_root_sha256="sha256:" + "f" * 64,
        )
    profile.process_path.write_text(json.dumps(record), encoding="utf-8")
    lease_path = profile.state_root / "listeners" / f"{profile.role}.json"
    lease_path.parent.mkdir(parents=True)
    lease_path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "launch_id": "a" * 32,
                "role": profile.role,
                "repo": str(profile.repo),
                "state_root": str(profile.state_root),
                "state_root_sha256": node.state_root_binding(profile.state_root),
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(node, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(node_service, "_require_installed", lambda value, manager: {})
    monkeypatch.setattr(
        node_service,
        "_run",
        lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    if manager_name == "task-scheduler":
        manager = node_service.TaskSchedulerAdapter(
            profile,
            run_command=lambda argv, **kwargs: calls.append(argv) or "",
            current_user=node_service._current_windows_user(),
        )
    elif manager_name == "systemd":
        manager = node_service.SystemdAdapter(profile)
    else:
        manager = node_service.LaunchdAdapter(profile)

    with pytest.raises(node_service.NodeServiceError, match="profile identity drift"):
        manager.stop()
    assert calls == []
    assert profile.process_path.is_file()
    monkeypatch.setattr(node, "_pid_alive", lambda pid: False)
    assert node_service._clear_exact_dead_stale_state(profile) is False
    assert profile.process_path.is_file()


def test_task_scheduler_install_uses_native_indefinite_periodic_definition(
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    calls: list[list[str]] = []
    current_user = node_service._current_windows_user()
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "",
        current_user=current_user,
    )

    manager.install()

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0].lower().endswith("schtasks.exe")
    assert "/Create" in argv
    assert argv[argv.index("/TN") + 1].startswith("\\")
    definition = Path(argv[argv.index("/XML") + 1])
    rendered = definition.read_text(encoding="utf-8")
    assert '<Task version="1.3"' in rendered
    assert "InteractiveToken" in rendered
    assert "LeastPrivilege" in rendered
    assert "IgnoreNew" in rendered
    assert "PT1M" in rendered
    assert "P1D" in rendered
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in rendered
    assert current_user in rendered
    assert "reconcile" in rendered
    assert str(profile.log_path) in rendered
    assert "foreground" not in rendered
    assert not any("powershell" in part.lower() for part in argv)
    assert "powershell" not in rendered.lower()
    assert "password" not in rendered.lower()
    assert "winsw" not in rendered.lower()


def test_task_scheduler_stop_ends_task_and_exact_bound_taskkills_process_tree(
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    calls: list[list[str]] = []
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "",
        current_user=r"DESKTOP\alice",
    )

    manager.stop(bound_pid=4321)

    assert any(argv[0].lower().endswith("schtasks.exe") and "/End" in argv for argv in calls)
    taskkill = next(argv for argv in calls if argv[0].lower().endswith("taskkill.exe"))
    assert taskkill[taskkill.index("/PID") + 1] == "4321"
    assert "/T" in taskkill
    assert "/F" in taskkill


def test_windows_taskkill_requires_matching_kernel_creation_identity(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(node, "_windows_process_creation_filetime", lambda pid: 222)

    assert node_service._process_creation_identity_matches(
        {"process_creation_filetime": 222}, 4321, required=True
    )
    assert not node_service._process_creation_identity_matches(
        {"process_creation_filetime": 111}, 4321, required=True
    )


def test_task_scheduler_stop_clears_reused_pid_without_taskkill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    process_path, lease_path = write_managed_incarnation(
        profile,
        process_creation_filetime=111,
    )
    calls: list[list[str]] = []
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "",
        current_user=node_service._current_windows_user(),
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(node, "_windows_process_creation_filetime", lambda pid: 222)

    assert manager.stop() == 0
    assert not process_path.exists()
    assert not lease_path.exists()
    assert not any(argv[0].lower().endswith("taskkill.exe") for argv in calls)
    assert any(argv[0].lower().endswith("schtasks.exe") and "/End" in argv for argv in calls)


@pytest.mark.parametrize(
    ("creation", "lease_root", "live_pids", "error"),
    [
        (None, True, {4321}, "unbound live listener"),
        (111, False, {4321}, "unbound live listener"),
        (111, True, {4321, 8765}, "process creation identity drift"),
    ],
)
def test_task_scheduler_stop_preserves_incomplete_or_live_lease_on_pid_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    creation: int | None,
    lease_root: bool,
    live_pids: set[int],
    error: str,
):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    process_path, lease_path = write_managed_incarnation(
        profile,
        process_creation_filetime=creation,
        lease_root=lease_root,
    )
    calls: list[list[str]] = []
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "",
        current_user=node_service._current_windows_user(),
    )
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid in live_pids)
    monkeypatch.setattr(node, "_windows_process_creation_filetime", lambda pid: 222)
    monkeypatch.setattr(
        node_service,
        "_process_creation_identity_matches",
        lambda record, pid: False,
    )

    with pytest.raises(node_service.NodeServiceError, match=error):
        manager.stop()
    assert process_path.exists()
    assert lease_path.exists()
    assert calls == []
    if creation is None:
        monkeypatch.setattr(node, "_pid_alive", lambda pid: False)
        assert not node_service._clear_exact_dead_stale_state(
            profile,
            require_creation_identity=True,
        )
        assert process_path.exists()
        assert lease_path.exists()


def test_reconcile_clears_exact_reused_incarnation_before_foreground(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    write_desired(profile, "running")
    process_path, lease_path = write_managed_incarnation(
        profile,
        process_creation_filetime=111,
    )
    foreground: list[node.NodeProfile] = []
    clear_stale = node_service._clear_exact_dead_stale_state
    monkeypatch.setattr(node, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(node, "_windows_process_creation_filetime", lambda pid: 222)
    monkeypatch.setattr(
        node_service,
        "_clear_exact_dead_stale_state",
        lambda value: clear_stale(value, require_creation_identity=True),
    )
    monkeypatch.setattr(
        node,
        "foreground",
        lambda value: foreground.append(value) or 17,
    )

    assert node.reconcile(profile) == 17
    assert foreground == [profile]
    assert not process_path.exists()
    assert not lease_path.exists()


def test_task_scheduler_commands_do_not_depend_on_localized_status_output(tmp_path: Path):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    calls: list[list[str]] = []
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "本次任务成功完成。",
        current_user=r"DESKTOP\alice",
    )

    status = manager.status()

    assert status["manager"] == "task-scheduler"
    assert status["localized_output_ignored"] is True
    assert calls[0][0].lower().endswith("schtasks.exe")
    assert "/Query" in calls[0]


def test_task_scheduler_uninstall_allows_clean_reinstall(tmp_path: Path):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    calls: list[list[str]] = []
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "",
        current_user=node_service._current_windows_user(),
    )

    manager.install()
    manager.uninstall()
    manager.install()

    creates = [argv for argv in calls if "/Create" in argv]
    assert len(creates) == 2
    assert manager.definition.is_file()
    assert (profile.node_dir / "managed" / "install.json").is_file()


def test_task_scheduler_upgrade_replaces_a_drifted_action_record(tmp_path: Path):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    calls: list[list[str]] = []
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: calls.append(argv) or "",
        current_user=node_service._current_windows_user(),
    )
    manager.install()
    install_path = profile.node_dir / "managed" / "install.json"
    record = json.loads(install_path.read_text(encoding="utf-8"))
    record["action_argv"] = ["old-python", "old-entrypoint"]
    install_path.write_text(json.dumps(record), encoding="utf-8")

    manager.upgrade()

    creates = [argv for argv in calls if "/Create" in argv]
    assert len(creates) == 2
    upgraded = json.loads(install_path.read_text(encoding="utf-8"))
    assert upgraded["action_argv"] == node_service._task_reconcile_argv(profile)


@pytest.mark.parametrize("drift", ["manager_id", "definition"])
def test_installed_record_rejects_manager_target_and_definition_path_drift(
    tmp_path: Path,
    drift: str,
):
    profile = load_managed_profile(tmp_path, manager="task-scheduler")
    manager = node_service.TaskSchedulerAdapter(
        profile,
        run_command=lambda argv, **kwargs: "",
        current_user=node_service._current_windows_user(),
    )
    manager.install()
    install_path = profile.node_dir / "managed" / "install.json"
    node_service._require_installed(profile, "task-scheduler")
    record = json.loads(install_path.read_text(encoding="utf-8"))
    if drift == "manager_id":
        record["manager_id"] = r"\AgentWorkflow-foreign"
    else:
        alternate = tmp_path / "foreign-task.xml"
        alternate.write_bytes(manager.definition.read_bytes())
        record["definition"] = str(alternate)
        record["definition_sha256"] = node_service._sha256(alternate)
    install_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(node_service.NodeServiceError, match="installation drifted"):
        node_service._require_installed(profile, "task-scheduler")
    with pytest.raises(node_service.NodeServiceError, match="upgrade target identity drifted"):
        node_service._require_upgrade_target(
            profile,
            "task-scheduler",
            manager.task_name,
        )


def test_launchd_uninstall_allows_clean_reinstall(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path, manager="launchd")
    definition = tmp_path / "launch-agent.plist"
    calls: list[list[str]] = []

    monkeypatch.setattr(
        node_service.LaunchdAdapter,
        "definition",
        property(lambda self: definition),
    )
    monkeypatch.setattr(
        node_service.LaunchdAdapter,
        "domain",
        property(lambda self: "gui/501"),
    )
    monkeypatch.setattr(
        node_service,
        "_run",
        lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    manager = node_service.LaunchdAdapter(profile)

    manager.install()
    manager.uninstall()
    manager.install()

    bootstraps = [argv for argv in calls if "bootstrap" in argv]
    assert len(bootstraps) == 2
    assert definition.is_file()
    assert (profile.node_dir / "managed" / "install.json").is_file()


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", "task-scheduler"),
        ("darwin", "launchd"),
        ("linux", "systemd"),
    ],
)
def test_auto_manager_maps_to_native_user_scoped_manager(platform: str, expected: str):
    assert node.resolve_managed_manager("auto", platform=platform, scope="user") == expected


@pytest.mark.parametrize("manager_name", ["launchd", "systemd"])
def test_mac_and_systemd_definitions_target_reconcile_not_foreground(
    tmp_path: Path,
    manager_name: str,
):
    profile = load_managed_profile(tmp_path, manager=manager_name)

    rendered = node.render_managed_definition(profile, manager=manager_name)

    assert "reconcile" in rendered
    assert "foreground" not in rendered
    expected_profile = (
        str(profile.path).replace("\\", "\\\\") if manager_name == "systemd" else str(profile.path)
    )
    assert expected_profile in rendered
    assert "AGENT_BUS_TOKEN" not in rendered
    assert "password" not in rendered.lower()


@pytest.mark.skipif(os.name == "nt", reason="POSIX venvs use interpreter symlinks")
def test_native_definitions_preserve_the_invoked_venv_python_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = load_managed_profile(tmp_path, manager="launchd")
    shim = tmp_path / "venv" / "bin" / "python"
    shim.parent.mkdir(parents=True)
    shim.symlink_to(Path(node_service.sys.executable).resolve())
    monkeypatch.setattr(node_service.sys, "executable", str(shim))

    systemd = node_service._render_systemd(profile, "awf-test.service")
    launchd = node_service._render_launchd(profile, "com.agentworkflow.test").decode()
    task = node_service._render_task_scheduler(profile, "DOMAIN\\user").decode()
    for definition_text in (systemd, launchd, task):
        assert str(shim) in definition_text
        assert str(shim.resolve()) not in definition_text

    definition = tmp_path / "launch-agent.plist"
    definition.write_text(launchd, encoding="utf-8")
    monkeypatch.setattr(
        node_service.LaunchdAdapter,
        "definition",
        property(lambda self: definition),
    )
    manager = node_service.LaunchdAdapter(profile)
    node_service._write_install_record(
        profile,
        "launchd",
        definition,
        {"manager_id": manager.label},
    )
    record = node_service._require_installed(profile, "launchd")
    assert record["python"] == str(shim)
    assert record["python_sha256"] == node_service._sha256(shim)
    assert record["action_argv"][0] == str(shim)


def test_native_manager_and_gbk_log_boundaries_are_utf8_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 7, "状态🙂\ufffd", "sensitive raw output")

    monkeypatch.setattr(node_service.subprocess, "run", fake_run)
    argv = ["manager", "--literal", "a & b"]

    completed = node_service._run(argv, check=False, timeout=9)

    assert completed.args == argv
    assert completed.returncode == 7
    assert calls == [
        (
            argv,
            {
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "timeout": 9,
                "check": False,
            },
        )
    ]
    with pytest.raises(node_service.NodeServiceError) as failed:
        node_service._run(argv)
    assert "exit=7" in str(failed.value)
    assert "text=utf-8/replace" in str(failed.value)
    assert "sensitive raw output" not in str(failed.value)

    log_path = tmp_path / "listener.log"
    log_path.write_bytes("状态🙂".encode("utf-8") + b"\xff\n")
    raw_output = io.BytesIO()
    console = io.TextIOWrapper(raw_output, encoding="gbk", errors="strict")
    monkeypatch.setattr(node_service.sys, "stdout", console)

    assert node_service._tail_file(log_path, 1) == 0
    console.flush()

    assert raw_output.getvalue().decode("gbk").splitlines() == ["状态??"]

    utf8_output = io.BytesIO()
    utf8_console = io.TextIOWrapper(utf8_output, encoding="cp65001", errors="strict")
    monkeypatch.setattr(node_service.sys, "stdout", utf8_console)

    assert node_service._tail_file(log_path, 1) == 0
    utf8_console.flush()

    assert utf8_output.getvalue().decode("utf-8").splitlines() == ["状态🙂\ufffd"]
