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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

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
        return (
            Path(str(configured)).expanduser().resolve()
            if configured
            else default_state_root()
        )

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
        return (
            Path(str(configured)).expanduser().resolve()
            if configured
            else default_config_path()
        )

    @property
    def digest(self) -> str:
        body = json.dumps(self.values, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / (
        "agent-workflow"
    )


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


def _lease_matches(profile: NodeProfile, lease: dict[str, object] | None, pid: object) -> bool:
    return bool(
        lease
        and lease.get("pid") == pid
        and lease.get("role") == profile.role
        and os.path.normcase(str(lease.get("repo", "")))
        == os.path.normcase(str(profile.repo))
    )


def _wait_for_listener_lease(profile: NodeProfile, process, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise NodeError(f"listener exited during startup; inspect {profile.log_path}")
        if _lease_matches(profile, _listener_lease(profile), process.pid):
            return
        time.sleep(0.05)
    raise NodeError(f"listener readiness timed out; inspect {profile.log_path}")


def _wait_for_stop(profile: NodeProfile, pid: int, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid) or not _lease_matches(profile, _listener_lease(profile), pid):
            return True
        time.sleep(0.05)
    return False


def _pid_alive(pid: object) -> bool:
    _, awf_listen = _operations_modules()
    return bool(awf_listen._pid_alive(pid))


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


def _load_runtime_config(profile: NodeProfile) -> tuple[dict[str, str], Path]:
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
    return config, repo


def doctor(profile: NodeProfile) -> int:
    _load_runtime_config(profile)
    record = _process_record(profile)
    state = "running" if record and _pid_alive(record.get("pid")) else "stopped"
    print(
        f"profile={profile.name} role={profile.role} readiness=pass listener={state} "
        f"repo={profile.repo}"
    )
    print("remote_dispatch=not_proven; use the existing Fast/Deep preflight for dispatch authority")
    return 0


def _listener_argv(profile: NodeProfile) -> list[str]:
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
    return argv


def start(profile: NodeProfile) -> int:
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
    with profile.log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            _listener_argv(profile),
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
        "profile": str(profile.path),
        "profile_sha256": profile.digest,
        "role": profile.role,
        "repo": str(profile.repo),
        "started_at": utc_now(),
    }
    _atomic_write(profile.process_path, record)
    try:
        _wait_for_listener_lease(profile, process)
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


def status(profile: NodeProfile) -> int:
    record = _process_record(profile)
    if not record:
        print(f"profile={profile.name} role={profile.role} listener=stopped")
        return 3
    if record.get("profile_sha256") != profile.digest:
        raise NodeError("profile changed after listener start; stop using the original profile")
    pid = record.get("pid")
    alive = _pid_alive(pid) and _lease_matches(profile, _listener_lease(profile), pid)
    print(
        f"profile={profile.name} role={profile.role} "
        f"listener={'running' if alive else 'stale'} pid={record.get('pid')}"
    )
    print(f"repo={profile.repo} log={profile.log_path}")
    return 0 if alive else 3


def stop(profile: NodeProfile) -> int:
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
    if not _pid_alive(pid):
        profile.process_path.unlink(missing_ok=True)
        print(f"profile={profile.name} listener=stopped stale_record=removed")
        return 0
    if not _lease_matches(profile, _listener_lease(profile), pid):
        raise NodeError("live listener lease does not match this profile; refusing to signal")
    if os.name == "nt":
        os.kill(pid, signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(pid, signal.SIGINT)
    if not _wait_for_stop(profile, pid):
        raise NodeError(f"listener did not stop after local interrupt; inspect {profile.log_path}")
    profile.process_path.unlink(missing_ok=True)
    print(f"stopped profile={profile.name} pid={pid}")
    return 0


def logs(profile: NodeProfile, lines: int) -> int:
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


def run(command: str, profile_value: str, *, lines: int = 100) -> int:
    try:
        profile = load_profile(profile_value)
        handlers = {
            "doctor": lambda: doctor(profile),
            "start": lambda: start(profile),
            "status": lambda: status(profile),
            "stop": lambda: stop(profile),
            "logs": lambda: logs(profile, lines),
        }
        return handlers[command]()
    except (NodeError, OSError) as exc:
        print(f"ERROR: node {command} failed: {exc}", file=sys.stderr)
        return 1
