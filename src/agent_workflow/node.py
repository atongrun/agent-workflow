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
from agent_workflow.state_root import resolve_state_root, state_root_binding

PROFILE_FORMAT = "awf.node-profile.v1"
INSTALLED_PROFILE_FORMAT = "awf.node-installed-profile.v1"
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
READINESS_FORMAT = "awf.node-readiness.v2"
MAX_READINESS_TTL_SECONDS = 86400
LISTENER_START_TIMEOUT_SECONDS = 15


class NodeError(RuntimeError):
    """A credential-safe local node lifecycle failure."""


class TransientBusReadinessError(NodeError):
    """A bounded pre-listener Agent Bus health failure."""


@dataclass(frozen=True)
class NodeProfile:
    path: Path
    values: dict[str, object]
    source_path: Path | None = None
    source_aliases: tuple[Path, ...] = ()

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
        return resolve_state_root(str(self.values["state_root"]))

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

    @property
    def authoring_path(self) -> Path:
        return self.source_path or self.path


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
    bus_capabilities: tuple[str, ...]
    bus_provenance_sha256: str
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


def _safe_profile_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in name)


def _installed_profiles_root() -> Path:
    return default_config_home() / "installed-profiles"


def _profile_source_key(path: Path) -> str:
    normalized = os.path.normcase(str(path.expanduser().resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_registry_path(path: Path) -> Path:
    return _installed_profiles_root() / "registry" / f"source-{_profile_source_key(path)}.json"


def _name_registry_path(name: str) -> Path:
    return _installed_profiles_root() / "registry" / f"name-{_safe_profile_name(name)}.json"


def _snapshot_path(profile: NodeProfile) -> Path:
    digest = profile.digest.removeprefix("sha256:")
    return (
        _installed_profiles_root()
        / "snapshots"
        / _safe_profile_name(profile.name)
        / f"{digest}.json"
    )


def _stage_installed_profile(profile: NodeProfile) -> NodeProfile:
    """Write or verify the immutable credential-free snapshot used by native managers."""
    path = _snapshot_path(profile)
    if path.exists():
        installed = load_profile(str(path))
        if installed.digest != profile.digest or installed.values != profile.values:
            raise NodeError("installed profile snapshot digest/content mismatch")
    else:
        _atomic_write(path, profile.values)
        installed = load_profile(str(path))
    return NodeProfile(
        path=installed.path,
        values=installed.values,
        source_path=profile.authoring_path,
    )


def _registry_value(profile: NodeProfile, aliases: tuple[Path, ...]) -> dict[str, object]:
    sources = sorted(
        {str(profile.authoring_path.resolve()), *(str(alias.resolve()) for alias in aliases)}
    )
    return {
        "format": INSTALLED_PROFILE_FORMAT,
        "name": profile.name,
        "original_source": str(profile.authoring_path.resolve()),
        "source_aliases": sources,
        "installed_profile": str(profile.path.resolve()),
        "profile_sha256": profile.digest,
    }


def _commit_installed_profile(profile: NodeProfile, *, aliases: tuple[Path, ...] = ()) -> None:
    all_aliases = (*profile.source_aliases, *aliases)
    value = _registry_value(profile, all_aliases)
    for source_value in value["source_aliases"]:
        source = Path(str(source_value))
        alias_value = dict(value)
        alias_value["requested_source"] = str(source)
        _atomic_write(_source_registry_path(source), alias_value)
    _atomic_write(_name_registry_path(profile.name), value)


def _registry_candidates(value: str) -> list[tuple[Path, Path | None]]:
    resolved = resolve_profile_path(value)
    candidates = [(_source_registry_path(resolved), resolved)]
    raw = Path(value).expanduser()
    if not raw.is_absolute() and raw.parent == Path(".") and raw.suffix != ".json":
        candidates.append((_name_registry_path(value), None))
    return candidates


def load_installed_profile(value: str) -> NodeProfile | None:
    """Resolve one exact installed binding without scanning or repairing durable state."""
    for registry_path, requested_source in _registry_candidates(value):
        if not registry_path.exists():
            continue
        try:
            record = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise NodeError(f"installed profile registry is unreadable: {registry_path}") from exc
        if not isinstance(record, dict) or record.get("format") != INSTALLED_PROFILE_FORMAT:
            raise NodeError(f"installed profile registry is invalid: {registry_path}")
        if requested_source is not None and record.get("requested_source") != str(
            requested_source.resolve()
        ):
            raise NodeError("installed profile source binding drifted")
        aliases = record.get("source_aliases")
        if (
            not isinstance(aliases, list)
            or not aliases
            or not all(isinstance(alias, str) and Path(alias).is_absolute() for alias in aliases)
        ):
            raise NodeError("installed profile source aliases are invalid")
        if requested_source is not None and str(requested_source.resolve()) not in aliases:
            raise NodeError("installed profile source alias is not bound to this snapshot")
        snapshot = Path(str(record.get("installed_profile", ""))).expanduser().resolve()
        root = _installed_profiles_root().resolve()
        if snapshot == root or not snapshot.is_relative_to(root):
            raise NodeError("installed profile registry points outside the durable profile root")
        installed = load_profile(str(snapshot))
        if installed.digest != record.get("profile_sha256") or installed.name != record.get("name"):
            raise NodeError("installed profile snapshot identity drifted")
        source = Path(str(record.get("original_source", ""))).expanduser().resolve()
        return NodeProfile(
            path=installed.path,
            values=installed.values,
            source_path=source,
            source_aliases=tuple(Path(alias).resolve() for alias in aliases),
        )
    return None


def _load_operational_profile(value: str) -> NodeProfile:
    source: NodeProfile | None = None
    source_error: NodeError | None = None
    try:
        source = load_profile(value)
    except NodeError as exc:
        source_error = exc
    if source is not None and source.lifecycle_mode == "session":
        return source
    installed = None
    if source is not None and source.path.is_relative_to(_installed_profiles_root().resolve()):
        installed = load_installed_profile(source.name)
        if installed is None or installed.path != source.path:
            raise NodeError("durable installed profile is not the current registered snapshot")
    if installed is None:
        installed = load_installed_profile(value)
    if installed is not None:
        return installed
    if source is not None:
        return source
    assert source_error is not None
    raise NodeError(
        f"{source_error}; no exact durable installed profile binding exists for "
        f"{resolve_profile_path(value)}"
    ) from source_error


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
        raise NodeError("Pi is not a supported coder tool")
    if profile.role == "architect" and profile.values["tool"] not in {"none", "pi"}:
        raise NodeError("architect tool must be Pi or the internal no-model terminal consumer")
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
    recorded_root = lease.get("state_root") if lease else None
    recorded_binding = lease.get("state_root_sha256") if lease else None
    root_matches = bool(
        (recorded_root is None and recorded_binding is None)
        or (
            recorded_root == str(profile.state_root)
            and recorded_binding == state_root_binding(profile.state_root)
        )
    )
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
        and root_matches
    )


def _record_matches_profile(profile: NodeProfile, record: dict[str, object]) -> bool:
    expected = {
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "role": profile.role,
        "repo": str(profile.repo),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        return False
    recorded_root = record.get("state_root")
    recorded_binding = record.get("state_root_sha256")
    return bool(
        (recorded_root is None and recorded_binding is None)
        or (
            recorded_root == str(profile.state_root)
            and recorded_binding == state_root_binding(profile.state_root)
        )
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


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise NodeError("Agent Bus executable provenance is unreadable") from exc
    return "sha256:" + digest.hexdigest()


def probe_agent_bus_client(executable: str) -> dict[str, object]:
    """Prove the required structured-listener capability without connecting to a server."""
    _awf_config, awf_listen = _operations_modules()
    resolved = _resolved_executable(executable)
    if not Path(resolved).is_file():
        raise NodeError("Agent Bus executable is unavailable")
    try:
        probe = awf_listen.run_command(
            [resolved, "listen", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            allow_shell_wrapper=True,
        )
    except awf_listen.ExecutionFailure as exc:
        raise NodeError("Agent Bus structured argv capability probe failed") from exc
    output = (probe.stdout or "") + "\n" + (probe.stderr or "")
    if probe.returncode != 0 or "--on-argv" not in output:
        raise NodeError(
            "Agent Bus client lacks agent-bus.listen.on-argv.v1; install a compatible client"
        )
    provenance = {
        "executable_sha256": _file_sha256(resolved),
        "listen_help_sha256": _version_sha256(probe.stdout or "", probe.stderr or ""),
    }
    return {
        "executable": resolved,
        "capabilities": ("agent-bus.listen.on-argv.v1",),
        "provenance": provenance,
        "provenance_sha256": "sha256:"
        + hashlib.sha256(
            json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "version": "unreported; capability-probed",
    }


def _local_readiness(profile: NodeProfile) -> LocalReadiness:
    inherited_root = os.environ.get("AWF_STATE_ROOT")
    if inherited_root and resolve_state_root(inherited_root) != profile.state_root:
        raise NodeError("local readiness failed; profile state root conflicts with environment")
    inherited_binding = os.environ.get("AWF_STATE_ROOT_SHA256", "")
    if inherited_binding and inherited_binding != state_root_binding(profile.state_root):
        raise NodeError(
            "local readiness failed; profile state-root binding conflicts with environment"
        )
    awf_config, awf_listen = _operations_modules()
    try:
        config = awf_config.load_config(profile.config_path)
        repo = awf_listen.check_workspace_readiness(
            profile.repo,
            profile.role,
            require_clean=profile.role in {"coder", "reviewer"} or profile.values["tool"] != "none",
        )
    except (awf_config.ConfigError, SystemExit) as exc:
        raise NodeError("local readiness failed; profile, config, or workspace is invalid") from exc
    required = {"AGENT_BUS_URL", ROLE_TOKEN[profile.role]}
    missing = sorted(key for key in required if not config.get(key))
    if missing:
        raise NodeError("local readiness failed; required Bus configuration is incomplete")
    bus = awf_config.native_executable(config.get("AWF_BUS_BIN", "agent-bus"))
    if not (shutil.which(bus) or Path(bus).is_file()):
        raise NodeError("local readiness failed; Agent Bus executable is unavailable")
    bus_facts = probe_agent_bus_client(bus)
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
        raise TransientBusReadinessError(
            "local readiness failed; Agent Bus health probe failed"
        ) from exc
    if bus_probe.returncode != 0:
        raise TransientBusReadinessError("local readiness failed; Agent Bus health probe failed")
    tool = ""
    tool_version_sha256 = ""
    if profile.values["tool"] != "none":
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
        bus_executable=str(bus_facts["executable"]),
        bus_capabilities=tuple(bus_facts["capabilities"]),
        bus_provenance_sha256=str(bus_facts["provenance_sha256"]),
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
    digest_matches = bool(record and _record_matches_profile(profile, record))
    launch_id = record.get("launch_id", "") if record else ""
    bound = bool(record and digest_matches and _live_lease_matches(profile, lease, pid, launch_id))
    return {
        "status": "running" if bound else "stale" if record else "stopped",
        "pid": pid,
        "profile_sha256": record.get("profile_sha256", "") if record else "",
        "state_root_sha256": state_root_binding(profile.state_root),
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
        "state_root": {
            "source": "node_profile",
            "sha256": state_root_binding(profile.state_root),
        },
        "config_sha256": config_sha256,
        "repo": str(readiness.repo),
        "bus_executable": readiness.bus_executable,
        "bus_capabilities": readiness.bus_capabilities,
        "bus_provenance_sha256": readiness.bus_provenance_sha256,
        "tool_executable": readiness.tool_executable,
        "tool_version_sha256": readiness.tool_version_sha256,
        "listener": listener,
    }
    body = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(("awf-node-readiness-v1\0" + body).encode()).hexdigest()


def _preflight_fact(profile: NodeProfile, observed_at: datetime) -> dict[str, object]:
    path = profile.state_root / "preflight" / "latest-deep.json"
    if not path.is_file():
        return {
            "dispatch_capable": False,
            "status": "missing",
            "source": "fast/deep-preflight",
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        expires_at = datetime.fromisoformat(str(value["expires_at"]))
    except (OSError, UnicodeError, KeyError, ValueError, json.JSONDecodeError):
        return {
            "dispatch_capable": None,
            "status": "unknown",
            "source": "fast/deep-preflight",
        }
    if expires_at.tzinfo is None:
        return {
            "dispatch_capable": None,
            "status": "unknown",
            "source": "fast/deep-preflight",
        }
    if expires_at <= observed_at:
        return {
            "dispatch_capable": False,
            "status": "stale",
            "source": "fast/deep-preflight",
            "expires_at": expires_at.isoformat(),
        }
    return {
        "dispatch_capable": None,
        "status": "not_evaluated",
        "source": "fast/deep-preflight",
        "expires_at": expires_at.isoformat(),
    }


def lifecycle_facts(
    profile: NodeProfile,
    *,
    configured: bool | None = None,
    connected: bool | None = None,
    observed_at: datetime | None = None,
    valid_until: datetime | None = None,
    listener: dict[str, object] | None = None,
) -> dict[str, object]:
    """Assemble orthogonal lifecycle facts without inferring one fact from another."""
    from agent_workflow import node_service

    observed = observed_at or _now()
    if listener is None:
        listener = _listener_snapshot(profile)
    if profile.lifecycle_mode == "managed":
        installation = node_service.installation_snapshot(profile)
    else:
        installation = {
            "source": "lifecycle_mode",
            "manager": "none",
            "installed": None,
            "status": "not_applicable",
        }
    running_status = str(listener.get("status", "unknown"))
    running = {"running": True, "unknown": None}.get(running_status, False)
    preflight = _preflight_fact(profile, observed)
    facts = {
        "format": "awf.node-lifecycle.v1",
        "configured": configured,
        "installed": installation["installed"],
        "running": running,
        "connected": connected,
        "dispatch_capable": preflight["dispatch_capable"],
        "installation": installation,
        "running_observation": {
            "source": "node_process_record+listener_lease+pid_probe",
            "status": running_status,
        },
        "connection_observation": {
            "source": "agent_bus_doctor" if connected is not None else "not_observed",
            "status": (
                "connected"
                if connected is True
                else "disconnected"
                if connected is False
                else "unknown"
            ),
        },
        "preflight": preflight,
    }
    if valid_until is not None and connected is not None:
        facts["connection_observation"]["valid_until"] = valid_until.isoformat()
    facts["next_legal_action"] = _next_lifecycle_action(profile, facts)
    return facts


def _node_action(profile: NodeProfile, action: str) -> dict[str, object]:
    profile_arg = str(profile.path.resolve())
    argv = ["awf", "node", action, "--profile", profile_arg]
    return {"id": action, "argv": argv, "command": subprocess.list2cmdline(argv)}


def _next_lifecycle_action(profile: NodeProfile, facts: dict[str, object]) -> dict[str, object]:
    installed = facts["installed"]
    if profile.lifecycle_mode == "managed" and installed is False:
        return _node_action(profile, "install")
    if profile.lifecycle_mode == "managed" and installed is None:
        installation = facts["installation"]
        if installation["status"] == "stale":
            return _node_action(profile, "upgrade")
    running_observation = facts["running_observation"]
    if running_observation["status"] == "stale":
        return _node_action(profile, "stop")
    if facts["running"] is False:
        return _node_action(profile, "start")
    if facts["connected"] is not True:
        return _node_action(profile, "doctor")
    if facts["dispatch_capable"] is not True:
        return {"id": "run_fast_deep_preflight", "command": "run Fast/Deep Preflight"}
    return {"id": "remote_dispatch_allowed", "command": "remote dispatch allowed"}


def doctor_report(
    profile: NodeProfile,
    readiness: LocalReadiness,
    *,
    ttl_seconds: int,
    observed_at: datetime,
) -> dict[str, object]:
    if ttl_seconds < 1 or ttl_seconds > MAX_READINESS_TTL_SECONDS:
        raise NodeError(f"--ttl-seconds must be between 1 and {MAX_READINESS_TTL_SECONDS}")
    valid_until = observed_at + timedelta(seconds=ttl_seconds)
    listener = _listener_snapshot(profile)
    lifecycle = lifecycle_facts(
        profile,
        configured=True,
        connected=True,
        observed_at=observed_at,
        valid_until=valid_until,
        listener=listener,
    )
    tool_status = "not_applicable" if profile.values["tool"] == "none" else "pass"
    return {
        "format": READINESS_FORMAT,
        "observed_at": observed_at.isoformat(),
        "valid_until": valid_until.isoformat(),
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
        "state_root": {
            "source": "node_profile",
            "sha256": state_root_binding(profile.state_root),
        },
        "fingerprint": _readiness_fingerprint(profile, readiness, listener),
        **{
            name: lifecycle[name]
            for name in (
                "configured",
                "installed",
                "running",
                "connected",
                "dispatch_capable",
            )
        },
        "lifecycle": lifecycle,
        "listener": listener,
        "layers": [
            {"id": "profile", "status": "pass"},
            {"id": "configuration", "status": "pass"},
            {
                "id": "workspace",
                "status": "pass",
                "scope": (
                    "source"
                    if profile.role == "architect" and profile.values["tool"] == "none"
                    else "dedicated_role"
                ),
            },
            {
                "id": "agent_bus",
                "status": "pass",
                "capabilities": list(readiness.bus_capabilities),
                "provenance_sha256": readiness.bus_provenance_sha256,
            },
            {
                "id": "model_tool",
                "status": tool_status,
                "version_sha256": readiness.tool_version_sha256,
                "model_invoked": False,
            },
        ],
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
    lifecycle = report["lifecycle"]
    print(f"profile={profile.name} role={profile.role} repo={profile.repo}")
    print(
        "lifecycle: "
        + " ".join(
            f"{name}={_truth_label(lifecycle[name])}"
            for name in ("configured", "installed", "running", "connected", "dispatch_capable")
        )
        + f" installation_status={lifecycle['installation']['status']}"
        + f" running_observation={lifecycle['running_observation']['status']}"
        + f" preflight={lifecycle['preflight']['status']}"
    )
    print(f"next_legal_action={lifecycle['next_legal_action']['command']}")
    return 0


def _truth_label(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


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
    if values.get("finding_enabled"):
        argv.append("--enable-finding")
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
    installed = _stage_installed_profile(profile)
    desired_exists = desired_state_path(installed).exists()
    result = _managed_action(installed, "install")
    _commit_installed_profile(installed)
    if not desired_exists:
        write_desired_state(installed, "stopped")
    return result


def restart(profile: NodeProfile) -> int:
    write_desired_state(profile, "stopped")
    _managed_action(profile, "stop")
    write_desired_state(profile, "running")
    return _managed_action(profile, "start")


def _transition_desired_profile(
    current: NodeProfile,
    target: NodeProfile,
    state: str,
) -> None:
    _, awf_listen = _operations_modules()
    try:
        with awf_listen.control_plane_lock(_desired_lock_path(current)):
            previous = _read_desired_state(current)
            value = {
                "format": "awf.node-desired-state.v1",
                "state": state,
                "profile": str(target.path),
                "profile_sha256": target.digest,
                "generation": int(previous.get("generation", 0)) + 1,
            }
            _atomic_write(desired_state_path(target), value)
    except awf_listen.ControlPlaneDenied as exc:
        raise NodeError("managed desired state lock is unavailable") from exc


def upgrade(profile: NodeProfile, *, replacement: NodeProfile | None = None) -> int:
    if replacement is not None:
        stable = (
            ("name", profile.name, replacement.name),
            ("role", profile.role, replacement.role),
            ("repo", profile.repo, replacement.repo),
            ("state_root", profile.state_root, replacement.state_root),
            ("lifecycle", profile.lifecycle, replacement.lifecycle),
        )
        changed = [name for name, current, proposed in stable if current != proposed]
        if changed:
            raise NodeError(
                "managed upgrade cannot change installed identity fields: " + ", ".join(changed)
            )
    write_desired_state(profile, "stopped")
    _managed_action(profile, "stop_for_upgrade")
    target = _stage_installed_profile(replacement or profile)
    _managed_action(target, "install", force=True)
    aliases = tuple(
        source
        for source in {profile.authoring_path, *profile.source_aliases}
        if source != target.authoring_path
    )
    _commit_installed_profile(target, aliases=aliases)
    _transition_desired_profile(profile, target, "running")
    return _managed_action(target, "start")


def uninstall(profile: NodeProfile) -> int:
    write_desired_state(profile, "stopped")
    result = _managed_action(profile, "uninstall")
    registry_paths = {
        _source_registry_path(source)
        for source in {profile.authoring_path, *profile.source_aliases}
    }
    registry_paths.add(_name_registry_path(profile.name))
    for path in registry_paths:
        path.unlink(missing_ok=True)
    return result


def start(profile: NodeProfile, *, allow_session_bound: bool = False) -> int:
    if profile.lifecycle_mode == "managed":
        from agent_workflow import node_service

        node_service.require_installed(profile)
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
        incumbent = str(existing.get("profile", "unknown"))
        raise NodeError(
            f"node role is already owned by profile={incumbent} pid={existing.get('pid')}; "
            f"run awf node stop --profile {incumbent} before starting another owner"
        )
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
        "state_root": str(profile.state_root),
        "state_root_sha256": state_root_binding(profile.state_root),
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
        incumbent = str(existing.get("profile", "unknown"))
        raise NodeError(
            f"node role is already owned by profile={incumbent} pid={existing.get('pid')}; "
            f"run awf node stop --profile {incumbent} before starting another owner"
        )
    record = {
        "format": "awf.node-process.v1",
        "pid": os.getpid(),
        "launch_id": launch_id,
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "state_root": str(profile.state_root),
        "state_root_sha256": state_root_binding(profile.state_root),
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
    from agent_workflow import node_service

    node_service._clear_exact_dead_stale_state(profile)
    snapshot = _listener_snapshot(profile)
    if snapshot.get("status") == "running":
        return 0
    result = foreground(profile)
    if result == 0 and _read_desired_state(profile).get("state") != "stopped":
        write_desired_state(profile, "stopped")
    return result


def status(
    profile: NodeProfile,
    run_id: str = "",
    *,
    json_output: bool = False,
    explain: bool = False,
) -> int:
    try:
        record = _process_record(profile)
    except NodeError:
        record = None
    if record and not _record_matches_profile(profile, record):
        raise NodeError("profile changed after listener start; stop using the original profile")
    from agent_workflow import status as factual_status

    value = factual_status.snapshot(profile, run_id)
    if json_output:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        if explain:
            factual_status.print_human(value, explain=True)
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
    if not _record_matches_profile(profile, record):
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
    explain: bool = False,
    ttl_seconds: int = 3600,
    allow_session_bound: bool = False,
) -> int:
    try:
        if command == "install":
            profile = load_profile(profile_value)
        else:
            profile = _load_operational_profile(profile_value)
        replacement = None
        if command == "upgrade":
            try:
                candidate = load_profile(profile_value)
            except NodeError:
                candidate = None
            if candidate is not None and candidate.path != profile.path:
                replacement = candidate
        handlers = {
            "doctor": lambda: doctor(profile, json_output=json_output, ttl_seconds=ttl_seconds),
            "foreground": lambda: foreground(profile),
            "reconcile": lambda: reconcile(profile),
            "install": lambda: install(profile),
            "start": lambda: start(profile, allow_session_bound=allow_session_bound),
            "status": lambda: status(
                profile,
                run_id,
                json_output=json_output,
                explain=explain,
            ),
            "stop": lambda: stop(profile),
            "logs": lambda: logs(profile, lines),
            "restart": lambda: restart(profile),
            "upgrade": lambda: upgrade(profile, replacement=replacement),
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
    if not _record_matches_profile(profile, record):
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
