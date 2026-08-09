"""Native service-manager adapters for one foreground role listener."""

from __future__ import annotations

import getpass
import hashlib
import html
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class NodeServiceError(RuntimeError):
    """A credential-safe native service lifecycle failure."""


def resolve_manager(manager: str, *, platform: str = sys.platform, os_name: str = os.name) -> str:
    if manager != "auto":
        return manager
    if os_name == "nt" or platform == "win32":
        return "winsw"
    if platform == "darwin":
        return "launchd"
    if platform.startswith("linux"):
        return "systemd"
    raise NodeServiceError(f"no native service manager is supported on {platform}")


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


def _foreground_arguments(profile) -> list[str]:
    return [
        "-m",
        "agent_workflow.cli",
        "node",
        "foreground",
        "--profile",
        str(profile.path),
    ]


def _quoted_arguments(arguments: list[str]) -> str:
    return subprocess.list2cmdline(arguments)


def render_winsw(profile, *, service_id: str) -> str:
    executable = html.escape(str(Path(sys.executable).resolve()), quote=True)
    arguments = html.escape(_quoted_arguments(_foreground_arguments(profile)), quote=True)
    working = html.escape(str(profile.repo), quote=True)
    log_path = html.escape(str(profile.log_path.parent / "winsw"), quote=True)
    escaped_id = html.escape(service_id, quote=True)
    return f"""<service>
  <id>{escaped_id}</id>
  <name>Agent Workflow Node ({html.escape(profile.name)})</name>
  <description>Supervises one foreground Agent Workflow role listener.</description>
  <executable>{executable}</executable>
  <arguments>{arguments}</arguments>
  <workingdirectory>{working}</workingdirectory>
  <stoptimeout>15 sec</stoptimeout>
  <onfailure action="restart" delay="10 sec"/>
  <resetfailure>1 hour</resetfailure>
  <logpath>{log_path}</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>4</keepFiles>
  </log>
</service>
"""


def _render_systemd(profile, unit: str) -> str:
    values = [sys.executable, *_foreground_arguments(profile)]
    command = " ".join(_systemd_quote(value) for value in values)
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
            "ProgramArguments": [sys.executable, *_foreground_arguments(profile)],
            "WorkingDirectory": str(profile.repo),
            "RunAtLoad": False,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 10,
            "StandardOutPath": str(profile.log_path),
            "StandardErrorPath": str(profile.log_path),
        },
        sort_keys=True,
    )


def _run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NodeServiceError(f"service manager command failed: {argv[0]}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise NodeServiceError(f"service manager command failed: {argv[0]}{suffix}")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise NodeServiceError(f"service manager binary is unavailable: {path}") from exc
    return "sha256:" + digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
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
        "format": "awf.node-service-install.v1",
        "manager": manager,
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "definition": str(definition),
        "definition_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "python": str(Path(sys.executable).resolve()),
        "python_sha256": _sha256(Path(sys.executable).resolve()),
        "awf_version": __version__,
        **extra,
    }
    _atomic_write(
        profile.node_dir / "service" / "install.json",
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode(),
    )


def _install_record(profile) -> dict[str, object]:
    path = profile.node_dir / "service" / "install.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NodeServiceError(f"service install record is unavailable: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != "awf.node-service-install.v1":
        raise NodeServiceError(f"service install record is invalid: {path}")
    return value


def _require_installed(profile, manager: str) -> dict[str, object]:
    from agent_workflow import __version__

    record = _install_record(profile)
    expected = {
        "manager": manager,
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "python": str(Path(sys.executable).resolve()),
        "awf_version": __version__,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise NodeServiceError("service installation drifted; restore the profile or run upgrade")
    definition = Path(str(record.get("definition", "")))
    if not definition.is_file() or _sha256(definition) != record.get("definition_sha256"):
        raise NodeServiceError("installed service definition digest does not match its record")
    if _sha256(Path(sys.executable).resolve()) != record.get("python_sha256"):
        raise NodeServiceError("installed Python digest does not match its record; run upgrade")
    return record


def _guard_install(profile, manager: str, *, force: bool) -> None:
    path = profile.node_dir / "service" / "install.json"
    if not path.exists() or force:
        return
    _require_installed(profile, manager)


class Adapter(Protocol):
    def install(self, *, force: bool = False) -> int: ...
    def start(self) -> int: ...
    def status(self) -> int: ...
    def logs(self, *, lines: int = 100) -> int: ...
    def stop(self) -> int: ...
    def restart(self) -> int: ...
    def upgrade(self) -> int: ...
    def uninstall(self) -> int: ...


@dataclass
class SystemdAdapter:
    profile: object

    @property
    def unit(self) -> str:
        return f"awf-node-{self.profile.name}.service"

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

    def install(self, *, force: bool = False) -> int:
        _guard_install(self.profile, "systemd", force=force)
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

    def status(self) -> int:
        _require_installed(self.profile, "systemd")
        result = _run(["systemctl", "--user", "is-active", self.unit], check=False)
        if result.returncode != 0 or result.stdout.strip() != "active":
            raise NodeServiceError(f"systemd unit is not active: {self.unit}")
        return _bound_listener_status(self.profile)

    def logs(self, *, lines: int = 100) -> int:
        result = _run(["journalctl", "--user", "-u", self.unit, "-n", str(lines), "--no-pager"])
        print(result.stdout, end="")
        return 0

    def stop(self) -> int:
        _run(["systemctl", "--user", "stop", self.unit])
        return _wait_stopped(self.profile)

    def restart(self) -> int:
        _run(["systemctl", "--user", "restart", self.unit])
        return self.status()

    def upgrade(self) -> int:
        self.stop()
        self.install(force=True)
        return self.start()

    def uninstall(self) -> int:
        _run(["systemctl", "--user", "disable", "--now", self.unit], check=False)
        _wait_stopped(self.profile)
        self.definition.unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
        return 0


@dataclass
class LaunchdAdapter:
    profile: object

    @property
    def label(self) -> str:
        return f"com.agentworkflow.node.{self.profile.name}"

    @property
    def definition(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"

    @property
    def domain(self) -> str:
        return f"gui/{os.getuid()}"

    def install(self, *, force: bool = False) -> int:
        _guard_install(self.profile, "launchd", force=force)
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

    def status(self) -> int:
        _require_installed(self.profile, "launchd")
        _run(["launchctl", "print", f"{self.domain}/{self.label}"])
        return _bound_listener_status(self.profile)

    def logs(self, *, lines: int = 100) -> int:
        return _tail_file(self.profile.log_path, lines)

    def stop(self) -> int:
        _run(["launchctl", "disable", f"{self.domain}/{self.label}"])
        _run(["launchctl", "kill", "SIGTERM", f"{self.domain}/{self.label}"], check=False)
        return _wait_stopped(self.profile)

    def restart(self) -> int:
        self.stop()
        return self.start()

    def upgrade(self) -> int:
        self.stop()
        self.install(force=True)
        return self.start()

    def uninstall(self) -> int:
        _run(["launchctl", "bootout", self.domain, str(self.definition)], check=False)
        _wait_stopped(self.profile)
        self.definition.unlink(missing_ok=True)
        return 0


@dataclass
class WinSWAdapter:
    profile: object

    @property
    def service_id(self) -> str:
        return f"awf-node-{self.profile.name}"

    @property
    def directory(self) -> Path:
        return self.profile.node_dir / "service" / "winsw"

    @property
    def executable(self) -> Path:
        return self.directory / f"{self.service_id}.exe"

    @property
    def definition(self) -> Path:
        return self.directory / f"{self.service_id}.xml"

    @property
    def expected_account(self) -> str:
        return str(self.profile.lifecycle["service_account"])

    def _source_binary(self) -> Path:
        source = Path(str(self.profile.lifecycle["winsw_executable"])).expanduser().resolve()
        expected = str(self.profile.lifecycle["winsw_sha256"])
        actual = _sha256(source)
        if actual != expected:
            raise NodeServiceError("WinSW SHA-256 does not match the profile")
        return source

    def _require_account(self) -> None:
        result = _run(["sc.exe", "qc", self.service_id])
        line = next(
            (item for item in result.stdout.splitlines() if "SERVICE_START_NAME" in item), ""
        )
        actual = line.split(":", 1)[1].strip() if ":" in line else ""
        if not _account_matches(self.expected_account, actual):
            raise NodeServiceError(
                "WinSW service account is not bound; an administrator must run: "
                f"sc.exe config {self.service_id} obj= {self.expected_account} "
                "password= <prompted-secret>"
            )

    def _require_installed(self) -> dict[str, object]:
        record = _require_installed(self.profile, "winsw")
        if record.get("winsw_sha256") != _sha256(self.executable):
            raise NodeServiceError("installed WinSW digest does not match its record")
        return record

    def install(self, *, force: bool = False) -> int:
        _guard_install(self.profile, "winsw", force=force)
        source = self._source_binary()
        self.directory.mkdir(parents=True, exist_ok=True)
        if source != self.executable:
            shutil.copy2(source, self.executable)
        _atomic_write(
            self.definition,
            render_winsw(self.profile, service_id=self.service_id).encode("utf-8"),
        )
        _run([str(self.executable), "install"], check=False)
        self._require_account()
        _write_install_record(
            self.profile,
            "winsw",
            self.definition,
            {
                "manager_id": self.service_id,
                "service_account": self.expected_account,
                "winsw_sha256": _sha256(self.executable),
            },
        )
        return 0

    def start(self) -> int:
        self._require_installed()
        self._source_binary()
        self._require_account()
        _run([str(self.executable), "start"])
        _wait_bound(self.profile)
        return self.status()

    def status(self) -> int:
        self._require_installed()
        self._require_account()
        result = _run([str(self.executable), "status"], check=False)
        if result.returncode != 0 or "active" not in result.stdout.lower():
            raise NodeServiceError(f"WinSW service is not active: {self.service_id}")
        _require_windows_process_account(self.profile, self.expected_account)
        return _bound_listener_status(self.profile)

    def logs(self, *, lines: int = 100) -> int:
        candidates = [
            self.directory / f"{self.service_id}.out.log",
            self.directory / f"{self.service_id}.err.log",
            self.directory / f"{self.service_id}.wrapper.log",
        ]
        available = [path for path in candidates if path.is_file()]
        if not available:
            raise NodeServiceError(f"WinSW logs are unavailable under {self.directory}")
        for path in available:
            print(f"== {path.name} ==")
            _tail_file(path, lines)
        return 0

    def stop(self) -> int:
        from agent_workflow import node

        record = node._process_record(self.profile)
        identities = _windows_process_tree(record.get("pid")) if record else []
        _run([str(self.executable), "stop"])
        _wait_stopped(self.profile)
        survivors = [identity[0] for identity in identities if _windows_identity_alive(identity)]
        if survivors:
            raise NodeServiceError(
                f"WinSW stopped but bound process-tree members remain: {survivors}"
            )
        return 0

    def restart(self) -> int:
        self.stop()
        return self.start()

    def upgrade(self) -> int:
        self.stop()
        self.uninstall()
        self.install(force=True)
        return self.start()

    def uninstall(self) -> int:
        _run([str(self.executable), "stop"], check=False)
        _wait_stopped(self.profile)
        _run([str(self.executable), "uninstall"], check=False)
        return 0


def _account_matches(expected: str, actual: str) -> bool:
    expected_folded = expected.strip().casefold()
    actual_folded = actual.strip().casefold()
    if expected_folded.startswith(".\\"):
        return actual_folded.rsplit("\\", 1)[-1] == expected_folded[2:]
    return actual_folded == expected_folded


def _require_windows_process_account(profile, expected: str) -> None:
    from agent_workflow import node

    record = node._process_record(profile)
    if not record or not isinstance(record.get("pid"), int):
        raise NodeServiceError(
            "service manager is active but the listener process record is missing"
        )
    actual = _windows_process_account(int(record["pid"]))
    if not actual or not _account_matches(expected, actual):
        raise NodeServiceError("listener process account does not match the service profile")


def _windows_process_account(pid: int) -> str:
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.LookupAccountSidW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.LookupAccountSidW.restype = wintypes.BOOL
    process = kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return ""
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
            return ""
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            return ""
        sid = ctypes.c_void_p(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0])
        name_size = wintypes.DWORD(256)
        domain_size = wintypes.DWORD(256)
        name = ctypes.create_unicode_buffer(name_size.value)
        domain = ctypes.create_unicode_buffer(domain_size.value)
        sid_type = wintypes.DWORD()
        if not advapi32.LookupAccountSidW(
            None,
            sid,
            name,
            ctypes.byref(name_size),
            domain,
            ctypes.byref(domain_size),
            ctypes.byref(sid_type),
        ):
            return ""
        return f"{domain.value}\\{name.value}" if domain.value else name.value
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


def _windows_process_identity(pid: object) -> tuple[int, float] | None:
    if not isinstance(pid, int) or pid < 1:
        return None
    if os.name != "nt":
        return (pid, 0.0)
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    process = kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return None
    try:
        creation = FILETIME()
        exit_time = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not kernel32.GetProcessTimes(
            process,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        created = float((creation.high << 32) | creation.low)
        return (pid, created)
    finally:
        kernel32.CloseHandle(process)


def _windows_identity_alive(identity: tuple[int, float]) -> bool:
    current = _windows_process_identity(identity[0])
    return current == identity


def _windows_process_tree(root_pid: object) -> list[tuple[int, float]]:
    if not isinstance(root_pid, int) or root_pid < 1:
        return []
    if os.name != "nt":
        identity = _windows_process_identity(root_pid)
        return [identity] if identity else []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid = ctypes.c_void_p(-1).value
    if snapshot == invalid:
        raise NodeServiceError("cannot snapshot the Windows service process tree")
    parents: dict[int, int] = {}
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        present = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while present:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            present = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    selected = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in selected and pid not in selected:
                selected.add(pid)
                changed = True
    identities = [_windows_process_identity(pid) for pid in sorted(selected)]
    if any(identity is None for identity in identities):
        raise NodeServiceError("cannot bind every Windows service process-tree identity")
    return [identity for identity in identities if identity is not None]


def _bound_listener_status(profile) -> int:
    from agent_workflow import node

    snapshot = node._listener_snapshot(profile)
    if snapshot.get("status") != "running":
        raise NodeServiceError("service manager is active but listener identity/lease is not bound")
    return 0


def _wait_bound(profile, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _bound_listener_status(profile)
            return
        except NodeServiceError:
            time.sleep(0.05)
    raise NodeServiceError("service started but listener identity/lease readiness timed out")


def _require_stopped(profile) -> int:
    from agent_workflow import node

    snapshot = node._listener_snapshot(profile)
    lease = node._listener_lease(profile)
    record = node._process_record(profile)
    if snapshot.get("status") != "stopped" or lease or record:
        raise NodeServiceError("service manager stopped but a listener process or lease remains")
    return 0


def _wait_stopped(profile, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return _require_stopped(profile)
        except NodeServiceError:
            time.sleep(0.05)
    return _require_stopped(profile)


def _tail_file(path: Path, lines: int) -> int:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise NodeServiceError(f"listener log is unavailable: {path}") from exc
    for line in content[-lines:]:
        print(line)
    return 0


def adapter_for(profile) -> Adapter:
    manager = resolve_manager(str(profile.lifecycle.get("manager", "auto")))
    if manager == "winsw":
        return WinSWAdapter(profile)
    if manager == "launchd":
        return LaunchdAdapter(profile)
    if manager == "systemd":
        return SystemdAdapter(profile)
    raise NodeServiceError(f"unsupported service manager: {manager}")


def run_action(profile, action: str, **kwargs) -> int:
    adapter = adapter_for(profile)
    handler = getattr(adapter, action, None)
    if handler is None:
        raise NodeServiceError(f"unsupported service action: {action}")
    return int(handler(**kwargs))
