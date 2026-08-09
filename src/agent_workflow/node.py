"""Thin, local lifecycle surface for one Agent Workflow role listener."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from agent_workflow import __version__
from agent_workflow.node_service import NodeServiceError
from agent_workflow.resources import authority_manifest_path, operations_dir, schemas_dir

PROFILE_FORMAT = "awf.node-profile.v1"
ROLE_TOKEN = {
    "architect": "AWF_ARCH_TOKEN",
    "coder": "AWF_CODER_TOKEN",
    "reviewer": "AWF_REVIEWER_TOKEN",
}
TOOL_CONFIG = {
    "codex": ("AWF_CODEX_BIN", "codex"),
    "opencode": ("AWF_OPENCODE_BIN", "opencode"),
    "pi": ("AWF_PI_BIN", "pi"),
}
READINESS_FORMAT = "awf.node-readiness.v1"
MAX_READINESS_TTL_SECONDS = 86400
LISTENER_START_TIMEOUT_SECONDS = 15


class NodeError(RuntimeError):
    """A credential-safe local node lifecycle failure."""


@dataclass(frozen=True)
class NodeProfile:
    path: Path
    values: dict[str, object]

    @property
    def name(self) -> str:
        return str(self.values["name"])

    @property
    def role(self) -> str:
        return str(self.values["role"])

    @property
    def repo(self) -> Path:
        return Path(str(self.values["repo"])).expanduser().resolve()

    @property
    def state_root(self) -> Path:
        configured = self.values.get("state_root")
        return Path(str(configured)).expanduser().resolve() if configured else default_state_root()

    @property
    def node_dir(self) -> Path:
        return self.state_root / "nodes" / self.name

    @property
    def process_path(self) -> Path:
        return self.node_dir / "process.json"

    @property
    def log_path(self) -> Path:
        configured = self.values.get("log_file")
        return (
            Path(str(configured)).expanduser().resolve()
            if configured
            else self.node_dir / "listener.log"
        )

    @property
    def config_path(self) -> Path:
        configured = self.values.get("config")
        return Path(str(configured)).expanduser().resolve() if configured else default_config_path()

    @property
    def digest(self) -> str:
        body = json.dumps(self.values, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()

    @property
    def lifecycle(self) -> dict[str, object]:
        value = self.values.get("lifecycle")
        return value if isinstance(value, dict) else {"mode": "session"}

    @property
    def lifecycle_mode(self) -> str:
        return str(self.lifecycle.get("mode", "session"))


def lifecycle_mode(profile: NodeProfile) -> str:
    return profile.lifecycle_mode


def lifecycle_settings(profile: NodeProfile) -> dict[str, object]:
    return dict(profile.lifecycle)


def desired_state_path(profile: NodeProfile) -> Path:
    return profile.node_dir / "desired-state.json"


def _desired_lock_path(profile: NodeProfile) -> Path:
    return profile.node_dir / ".desired-state.lock"


def _read_desired_state(profile: NodeProfile) -> dict[str, object]:
    path = desired_state_path(profile)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "format": "awf.node-desired-state.v1",
            "state": "stopped",
            "profile": str(profile.path),
            "profile_sha256": profile.digest,
            "generation": 0,
        }
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NodeError(f"managed desired state is unreadable: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != "awf.node-desired-state.v1":
        raise NodeError(f"managed desired state is invalid: {path}")
    if value.get("profile") != str(profile.path) or value.get("profile_sha256") != profile.digest:
        raise NodeError("managed desired state profile drifted; run start or upgrade")
    if value.get("state") not in {"running", "stopped"}:
        raise NodeError("managed desired state must be running or stopped")
    return value


def write_desired_state(
    profile: NodeProfile,
    state: str,
    *,
    generation: int | None = None,
) -> dict[str, object]:
    if state not in {"running", "stopped"}:
        raise NodeError("managed desired state must be running or stopped")
    _, awf_listen = _operations_modules()
    try:
        with awf_listen.control_plane_lock(_desired_lock_path(profile)):
            if generation is None:
                current = _read_desired_state(profile)
                generation = int(current.get("generation", 0)) + 1
            value = {
                "format": "awf.node-desired-state.v1",
                "state": state,
                "profile": str(profile.path),
                "profile_sha256": profile.digest,
                "generation": generation,
            }
            _atomic_write(desired_state_path(profile), value)
            return value
    except awf_listen.ControlPlaneDenied as exc:
        raise NodeError("managed desired state lock is unavailable") from exc


@dataclass(frozen=True)
class LocalReadiness:
    config: dict[str, str]
    repo: Path
    bus_executable: str
    tool_executable: str
    tool_version_sha256: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def default_config_home() -> Path:
    if os.name == "nt":
        root = os.environ.get("APPDATA")
        if not root:
            raise NodeError("APPDATA is required to resolve a named profile")
        return Path(root) / "awf"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "awf"


def default_config_path() -> Path:
    configured = os.environ.get("AWF_DISPATCH_ENV")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else default_config_home() / "dispatch.env"
    )


def default_state_root() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        if not root:
            raise NodeError("LOCALAPPDATA is required to resolve node state")
        return Path(root) / "agent-workflow"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / ("agent-workflow")


def resolve_profile_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or candidate.parent != Path(".") or candidate.suffix == ".json":
        return candidate.resolve()
    return (default_config_home() / "profiles" / f"{value}.json").resolve()


def load_profile(value: str) -> NodeProfile:
    path = resolve_profile_path(value)
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NodeError(f"profile is unavailable or invalid: {path}") from exc
    schema_path = schemas_dir() / "node-profile.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NodeError("node profile schema is unavailable") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data), key=lambda item: list(item.path)
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "profile"
        raise NodeError(f"profile validation failed at {location}: {errors[0].message}")
    assert isinstance(data, dict)
    profile = NodeProfile(path=path, values=data)
    _validate_profile_semantics(profile)
    return profile


def _validate_profile_semantics(profile: NodeProfile) -> None:
    if not Path(str(profile.values["repo"])).expanduser().is_absolute():
        raise NodeError("profile repo must be an absolute path")
    for field in ("state_root", "log_file", "config"):
        value = profile.values.get(field)
        if value and not Path(str(value)).expanduser().is_absolute():
            raise NodeError(f"profile {field} must be an absolute path")
    for field, path in (("state_root", profile.state_root), ("log_file", profile.log_path)):
        if path == profile.repo or path.is_relative_to(profile.repo):
            raise NodeError(f"profile {field} must be outside the role repository")
    if profile.role == "coder" and profile.values["tool"] == "pi":
        raise NodeError("Pi is reviewer-only and cannot be selected for coder")
    if profile.role == "architect" and profile.values["tool"] != "none":
        raise NodeError("architect terminal handling is no-model; tool must be none")
    if profile.role != "architect" and profile.values["tool"] == "none":
        raise NodeError("coder and reviewer profiles require a model tool")
    if bool(profile.values.get("upstream_repo")) != bool(profile.values.get("head_repo")):
        raise NodeError("upstream_repo and head_repo must be configured together")
    on_type = str(profile.values.get("on_type", ""))
    if (not on_type or on_type.endswith("-v3")) and not profile.values.get("upstream_repo"):
        raise NodeError("v3 profiles require upstream_repo and head_repo")
    lifecycle = profile.lifecycle
    manager = str(lifecycle.get("manager", "auto"))
    if profile.lifecycle_mode == "session":
        unexpected = sorted(key for key in lifecycle if key != "mode")
        if unexpected:
            raise NodeError("session lifecycle accepts only mode")
        return
    if profile.lifecycle_mode != "managed":
        raise NodeError("lifecycle.mode must be session or managed")
    if lifecycle.get("scope", "user") != "user":
        raise NodeError("managed lifecycle currently supports only user scope")
    if manager not in {"auto", "launchd", "systemd", "task-scheduler"}:
        raise NodeError(f"unsupported managed lifecycle manager: {manager}")


def _operations_modules():
    directory = operations_dir()
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    import awf_config
    import awf_listen

    return awf_config, awf_listen


def _process_record(profile: NodeProfile) -> dict[str, object] | None:
    try:
        value = json.loads(profile.process_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NodeError(f"node process record is unreadable: {profile.process_path}") from exc
    if not isinstance(value, dict):
        raise NodeError(f"node process record is invalid: {profile.process_path}")
    return value


def _listener_lease(profile: NodeProfile) -> dict[str, object] | None:
    path = profile.state_root / "listeners" / f"{profile.role}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NodeError(f"listener lease is unreadable: {path}") from exc
    return value if isinstance(value, dict) else None


def _lease_matches(
    profile: NodeProfile,
    lease: dict[str, object] | None,
    pid: object,
    launch_id: object = "",
) -> bool:
    identity_matches = bool(
        lease
        and (
            lease.get("launch_id") == launch_id
            if isinstance(launch_id, str) and launch_id
            else lease.get("pid") == pid
        )
    )
    return bool(
        lease
        and identity_matches
        and lease.get("role") == profile.role
        and os.path.normcase(str(lease.get("repo", ""))) == os.path.normcase(str(profile.repo))
    )


def _live_lease_matches(
    profile: NodeProfile,
    lease: dict[str, object] | None,
    pid: object,
    launch_id: object = "",
    *,
    launcher_alive: bool | None = None,
) -> bool:
    if not _lease_matches(profile, lease, pid, launch_id):
        return False
    if launcher_alive is None:
        launcher_alive = _pid_alive(pid)
    return bool(launcher_alive and lease and _pid_alive(lease.get("pid")))


def _wait_for_listener_lease(
    profile: NodeProfile,
    process,
    launch_id: str,
    timeout: float = LISTENER_START_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        launcher_alive = process.poll() is None
        if not launcher_alive:
            raise NodeError(f"listener exited during startup; inspect {profile.log_path}")
        if _live_lease_matches(
            profile,
            _listener_lease(profile),
            process.pid,
            launch_id,
            launcher_alive=launcher_alive,
        ):
            return
        time.sleep(0.05)
    raise NodeError(f"listener readiness timed out; inspect {profile.log_path}")


def _wait_for_stop(
    profile: NodeProfile,
    pid: int,
    launch_id: object = "",
    timeout: float = 5,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lease = _listener_lease(profile)
        launcher_alive = _pid_alive(pid)
        listener_alive = bool(
            _lease_matches(profile, lease, pid, launch_id)
            and lease
            and _pid_alive(lease.get("pid"))
        )
        if not launcher_alive and not listener_alive:
            return True
        time.sleep(0.05)
    return False


def _pid_alive(pid: object) -> bool:
    _, awf_listen = _operations_modules()
    return bool(awf_listen._pid_alive(pid))


def _windows_process_creation_filetime(pid: int) -> int | None:
    """Return the kernel creation identity used to reject Windows PID reuse."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def _atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _version_sha256(stdout: str, stderr: str) -> str:
    body = (stdout + "\0" + stderr).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _resolved_executable(value: str) -> str:
    resolved = shutil.which(value)
    return str(Path(resolved).resolve()) if resolved else str(Path(value).resolve())


def _local_readiness(profile: NodeProfile) -> LocalReadiness:
    awf_config, awf_listen = _operations_modules()
    try:
        config = awf_config.load_config(profile.config_path)
        repo = awf_listen.check_workspace_readiness(profile.repo, profile.role)
    except (awf_config.ConfigError, SystemExit) as exc:
        raise NodeError("local readiness failed; profile, config, or workspace is invalid") from exc
    required = {"AGENT_BUS_URL", ROLE_TOKEN[profile.role]}
    missing = sorted(key for key in required if not config.get(key))
    if missing:
        raise NodeError("local readiness failed; required Bus configuration is incomplete")
    bus = awf_config.native_executable(config.get("AWF_BUS_BIN", "agent-bus"))
    if not (shutil.which(bus) or Path(bus).is_file()):
        raise NodeError("local readiness failed; Agent Bus executable is unavailable")
    environment = dict(os.environ)
    token = config[ROLE_TOKEN[profile.role]]
    environment.update(
        {
            "AGENT_BUS_URL": config["AGENT_BUS_URL"],
            "AGENT_BUS_TOKEN": token,
            "AGENT_BUS_AGENT": profile.role,
        }
    )
    import awf_network

    awf_network.add_url_host_to_no_proxy(environment, config["AGENT_BUS_URL"])
    try:
        bus_probe = awf_listen.run_command(
            [bus, "doctor"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            secrets=(token,),
            allow_shell_wrapper=True,
        )
    except awf_listen.ExecutionFailure as exc:
        raise NodeError("local readiness failed; Agent Bus health probe failed") from exc
    if bus_probe.returncode != 0:
        raise NodeError("local readiness failed; Agent Bus health probe failed")
    tool = ""
    tool_version_sha256 = ""
    if profile.role != "architect":
        key, default = TOOL_CONFIG[str(profile.values["tool"])]
        tool = awf_config.native_executable(config.get(key, default))
        if not (shutil.which(tool) or Path(tool).is_file()):
            raise NodeError("local readiness failed; selected model executable is unavailable")
        try:
            tool_probe = awf_listen.run_command(
                [tool, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                allow_shell_wrapper=True,
            )
        except awf_listen.ExecutionFailure as exc:
            raise NodeError("local readiness failed; selected model probe failed") from exc
        if tool_probe.returncode != 0:
            raise NodeError("local readiness failed; selected model probe failed")
        tool_version_sha256 = _version_sha256(tool_probe.stdout or "", tool_probe.stderr or "")
    return LocalReadiness(
        config=config,
        repo=repo,
        bus_executable=_resolved_executable(bus),
        tool_executable=_resolved_executable(tool) if tool else "",
        tool_version_sha256=tool_version_sha256,
    )


def _load_runtime_config(profile: NodeProfile) -> tuple[dict[str, str], Path]:
    readiness = _local_readiness(profile)
    return readiness.config, readiness.repo


def _listener_snapshot(profile: NodeProfile) -> dict[str, object]:
    try:
        record = _process_record(profile)
        lease = _listener_lease(profile)
    except NodeError:
        return {
            "status": "unknown",
            "pid": None,
            "profile_sha256": "",
            "lease_bound": False,
        }
    pid = record.get("pid") if record else None
    digest_matches = bool(record and record.get("profile_sha256") == profile.digest)
    launch_id = record.get("launch_id", "") if record else ""
    bound = bool(record and digest_matches and _live_lease_matches(profile, lease, pid, launch_id))
    return {
        "status": "running" if bound else "stale" if record else "stopped",
        "pid": pid,
        "profile_sha256": record.get("profile_sha256", "") if record else "",
        "lease_bound": bound,
    }


def _readiness_fingerprint(
    profile: NodeProfile,
    readiness: LocalReadiness,
    listener: dict[str, object],
) -> str:
    config_body = json.dumps(readiness.config, sort_keys=True, separators=(",", ":"))
    config_sha256 = hashlib.sha256(config_body.encode("utf-8")).hexdigest()
    selected = {
        "awf_version": __version__,
        "runtime": {
            "platform": sys.platform,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "operations_dir": str(operations_dir().resolve()),
        "profile_sha256": profile.digest,
        "config_sha256": config_sha256,
        "repo": str(readiness.repo),
        "bus_executable": readiness.bus_executable,
        "tool_executable": readiness.tool_executable,
        "tool_version_sha256": readiness.tool_version_sha256,
        "listener": listener,
    }
    body = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(("awf-node-readiness-v1\0" + body).encode()).hexdigest()


def doctor_report(
    profile: NodeProfile,
    readiness: LocalReadiness,
    *,
    ttl_seconds: int,
    observed_at: datetime,
) -> dict[str, object]:
    if ttl_seconds < 1 or ttl_seconds > MAX_READINESS_TTL_SECONDS:
        raise NodeError(f"--ttl-seconds must be between 1 and {MAX_READINESS_TTL_SECONDS}")
    listener = _listener_snapshot(profile)
    tool_status = "not_applicable" if profile.role == "architect" else "pass"
    return {
        "format": READINESS_FORMAT,
        "status": "ready",
        "observed_at": observed_at.isoformat(),
        "valid_until": (observed_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "scope": "operator-discovery-only",
        "awf_version": __version__,
        "runtime": {
            "platform": sys.platform,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "profile": {
            "name": profile.name,
            "role": profile.role,
            "tool": str(profile.values["tool"]),
            "model": str(profile.values.get("model", "")),
        },
        "profile_sha256": profile.digest,
        "fingerprint": _readiness_fingerprint(profile, readiness, listener),
        "listener": listener,
        "layers": [
            {"id": "profile", "status": "pass"},
            {"id": "configuration", "status": "pass"},
            {
                "id": "workspace",
                "status": "pass",
                "scope": "source" if profile.role == "architect" else "dedicated_role",
            },
            {"id": "agent_bus", "status": "pass"},
            {
                "id": "model_tool",
                "status": tool_status,
                "version_sha256": readiness.tool_version_sha256,
                "model_invoked": False,
            },
        ],
        "remote_dispatch": {
            "status": "not_proven",
            "required_gate": "fast/deep-preflight",
        },
        "invalidate_on": [
            "ttl_expired",
            "profile_or_selection_changed",
            "awf_or_tool_changed",
            "configuration_or_workspace_changed",
            "listener_or_bus_failure",
        ],
    }


def doctor(
    profile: NodeProfile,
    *,
    json_output: bool = False,
    ttl_seconds: int = 3600,
) -> int:
    if profile.lifecycle_mode == "managed":
        _managed_action(profile, "doctor")
    readiness = _local_readiness(profile)
    report = doctor_report(
        profile,
        readiness,
        ttl_seconds=ttl_seconds,
        observed_at=_now(),
    )
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    state = str(report["listener"]["status"])
    print(
        f"profile={profile.name} role={profile.role} readiness=pass listener={state} "
        f"repo={profile.repo}"
    )
    print("remote_dispatch=not_proven; use the existing Fast/Deep preflight for dispatch authority")
    return 0


def _listener_argv(profile: NodeProfile, launch_id: str = "") -> list[str]:
    values = profile.values
    argv = [
        sys.executable,
        str(operations_dir() / "awf_listen.py"),
        "--config",
        str(profile.config_path),
        "--authority-manifest",
        str(authority_manifest_path()),
        "--state-root",
        str(profile.state_root),
        "--role",
        profile.role,
        "--repo",
        str(profile.repo),
        "--tool",
        str(values["tool"]),
        "--base",
        str(values.get("base", "master")),
        "--upstream-remote",
        str(values.get("upstream_remote", "upstream")),
        "--head-remote",
        str(values.get("head_remote", "fork")),
        "--base-ref",
        str(values.get("base_ref", "main")),
        "--gh-bin",
        str(values.get("gh_bin", "gh")),
    ]
    for key, flag in (
        ("model", "--model"),
        ("on_type", "--on-type"),
        ("upstream_repo", "--upstream-repo"),
        ("head_repo", "--head-repo"),
    ):
        if values.get(key):
            argv.extend([flag, str(values[key])])
    if values.get("enable_preflight"):
        argv.append("--enable-preflight")
    if values.get("no_push"):
        argv.append("--no-push")
    if launch_id:
        argv.extend(["--node-launch-id", launch_id])
    return argv


def _inside_ssh_session() -> bool:
    return any(os.environ.get(key) for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"))


def render_managed_definition(profile: NodeProfile, *, manager: str) -> str:
    from agent_workflow import node_service

    return node_service.render_definition(profile, manager=manager)


def resolve_managed_manager(
    manager: str,
    *,
    platform: str = sys.platform,
    scope: str = "user",
) -> str:
    if scope != "user":
        raise NodeError("managed lifecycle currently supports only user scope")
    from agent_workflow import node_service

    return node_service.resolve_manager(manager, platform=platform)


def _resolve_managed_manager(profile: NodeProfile):
    from agent_workflow import node_service

    return node_service.adapter_for(profile)


def _managed_action(profile: NodeProfile, action: str, *args, **kwargs) -> int:
    if profile.lifecycle_mode != "managed":
        raise NodeError(f"node {action} requires lifecycle.mode=managed")
    manager = _resolve_managed_manager(profile)
    handler = getattr(manager, action, None)
    if handler is None:
        raise NodeError(f"managed lifecycle manager does not support {action}")
    result = handler(*args, **kwargs)
    if isinstance(result, dict):
        return 0
    return int(result)


def install(profile: NodeProfile) -> int:
    desired_exists = desired_state_path(profile).exists()
    result = _managed_action(profile, "install")
    if not desired_exists:
        write_desired_state(profile, "stopped")
    return result


def restart(profile: NodeProfile) -> int:
    write_desired_state(profile, "stopped")
    _managed_action(profile, "stop")
    write_desired_state(profile, "running")
    return _managed_action(profile, "start")


def upgrade(profile: NodeProfile) -> int:
    write_desired_state(profile, "stopped")
    _managed_action(profile, "stop_for_upgrade")
    _managed_action(profile, "install", force=True)
    write_desired_state(profile, "running")
    return _managed_action(profile, "start")


def uninstall(profile: NodeProfile) -> int:
    write_desired_state(profile, "stopped")
    return _managed_action(profile, "uninstall")


def start(profile: NodeProfile, *, allow_session_bound: bool = False) -> int:
    if profile.lifecycle_mode == "managed":
        write_desired_state(profile, "running")
        return _managed_action(profile, "start")
    if _inside_ssh_session() and not allow_session_bound:
        raise NodeError(
            "session-bound node start is unsafe inside SSH; use lifecycle.mode=managed, "
            "node foreground under an external supervisor, or --allow-session-bound temporarily"
        )
    _load_runtime_config(profile)
    _, awf_listen = _operations_modules()
    try:
        with awf_listen.control_plane_lock(profile.node_dir / ".lifecycle.lock"):
            return _start_locked(profile)
    except awf_listen.ControlPlaneDenied as exc:
        raise NodeError("node lifecycle lock is unavailable") from exc


def _start_locked(profile: NodeProfile) -> int:
    existing = _process_record(profile)
    if existing and _pid_alive(existing.get("pid")):
        raise NodeError(f"node already running with pid={existing.get('pid')}")
    if existing:
        profile.process_path.unlink(missing_ok=True)
    profile.log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    launch_id = uuid.uuid4().hex
    with profile.log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            _listener_argv(profile, launch_id),
            cwd=profile.repo,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            creationflags=flags,
        )
    record = {
        "format": "awf.node-process.v1",
        "pid": process.pid,
        "launch_id": launch_id,
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "role": profile.role,
        "repo": str(profile.repo),
        "started_at": utc_now(),
    }
    _atomic_write(profile.process_path, record)
    try:
        _wait_for_listener_lease(profile, process, launch_id)
    except NodeError:
        profile.process_path.unlink(missing_ok=True)
        if process.poll() is None:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGINT)
        raise
    print(f"started profile={profile.name} role={profile.role} pid={process.pid}")
    print(f"log={profile.log_path}")
    return 0


def _foreground_record(profile: NodeProfile, launch_id: str) -> None:
    existing = _process_record(profile)
    if existing and _pid_alive(existing.get("pid")):
        raise NodeError(f"node already running with pid={existing.get('pid')}")
    record = {
        "format": "awf.node-process.v1",
        "pid": os.getpid(),
        "launch_id": launch_id,
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "role": profile.role,
        "repo": str(profile.repo),
        "started_at": utc_now(),
        "lifecycle": "foreground",
    }
    if os.name == "nt":
        creation = _windows_process_creation_filetime(os.getpid())
        if creation is None:
            raise NodeError("cannot bind the managed Windows process creation identity")
        record["process_creation_filetime"] = creation
    _atomic_write(profile.process_path, record)


def _clear_foreground_record(profile: NodeProfile, launch_id: str) -> None:
    record = _process_record(profile)
    if record and record.get("pid") == os.getpid() and record.get("launch_id") == launch_id:
        profile.process_path.unlink(missing_ok=True)


def foreground(profile: NodeProfile) -> int:
    """Run the complete listener in this process for a native supervisor."""
    _local_readiness(profile)
    _, awf_listen = _operations_modules()
    launch_id = uuid.uuid4().hex
    _foreground_record(profile, launch_id)
    previous_sigterm = None

    def stop_on_sigterm(_signum, _frame):
        raise KeyboardInterrupt

    if os.name != "nt" and hasattr(signal, "SIGTERM"):
        previous_sigterm = signal.signal(signal.SIGTERM, stop_on_sigterm)
    result = 1
    try:
        result = int(awf_listen.main(_listener_argv(profile, launch_id)[2:]))
        return result
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        _clear_foreground_record(profile, launch_id)
        if profile.lifecycle_mode == "managed" and result == 0:
            write_desired_state(profile, "stopped")


def reconcile(profile: NodeProfile) -> int:
    if profile.lifecycle_mode != "managed":
        raise NodeError("node reconcile requires lifecycle.mode=managed")
    desired = _read_desired_state(profile)
    if desired["state"] == "stopped":
        return 0
    snapshot = _listener_snapshot(profile)
    if snapshot.get("status") == "running":
        return 0
    result = foreground(profile)
    if result == 0 and _read_desired_state(profile).get("state") != "stopped":
        write_desired_state(profile, "stopped")
    return result


def status(profile: NodeProfile, run_id: str = "", *, json_output: bool = False) -> int:
    if profile.lifecycle_mode == "managed":
        _managed_action(profile, "status")
    try:
        record = _process_record(profile)
    except NodeError:
        record = None
    if record and record.get("profile_sha256") != profile.digest:
        raise NodeError("profile changed after listener start; stop using the original profile")
    from agent_workflow import status as factual_status

    value = factual_status.snapshot(profile, run_id)
    if json_output:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        factual_status.print_human(value)
    listener = value.get("listener")
    return 0 if isinstance(listener, dict) and listener.get("status") == "running" else 3


def stop(profile: NodeProfile) -> int:
    if profile.lifecycle_mode == "managed":
        write_desired_state(profile, "stopped")
        return _managed_action(profile, "stop")
    _, awf_listen = _operations_modules()
    try:
        with awf_listen.control_plane_lock(profile.node_dir / ".lifecycle.lock"):
            return _stop_locked(profile)
    except awf_listen.ControlPlaneDenied as exc:
        raise NodeError("node lifecycle lock is unavailable") from exc


def _stop_locked(profile: NodeProfile) -> int:
    record = _process_record(profile)
    if not record:
        print(f"profile={profile.name} listener=stopped")
        return 0
    expected = {
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "role": profile.role,
        "repo": str(profile.repo),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise NodeError("process record does not match this profile; refusing to signal")
    pid = record.get("pid")
    if not isinstance(pid, int) or pid < 1:
        raise NodeError("process record PID is invalid; refusing to signal")
    lease = _listener_lease(profile)
    launch_id = record.get("launch_id", "")
    if not _pid_alive(pid):
        matching_listener_alive = bool(
            isinstance(launch_id, str)
            and launch_id
            and _lease_matches(profile, lease, pid, launch_id)
            and lease
            and _pid_alive(lease.get("pid"))
        )
        if matching_listener_alive:
            raise NodeError(
                "node launcher is not alive but its listener lease is still live; "
                "refusing to declare stopped"
            )
        profile.process_path.unlink(missing_ok=True)
        print(f"profile={profile.name} listener=stopped stale_record=removed")
        return 0
    if not _live_lease_matches(profile, lease, pid, launch_id):
        raise NodeError("live listener lease does not match this profile; refusing to signal")
    if os.name == "nt":
        os.kill(pid, signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(pid, signal.SIGINT)
    if not _wait_for_stop(profile, pid, launch_id):
        raise NodeError(f"listener did not stop after local interrupt; inspect {profile.log_path}")
    profile.process_path.unlink(missing_ok=True)
    print(f"stopped profile={profile.name} pid={pid}")
    return 0


def logs(profile: NodeProfile, lines: int) -> int:
    if profile.lifecycle_mode == "managed":
        return _managed_action(profile, "logs", lines)
    if lines < 1 or lines > 10000:
        raise NodeError("--lines must be between 1 and 10000")
    try:
        content = profile.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        raise NodeError(f"listener log is unavailable: {profile.log_path}") from None
    except OSError as exc:
        raise NodeError(f"listener log is unreadable: {profile.log_path}") from exc
    for line in content[-lines:]:
        print(line)
    return 0


def run(
    command: str,
    profile_value: str,
    *,
    lines: int = 100,
    run_id: str = "",
    json_output: bool = False,
    ttl_seconds: int = 3600,
    allow_session_bound: bool = False,
) -> int:
    try:
        profile = load_profile(profile_value)
        handlers = {
            "doctor": lambda: doctor(profile, json_output=json_output, ttl_seconds=ttl_seconds),
            "foreground": lambda: foreground(profile),
            "reconcile": lambda: reconcile(profile),
            "install": lambda: install(profile),
            "start": lambda: start(profile, allow_session_bound=allow_session_bound),
            "status": lambda: status(profile, run_id, json_output=json_output),
            "stop": lambda: stop(profile),
            "logs": lambda: logs(profile, lines),
            "restart": lambda: restart(profile),
            "upgrade": lambda: upgrade(profile),
            "uninstall": lambda: uninstall(profile),
        }
        return handlers[command]()
    except (NodeError, NodeServiceError, OSError) as exc:
        print(f"ERROR: node {command} failed: {exc}", file=sys.stderr)
        return 1


def _managed_stop_snapshot(manager, profile: NodeProfile) -> dict[str, object]:
    stop = getattr(manager, "stop", None)
    if stop is None:
        raise NodeError("managed stop fail closed: manager does not support stop")
    result = stop()
    if int(result or 0) != 0:
        raise NodeError("managed stop fail closed: manager stop returned a non-zero result")
    try:
        record = _process_record(profile)
    except NodeError:
        record = None
    return {
        "status": "stopped",
        "pid": record.get("pid") if record else None,
        "launch_id": record.get("launch_id", "") if record else "",
    }


def _clear_managed_stale_stop(profile: NodeProfile, snapshot: dict[str, object]) -> int:
    if snapshot.get("status") != "stopped":
        raise NodeError("managed stop degraded; fail closed before clearing listener state")
    record = _process_record(profile)
    lease = _listener_lease(profile)
    if not record and not lease:
        return 0
    if not record or not lease:
        raise NodeError("managed stop degraded; fail closed on incomplete listener state")
    launch_id = record.get("launch_id", "")
    expected = {
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "role": profile.role,
        "repo": str(profile.repo),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise NodeError("managed stop degraded; fail closed on profile drift")
    if snapshot.get("pid") != record.get("pid") or snapshot.get("launch_id") != launch_id:
        raise NodeError("managed stop degraded; fail closed on launch identity mismatch")
    if not isinstance(launch_id, str) or not launch_id:
        raise NodeError("managed stop degraded; fail closed on missing launch identity")
    if not _lease_matches(profile, lease, record.get("pid"), launch_id):
        raise NodeError("managed stop degraded; fail closed on lease mismatch")
    if _pid_alive(record.get("pid")) or _pid_alive(lease.get("pid")):
        raise NodeError("managed stop degraded; fail closed while listener PID is alive")
    profile.process_path.unlink(missing_ok=True)
    (profile.state_root / "listeners" / f"{profile.role}.json").unlink(missing_ok=True)
    return 0
