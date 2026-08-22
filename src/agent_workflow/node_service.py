"""Native managed-lifecycle adapters for one foreground role listener."""

from __future__ import annotations

import codecs
import getpass
import hashlib
import json
import os
import plistlib
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


class NodeServiceError(RuntimeError):
    """A credential-safe native managed lifecycle failure."""


SUPPORTED_MANAGERS = {"launchd", "systemd", "task-scheduler"}
_TEXT_ENCODING = "utf-8"
_TEXT_ERRORS = "replace"


def resolve_manager(manager: str, *, platform: str = sys.platform, os_name: str = os.name) -> str:
    native = _native_manager(platform=platform, os_name=os_name)
    if manager == "auto":
        return native
    if manager not in SUPPORTED_MANAGERS:
        raise NodeServiceError(f"unsupported managed lifecycle manager: {manager}")
    if manager != native:
        raise NodeServiceError(f"{manager} is not native on {platform}")
    return manager


def _native_manager(*, platform: str = sys.platform, os_name: str = os.name) -> str:
    if platform == "win32":
        return "task-scheduler"
    if platform == "darwin":
        return "launchd"
    if platform.startswith("linux"):
        return "systemd"
    if os_name == "nt":
        return "task-scheduler"
    raise NodeServiceError(f"no native managed lifecycle manager is supported on {platform}")


def service_health(
    *,
    manager_running: bool,
    process_owner_matches: bool,
    profile_digest_matches: bool,
    lease_bound: bool,
    orphaned: bool,
) -> str:
    if (
        manager_running
        and process_owner_matches
        and profile_digest_matches
        and lease_bound
        and not orphaned
    ):
        return "running"
    if not manager_running and not lease_bound and not orphaned:
        return "stopped"
    return "degraded"


def _reconcile_arguments(profile) -> list[str]:
    return [
        "-m",
        "agent_workflow.cli",
        "node",
        "reconcile",
        "--profile",
        str(Path(profile.path).resolve()),
    ]


def _reconcile_argv(profile) -> list[str]:
    return [str(Path(sys.executable).resolve()), *_reconcile_arguments(profile)]


def _task_reconcile_argv(profile) -> list[str]:
    return [
        str(Path(sys.executable).resolve()),
        "-m",
        "agent_workflow.node_service",
        "task-reconcile",
        str(Path(profile.path).resolve()),
        str(Path(profile.log_path).resolve()),
    ]


def _manager_action_argv(profile, manager: str) -> list[str]:
    return (
        _task_reconcile_argv(profile) if manager == "task-scheduler" else _reconcile_argv(profile)
    )


def _service_dir(profile) -> Path:
    return profile.node_dir / "managed"


def _safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in name)


def _render_task_scheduler(profile, user: str) -> bytes:
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    task = ET.Element("Task", {"version": "1.3", "xmlns": namespace})
    registration = ET.SubElement(task, "RegistrationInfo")
    ET.SubElement(registration, "Description").text = "Reconciles one Agent Workflow role listener."
    triggers = ET.SubElement(task, "Triggers")
    logon = ET.SubElement(triggers, "LogonTrigger")
    ET.SubElement(logon, "Enabled").text = "true"
    ET.SubElement(logon, "UserId").text = user
    calendar = ET.SubElement(triggers, "CalendarTrigger")
    ET.SubElement(calendar, "Enabled").text = "true"
    ET.SubElement(calendar, "StartBoundary").text = datetime.now().isoformat(timespec="seconds")
    repetition = ET.SubElement(calendar, "Repetition")
    ET.SubElement(repetition, "Interval").text = "PT1M"
    ET.SubElement(repetition, "Duration").text = "P1D"
    ET.SubElement(repetition, "StopAtDurationEnd").text = "false"
    schedule = ET.SubElement(calendar, "ScheduleByDay")
    ET.SubElement(schedule, "DaysInterval").text = "1"
    principals = ET.SubElement(task, "Principals")
    principal = ET.SubElement(principals, "Principal", {"id": "CurrentUser"})
    ET.SubElement(principal, "UserId").text = user
    ET.SubElement(principal, "LogonType").text = "InteractiveToken"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    settings = ET.SubElement(task, "Settings")
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "DisallowStartIfOnBatteries").text = "false"
    ET.SubElement(settings, "StopIfGoingOnBatteries").text = "false"
    ET.SubElement(settings, "AllowHardTerminate").text = "true"
    ET.SubElement(settings, "StartWhenAvailable").text = "true"
    ET.SubElement(settings, "RunOnlyIfNetworkAvailable").text = "false"
    ET.SubElement(settings, "ExecutionTimeLimit").text = "PT0S"
    actions = ET.SubElement(task, "Actions", {"Context": "CurrentUser"})
    action = ET.SubElement(actions, "Exec")
    argv = _task_reconcile_argv(profile)
    ET.SubElement(action, "Command").text = argv[0]
    ET.SubElement(action, "Arguments").text = subprocess.list2cmdline(argv[1:])
    ET.SubElement(action, "WorkingDirectory").text = str(profile.repo)
    return ET.tostring(task, encoding="utf-8", xml_declaration=False)


def _render_systemd(profile, unit: str) -> str:
    command = " ".join(_systemd_quote(value) for value in _reconcile_argv(profile))
    return f"""[Unit]
Description=Agent Workflow Node ({profile.name})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={profile.repo}
ExecStart={command}
Restart=on-failure
RestartSec=10
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=default.target
"""


def _systemd_quote(value: object) -> str:
    text = str(value)
    return '"' + text.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_launchd(profile, label: str) -> bytes:
    return plistlib.dumps(
        {
            "Label": label,
            "ProgramArguments": _reconcile_argv(profile),
            "WorkingDirectory": str(profile.repo),
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 10,
            "StandardOutPath": str(profile.log_path),
            "StandardErrorPath": str(profile.log_path),
        },
        sort_keys=True,
    )


def render_definition(profile, *, manager: str) -> str:
    if manager == "systemd":
        return _render_systemd(profile, f"awf-node-{_safe_name(profile.name)}.service")
    if manager == "launchd":
        label = f"com.agentworkflow.node.{_safe_name(profile.name)}"
        return _render_launchd(profile, label).decode("utf-8")
    if manager == "task-scheduler":
        return _render_task_scheduler(profile, "CURRENT-CONSOLE-USER").decode("utf-8")
    raise NodeServiceError(f"unsupported managed lifecycle manager: {manager}")


def _run(
    argv: list[str],
    *,
    check: bool = True,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise NodeServiceError("service manager argv must be explicit non-empty strings")
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding=_TEXT_ENCODING,
            errors=_TEXT_ERRORS,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NodeServiceError(f"service manager command failed: {argv[0]}") from exc
    if check and result.returncode != 0:
        raise NodeServiceError(
            f"service manager command failed: {argv[0]} "
            f"(exit={result.returncode}, text={_TEXT_ENCODING}/{_TEXT_ERRORS})"
        )
    return result


def _decode_utf8(value: bytes | str) -> str:
    return value.decode(_TEXT_ENCODING, errors=_TEXT_ERRORS) if isinstance(value, bytes) else value


def _write_console_text(value: bytes | str, *, end: str = "\n") -> None:
    text = _decode_utf8(value) + end
    encoding = sys.stdout.encoding or _TEXT_ENCODING
    if codecs.lookup(encoding).name != _TEXT_ENCODING:
        text = text.replace("\ufffd", "?")
    safe_text = text.encode(encoding, errors=_TEXT_ERRORS).decode(encoding)
    sys.stdout.write(safe_text)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise NodeServiceError(f"managed lifecycle artifact is unavailable: {path}") from exc
    return "sha256:" + digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_install_record(
    profile, manager: str, definition: Path, extra: dict[str, object]
) -> None:
    from agent_workflow import __version__

    body = definition.read_bytes()
    record = {
        "format": "awf.node-managed-install.v1",
        "manager": manager,
        "profile": str(Path(profile.path).resolve()),
        "profile_source": str(Path(profile.authoring_path).resolve()),
        "profile_sha256": profile.digest,
        "definition": str(definition),
        "definition_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "python": str(Path(sys.executable).resolve()),
        "python_sha256": _sha256(Path(sys.executable).resolve()),
        "awf_version": __version__,
        "action_argv": _manager_action_argv(profile, manager),
        **extra,
    }
    _atomic_write(
        _service_dir(profile) / "install.json",
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode(),
    )


def _install_record(profile) -> dict[str, object]:
    path = _service_dir(profile) / "install.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NodeServiceError(f"managed lifecycle install record is unavailable: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != "awf.node-managed-install.v1":
        raise NodeServiceError(f"managed lifecycle install record is invalid: {path}")
    return value


def _manager_target(profile, manager: str) -> tuple[str, Path]:
    if manager == "systemd":
        adapter = SystemdAdapter(profile)
        return adapter.unit, adapter.definition
    if manager == "launchd":
        adapter = LaunchdAdapter(profile)
        return adapter.label, adapter.definition
    if manager == "task-scheduler":
        adapter = TaskSchedulerAdapter(profile)
        return adapter.task_name, adapter.definition
    raise NodeServiceError(f"unsupported managed lifecycle manager: {manager}")


def _remove_install_record(profile) -> None:
    (_service_dir(profile) / "install.json").unlink(missing_ok=True)


def _require_installed(profile, manager: str) -> dict[str, object]:
    from agent_workflow import __version__

    record = _install_record(profile)
    manager_id, definition = _manager_target(profile, manager)
    expected = {
        "manager": manager,
        "manager_id": manager_id,
        "profile": str(Path(profile.path).resolve()),
        "profile_source": str(Path(profile.authoring_path).resolve()),
        "profile_sha256": profile.digest,
        "definition": str(definition),
        "python": str(Path(sys.executable).resolve()),
        "awf_version": __version__,
        "action_argv": _manager_action_argv(profile, manager),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise NodeServiceError("managed lifecycle installation drifted; run upgrade")
    if not definition.is_file() or _sha256(definition) != record.get("definition_sha256"):
        raise NodeServiceError("managed lifecycle definition digest does not match its record")
    if _sha256(Path(sys.executable).resolve()) != record.get("python_sha256"):
        raise NodeServiceError("installed Python digest does not match its record; run upgrade")
    return record


def _require_upgrade_target(profile, manager: str, manager_id: str) -> dict[str, object]:
    record = _install_record(profile)
    expected_manager_id, definition = _manager_target(profile, manager)
    expected = {
        "manager": manager,
        "manager_id": expected_manager_id,
        "profile": str(Path(profile.path).resolve()),
        "definition": str(definition),
    }
    if manager_id != expected_manager_id:
        raise NodeServiceError("managed lifecycle upgrade target identity drifted")
    if any(record.get(key) != value for key, value in expected.items()):
        raise NodeServiceError("managed lifecycle upgrade target identity drifted")
    return record


def _guard_install(profile, manager: str, *, force: bool) -> bool:
    path = _service_dir(profile) / "install.json"
    if not path.exists() or force:
        return False
    _require_installed(profile, manager)
    return True


def installation_snapshot(profile) -> dict[str, object]:
    """Report credential-free native install-record and definition truth."""
    manager = resolve_manager(str(profile.lifecycle.get("manager", "auto")))
    record_path = _service_dir(profile) / "install.json"
    if not record_path.is_file():
        return {
            "source": "native_manager_install_record+definition",
            "manager": manager,
            "installed": False,
            "status": "not_installed",
        }
    try:
        _require_installed(profile, manager)
    except NodeServiceError:
        return {
            "source": "native_manager_install_record+definition",
            "manager": manager,
            "installed": None,
            "status": "stale",
        }
    return {
        "source": "native_manager_install_record+definition",
        "manager": manager,
        "installed": True,
        "status": "current",
    }


def require_installed(profile) -> None:
    """Fail before desired-state mutation unless native installation evidence is current."""
    snapshot = installation_snapshot(profile)
    install_action = subprocess.list2cmdline(
        ["awf", "node", "install", "--profile", str(Path(profile.path).resolve())]
    )
    upgrade_action = subprocess.list2cmdline(
        ["awf", "node", "upgrade", "--profile", str(Path(profile.path).resolve())]
    )
    if snapshot["installed"] is True:
        return
    if snapshot["installed"] is False:
        raise NodeServiceError(f"managed lifecycle is not installed; run {install_action}")
    raise NodeServiceError(f"managed lifecycle installation is stale; run {upgrade_action}")


class Adapter(Protocol):
    def doctor(self) -> int: ...
    def install(self, *, force: bool = False) -> int: ...
    def start(self) -> int: ...
    def status(self, run_id: str = "", json_output: bool = False) -> int: ...
    def logs(self, lines: int = 100) -> int: ...
    def stop(self, bound_pid: int | None = None, launch_id: str = "") -> int: ...
    def stop_for_upgrade(self) -> int: ...
    def restart(self) -> int: ...
    def upgrade(self) -> int: ...
    def uninstall(self) -> int: ...


@dataclass
class SystemdAdapter:
    profile: object

    @property
    def unit(self) -> str:
        return f"awf-node-{_safe_name(self.profile.name)}.service"

    @property
    def definition(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / self.unit

    def _require_linger(self) -> None:
        result = _run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger", "--value"])
        if result.stdout.strip().lower() != "yes":
            raise NodeServiceError(
                "systemd user lingering is disabled; run "
                f"loginctl enable-linger {getpass.getuser()}"
            )

    def doctor(self) -> int:
        self._require_linger()
        return 0

    def install(self, *, force: bool = False) -> int:
        if _guard_install(self.profile, "systemd", force=force):
            return 0
        self._require_linger()
        _atomic_write(self.definition, _render_systemd(self.profile, self.unit).encode())
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", self.unit])
        _write_install_record(self.profile, "systemd", self.definition, {"manager_id": self.unit})
        return 0

    def start(self) -> int:
        _require_installed(self.profile, "systemd")
        self._require_linger()
        _run(["systemctl", "--user", "start", self.unit])
        _wait_bound(self.profile)
        return self.status()

    def status(self, run_id: str = "", json_output: bool = False) -> int:
        _require_installed(self.profile, "systemd")
        result = _run(["systemctl", "--user", "is-active", self.unit], check=False)
        if result.returncode == 0 and result.stdout.strip() == "active":
            return _bound_listener_status(self.profile)
        return _inactive_manager_status(self.profile, "systemd")

    def logs(self, lines: int = 100) -> int:
        result = _run(["journalctl", "--user", "-u", self.unit, "-n", str(lines), "--no-pager"])
        _write_console_text(result.stdout, end="")
        return 0

    def stop(self, bound_pid: int | None = None) -> int:
        _require_installed(self.profile, "systemd")
        if _bound_live_listener_pid(self.profile) is None:
            return 0
        _run(["systemctl", "--user", "stop", self.unit])
        return _after_manager_stop(self.profile)

    def restart(self) -> int:
        self.stop()
        return self.start()

    def upgrade(self) -> int:
        self.stop_for_upgrade()
        self.install(force=True)
        return self.start()

    def stop_for_upgrade(self) -> int:
        _require_upgrade_target(self.profile, "systemd", self.unit)
        if _bound_live_listener_pid(self.profile) is None:
            return 0
        _run(["systemctl", "--user", "stop", self.unit])
        return _after_manager_stop(self.profile)

    def uninstall(self) -> int:
        _require_installed(self.profile, "systemd")
        if _bound_live_listener_pid(self.profile) is not None:
            _run(["systemctl", "--user", "stop", self.unit])
            _after_manager_stop(self.profile)
        _run(["systemctl", "--user", "disable", self.unit], check=False)
        self.definition.unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
        _remove_install_record(self.profile)
        return 0


@dataclass
class LaunchdAdapter:
    profile: object

    @property
    def label(self) -> str:
        return f"com.agentworkflow.node.{_safe_name(self.profile.name)}"

    @property
    def definition(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"

    @property
    def domain(self) -> str:
        return f"gui/{os.getuid()}"

    def doctor(self) -> int:
        return 0

    def install(self, *, force: bool = False) -> int:
        if _guard_install(self.profile, "launchd", force=force):
            return 0
        _atomic_write(self.definition, _render_launchd(self.profile, self.label))
        _run(["launchctl", "bootout", self.domain, str(self.definition)], check=False)
        _run(["launchctl", "bootstrap", self.domain, str(self.definition)])
        _run(["launchctl", "disable", f"{self.domain}/{self.label}"], check=False)
        _write_install_record(self.profile, "launchd", self.definition, {"manager_id": self.label})
        return 0

    def start(self) -> int:
        _require_installed(self.profile, "launchd")
        _run(["launchctl", "enable", f"{self.domain}/{self.label}"])
        _run(["launchctl", "kickstart", f"{self.domain}/{self.label}"])
        _wait_bound(self.profile)
        return self.status()

    def status(self, run_id: str = "", json_output: bool = False) -> int:
        _require_installed(self.profile, "launchd")
        result = _run(["launchctl", "print", f"{self.domain}/{self.label}"], check=False)
        if result.returncode == 0:
            return _listener_status_code(self.profile)
        return _inactive_manager_status(self.profile, "launchd")

    def logs(self, lines: int = 100) -> int:
        return _tail_file(self.profile.log_path, lines)

    def stop(self, bound_pid: int | None = None, launch_id: str = "") -> int:
        _require_installed(self.profile, "launchd")
        if _bound_live_listener_pid(self.profile) is None:
            return 0
        _run(["launchctl", "disable", f"{self.domain}/{self.label}"])
        _run(["launchctl", "kill", "SIGTERM", f"{self.domain}/{self.label}"], check=False)
        return _after_manager_stop(self.profile)

    def restart(self) -> int:
        self.stop()
        return self.start()

    def upgrade(self) -> int:
        self.stop_for_upgrade()
        self.install(force=True)
        return self.start()

    def stop_for_upgrade(self) -> int:
        _require_upgrade_target(self.profile, "launchd", self.label)
        if _bound_live_listener_pid(self.profile) is None:
            return 0
        _run(["launchctl", "disable", f"{self.domain}/{self.label}"])
        _run(["launchctl", "kill", "SIGTERM", f"{self.domain}/{self.label}"], check=False)
        return _after_manager_stop(self.profile)

    def uninstall(self) -> int:
        _require_installed(self.profile, "launchd")
        if _bound_live_listener_pid(self.profile) is not None:
            _run(["launchctl", "disable", f"{self.domain}/{self.label}"])
            _run(["launchctl", "kill", "SIGTERM", f"{self.domain}/{self.label}"], check=False)
            _after_manager_stop(self.profile)
        _run(["launchctl", "bootout", self.domain, str(self.definition)], check=False)
        self.definition.unlink(missing_ok=True)
        _remove_install_record(self.profile)
        return 0


@dataclass
class TaskSchedulerAdapter:
    profile: object
    run_command: object | None = None
    current_user: str | None = None

    @property
    def task_name(self) -> str:
        return rf"\AgentWorkflow-awf-node-{_safe_name(self.profile.name)}"

    @property
    def definition(self) -> Path:
        return _service_dir(self.profile) / "task.xml"

    def _require_interactive_user(self) -> str:
        user = self.current_user or _interactive_console_user()
        if not user:
            raise NodeServiceError(
                "Task Scheduler managed lifecycle requires an interactive console user"
            )
        if os.name == "nt" and not _same_windows_user(user, _current_windows_user()):
            raise NodeServiceError(
                "Task Scheduler managed lifecycle requires the installer identity "
                "to match the active console user"
            )
        return user

    def _call(self, argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if self.run_command is None:
            return _run(argv, check=check)
        output = self.run_command(argv, check=check)
        if isinstance(output, subprocess.CompletedProcess):
            return output
        return subprocess.CompletedProcess(argv, 0, str(output or ""), "")

    def doctor(self) -> int:
        self._require_interactive_user()
        return 0

    def install(self, *, force: bool = False) -> int:
        if _guard_install(self.profile, "task-scheduler", force=force):
            return 0
        user = self._require_interactive_user()
        _atomic_write(self.definition, _render_task_scheduler(self.profile, user))
        create_argv = [
            "schtasks.exe",
            "/Create",
            "/TN",
            self.task_name,
            "/XML",
            str(self.definition),
            "/F",
        ]
        self._call(create_argv)
        _write_install_record(
            self.profile,
            "task-scheduler",
            self.definition,
            {"manager_id": self.task_name, "interactive_user": user},
        )
        return 0

    def start(self) -> int:
        _require_installed(self.profile, "task-scheduler")
        self._require_interactive_user()
        self._call(["schtasks.exe", "/Run", "/TN", self.task_name])
        if self.run_command is not None:
            return 0
        _wait_bound(self.profile)
        return self.status()

    def status(self, run_id: str = "", json_output: bool = False) -> dict[str, object]:
        if self.run_command is None:
            _require_installed(self.profile, "task-scheduler")
        result = self._call(
            ["schtasks.exe", "/Query", "/TN", self.task_name],
            check=False,
        )
        if self.run_command is not None:
            return {"manager": "task-scheduler", "localized_output_ignored": True}
        if result.returncode != 0:
            raise NodeServiceError(f"Task Scheduler task is unavailable: {self.task_name}")
        code = _listener_status_code(self.profile)
        return {
            "manager": "task-scheduler",
            "localized_output_ignored": True,
            "exit_code": code,
        }

    def logs(self, lines: int = 100) -> int:
        if self.run_command is not None:
            self._call(["schtasks.exe", "/Query", "/TN", self.task_name])
            return 0
        return _tail_file(self.profile.log_path, lines)

    def stop(self, bound_pid: int | None = None, launch_id: str = "") -> int:
        if self.run_command is None:
            _require_installed(self.profile, "task-scheduler")
        pid = bound_pid if bound_pid is not None else _bound_live_listener_pid(self.profile)
        if pid is not None:
            self._call(["taskkill.exe", "/PID", str(pid), "/T", "/F"])
        self._call(["schtasks.exe", "/End", "/TN", self.task_name], check=False)
        if self.run_command is not None:
            return 0
        return _after_manager_stop(self.profile)

    def restart(self) -> int:
        self.stop()
        return self.start()

    def upgrade(self) -> int:
        self.stop_for_upgrade()
        self.install(force=True)
        return self.start()

    def stop_for_upgrade(self) -> int:
        _require_upgrade_target(self.profile, "task-scheduler", self.task_name)
        pid = _bound_live_listener_pid(self.profile)
        if pid is not None:
            self._call(["taskkill.exe", "/PID", str(pid), "/T", "/F"])
        self._call(["schtasks.exe", "/End", "/TN", self.task_name], check=False)
        if self.run_command is None:
            return _after_manager_stop(self.profile)
        return 0

    def uninstall(self) -> int:
        self.stop()
        self._call(["schtasks.exe", "/Delete", "/TN", self.task_name, "/F"])
        self.definition.unlink(missing_ok=True)
        _remove_install_record(self.profile)
        return 0


def _interactive_console_user() -> str:
    override = os.environ.get("AWF_INTERACTIVE_CONSOLE_USER")
    if override:
        return override
    if os.name != "nt":
        return getpass.getuser()
    try:
        return _windows_interactive_console_user()
    except NodeServiceError:
        raise
    except Exception as exc:
        raise NodeServiceError("cannot resolve the interactive Windows console user") from exc


def _windows_interactive_console_user() -> str:
    import ctypes
    from ctypes import wintypes

    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WTSGetActiveConsoleSessionId.argtypes = []
    kernel32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
    wtsapi32.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    wtsapi32.WTSFreeMemory.restype = None
    session_id = kernel32.WTSGetActiveConsoleSessionId()
    if session_id == 0xFFFFFFFF:
        return ""
    user = _wts_query_string(wtsapi32, session_id, 5)
    if not user:
        return ""
    domain = _wts_query_string(wtsapi32, session_id, 7)
    return f"{domain}\\{user}" if domain else user


def _wts_query_string(wtsapi32, session_id: int, info_class: int) -> str:
    import ctypes
    from ctypes import wintypes

    buffer = wintypes.LPWSTR()
    size = wintypes.DWORD()
    ok = wtsapi32.WTSQuerySessionInformationW(
        None,
        wintypes.DWORD(session_id),
        info_class,
        ctypes.byref(buffer),
        ctypes.byref(size),
    )
    if not ok:
        return ""
    try:
        return buffer.value or ""
    finally:
        if buffer:
            wtsapi32.WTSFreeMemory(buffer)


def _current_windows_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME", "") or getpass.getuser()
    return f"{domain}\\{name}" if domain else name


def _same_windows_user(left: str, right: str) -> bool:
    left_folded = left.strip().casefold()
    right_folded = right.strip().casefold()
    if not left_folded or not right_folded:
        return False
    if left_folded == right_folded:
        return True
    return left_folded.rsplit("\\", 1)[-1] == right_folded.rsplit("\\", 1)[-1]


def _bound_listener_status(profile) -> int:
    from agent_workflow import node

    snapshot = node._listener_snapshot(profile)
    if snapshot.get("status") != "running":
        raise NodeServiceError("manager is active but listener identity/lease is not bound")
    return 0


def _listener_status_code(profile) -> int:
    from agent_workflow import node

    snapshot = node._listener_snapshot(profile)
    status = snapshot.get("status")
    if status == "running":
        return 0
    if status == "stopped":
        print(f"profile={profile.name} managed=stopped")
        return 3
    raise NodeServiceError(f"managed listener is degraded: {status}")


def _inactive_manager_status(profile, manager: str) -> int:
    from agent_workflow import node

    snapshot = node._listener_snapshot(profile)
    if snapshot.get("status") == "stopped":
        print(f"profile={profile.name} managed=stopped")
        return 3
    raise NodeServiceError(f"{manager} is inactive while listener state is not stopped")


def _bound_live_listener_pid(profile) -> int | None:
    """Return the exact bound root PID that a local managed stop may terminate."""
    from agent_workflow import node

    record = node._process_record(profile)
    lease = node._listener_lease(profile)
    if not record and not lease:
        return None
    if not record or not lease:
        raise NodeServiceError("managed stop refused incomplete listener state")
    if not _managed_record_matches_profile(profile, record):
        raise NodeServiceError("managed stop refused profile identity drift")
    pid = record.get("pid")
    launch_id = record.get("launch_id", "")
    if not isinstance(pid, int) or pid < 1 or not isinstance(launch_id, str) or not launch_id:
        raise NodeServiceError("managed stop refused invalid process identity")
    if not node._live_lease_matches(profile, lease, pid, launch_id):
        raise NodeServiceError("managed stop refused an unbound live listener")
    if not _process_creation_identity_matches(record, pid):
        raise NodeServiceError("managed stop refused Windows process creation identity drift")
    return pid


def _managed_record_matches_profile(profile, record: dict[str, object]) -> bool:
    from agent_workflow import node

    return bool(
        node._record_matches_profile(profile, record)
        and record.get("state_root") == str(profile.state_root)
        and record.get("state_root_sha256") == node.state_root_binding(profile.state_root)
    )


def _process_creation_identity_matches(
    record: dict[str, object],
    pid: int,
    *,
    required: bool = os.name == "nt",
) -> bool:
    if not required:
        return True
    from agent_workflow import node

    recorded_creation = record.get("process_creation_filetime")
    live_creation = node._windows_process_creation_filetime(pid)
    return bool(
        isinstance(recorded_creation, int)
        and live_creation is not None
        and recorded_creation == live_creation
    )


def _wait_bound(profile, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _bound_listener_status(profile)
            return
        except NodeServiceError:
            time.sleep(0.05)
    raise NodeServiceError("manager started but listener identity/lease readiness timed out")


def _after_manager_stop(profile, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _clear_exact_dead_stale_state(profile):
            return 0
        time.sleep(0.05)
    if _clear_exact_dead_stale_state(profile):
        return 0
    raise NodeServiceError(
        "manager stop did not converge to an exact dead listener record and lease"
    )


def _clear_exact_dead_stale_state(profile) -> bool:
    from agent_workflow import node

    record = node._process_record(profile)
    lease = node._listener_lease(profile)
    if not record and not lease:
        return True
    if not record or not lease:
        return False
    launch_id = record.get("launch_id", "")
    if not _managed_record_matches_profile(profile, record):
        return False
    if not isinstance(launch_id, str) or not launch_id:
        return False
    if not node._lease_matches(profile, lease, record.get("pid"), launch_id):
        return False
    related_pids = [record.get("pid"), lease.get("pid")]
    if any(node._pid_alive(pid) for pid in related_pids):
        return False
    profile.process_path.unlink(missing_ok=True)
    (profile.state_root / "listeners" / f"{profile.role}.json").unlink(missing_ok=True)
    return True


def _tail_file(path: Path, lines: int) -> int:
    if lines < 1 or lines > 10000:
        raise NodeServiceError("--lines must be between 1 and 10000")
    try:
        content = _decode_utf8(path.read_bytes()).splitlines()
    except OSError as exc:
        raise NodeServiceError(f"listener log is unavailable: {path}") from exc
    for line in content[-lines:]:
        _write_console_text(line)
    return 0


def adapter_for(profile) -> Adapter:
    manager = resolve_manager(str(profile.lifecycle.get("manager", "auto")))
    if manager == "task-scheduler":
        return TaskSchedulerAdapter(profile)
    if manager == "launchd":
        return LaunchdAdapter(profile)
    if manager == "systemd":
        return SystemdAdapter(profile)
    raise NodeServiceError(f"unsupported managed lifecycle manager: {manager}")


def run_action(profile, action: str, **kwargs) -> int:
    adapter = adapter_for(profile)
    handler = getattr(adapter, action, None)
    if handler is None:
        raise NodeServiceError(f"unsupported managed lifecycle action: {action}")
    return int(handler(**kwargs))


def _task_reconcile(profile_value: str, log_value: str) -> int:
    """Task Scheduler entry point with shell-free append-only file logging."""
    from agent_workflow import node

    log_path = Path(log_value).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        saved_stdout = os.dup(1)
    except OSError:
        saved_stdout = None
    try:
        saved_stderr = os.dup(2)
    except OSError:
        saved_stderr = None
    try:
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            windows_handles = _redirect_windows_standard_handles(log.fileno())
            try:
                with redirect_stdout(log), redirect_stderr(log):
                    try:
                        profile = node.load_profile(profile_value)
                        if profile.log_path != log_path:
                            raise node.NodeError(
                                "task reconcile log path drifted from the installed profile"
                            )
                        return node.reconcile(profile)
                    except (node.NodeError, NodeServiceError, OSError) as exc:
                        log.write(f"ERROR: task reconcile failed: {exc}\n")
                        return 1
            finally:
                _restore_windows_standard_handles(windows_handles)
    finally:
        if saved_stdout is not None:
            os.dup2(saved_stdout, 1)
            os.close(saved_stdout)
        if saved_stderr is not None:
            os.dup2(saved_stderr, 2)
            os.close(saved_stderr)


def _redirect_windows_standard_handles(file_descriptor: int):
    if os.name != "nt":
        return None
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel32.SetStdHandle.restype = wintypes.BOOL
    identifiers = (-11, -12)
    previous = tuple(kernel32.GetStdHandle(identifier) for identifier in identifiers)
    native_handle = wintypes.HANDLE(msvcrt.get_osfhandle(file_descriptor))
    for identifier in identifiers:
        if not kernel32.SetStdHandle(identifier, native_handle):
            raise NodeServiceError("cannot bind Windows scheduler standard handles")
    return kernel32, identifiers, previous


def _restore_windows_standard_handles(binding) -> None:
    if binding is None:
        return
    kernel32, identifiers, previous = binding
    for identifier, handle in zip(identifiers, previous, strict=True):
        kernel32.SetStdHandle(identifier, handle)


def _main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) == 3 and values[0] == "task-reconcile":
        return _task_reconcile(values[1], values[2])
    raise NodeServiceError("expected task-reconcile <absolute-profile.json> <absolute-log-path>")


if __name__ == "__main__":
    raise SystemExit(_main())
