#!/usr/bin/env python3
"""awf_listen — start a cross-platform Agent Workflow role listener.

Whichever machine runs this becomes that role's worker: it connects to Agent Bus
and runs awf_role.py for each matching event. Replaces awf-listen.sh so the
executor side has no bash/cmd/WSL shell-dialect problems on Windows.

    python awf_listen.py --role coder    --repo /path/to/repo --tool opencode --model M
    python awf_listen.py --role reviewer --repo /path/to/repo --tool codex --base master

Config comes from the strict, shell-free Python loader (or an explicit environment):
    AGENT_BUS_URL, AWF_<ROLE>_TOKEN            (required)
    AWF_BUS_BIN                                (agent-bus binary; default: agent-bus)
    AWF_OPENCODE_BIN / AWF_CODEX_BIN / AWF_PI_BIN  (tool binaries; optional)

control:shutdown is built into `agent-bus listen`; the VPS can stop this listener
with `agent-bus send --to <role> --type control:shutdown`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from awf_config import ConfigError, default_config_path, load_into_environment, native_executable
from awf_control_plane import (
    ControlPlaneDenied,
    authorize_operation,
    default_state_root,
    load_authority_manifest,
)
from awf_control_plane import (
    _lock as control_plane_lock,
)

try:
    from awf_executor import ExecutionFailure
    from awf_executor import run as run_command
except ModuleNotFoundError:  # package import in tests
    from .awf_executor import ExecutionFailure
    from .awf_executor import run as run_command
from awf_network import add_url_host_to_no_proxy

from agent_workflow.state_root import state_root_binding

PREFLIGHT_REQUEST_TYPE = "control:awf-preflight-v1"
PREFLIGHT_RESULT_TYPE = "control:awf-preflight-result-v1"
PLAN_START_TYPE = "task:awf-plan-start-v1"

DEFAULT_ON_TYPE = {
    "architect": "decision:awf-ready-v3",
    "coder": "task:awf-impl-v3",
    "reviewer": "task:awf-review-v3",
}


def configure_network_bypass(environment: dict[str, str], bus_url: str) -> None:
    """Keep only the private Bus off host proxy routes."""
    add_url_host_to_no_proxy(environment, bus_url)


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            wait_timeout = 0x00000102
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_listener_lease(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _git_read(repo: Path, *args: str):
    try:
        return run_command(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except ExecutionFailure as exc:
        die(f"workspace readiness failed: cannot run Git: {exc}")


def check_workspace_readiness(
    repo: Path,
    role: str,
    *,
    require_clean: bool | None = None,
) -> Path:
    """Require a role-owned Git root before any event can be consumed."""
    resolved = repo.resolve()
    if not resolved.is_dir():
        die(f"repo not found: {resolved}")
    result = _git_read(resolved, "rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != "true":
        die(f"workspace readiness failed: not a Git worktree: {resolved}")
    top = _git_read(resolved, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != resolved:
        die(f"workspace ownership failed: --repo must name the Git root: {resolved}")
    if require_clean is None:
        require_clean = role in {"coder", "reviewer"}
    if require_clean:
        status = _git_read(resolved, "status", "--porcelain")
        if status.returncode != 0:
            die(f"workspace readiness failed: Git status unavailable: {resolved}")
        if status.stdout.strip():
            die(
                f"workspace ownership failed: role={role} requires a dedicated clean repo; "
                "operator files were left unchanged"
            )
    return resolved


def acquire_listener_lease(
    state_root: Path,
    role: str,
    repo: Path,
    *,
    launch_id: str = "",
) -> Path:
    """Claim one live role and one live role-scoped repository before Bus connect."""
    lease_dir = state_root.resolve() / "listeners"
    lease_dir.mkdir(parents=True, exist_ok=True)
    resolved_repo = os.path.normcase(str(repo.resolve()))
    own_path = lease_dir / f"{role}.json"

    with control_plane_lock(lease_dir / ".registry.lock"):
        for path in sorted(lease_dir.glob("*.json")):
            lease = _read_listener_lease(path)
            if lease is None:
                die(f"listener lease is unreadable; inspect before retrying: {path}")
            if not _pid_alive(lease.get("pid")):
                path.unlink(missing_ok=True)
                continue
            owner_role = str(lease.get("role", path.stem))
            owner_repo = os.path.normcase(str(lease.get("repo", "")))
            owner_pid = int(lease["pid"])
            if owner_role == role:
                die(
                    f"duplicate listener: role={role} already owned by pid={owner_pid} "
                    f"repo={owner_repo or '<unknown>'}"
                )
            if owner_repo == resolved_repo:
                die(
                    f"role-repo conflict: repo={resolved_repo} is owned by "
                    f"role={owner_role} pid={owner_pid}"
                )

        resolved_root = str(state_root.resolve())
        record = {
            "pid": os.getpid(),
            "role": role,
            "repo": resolved_repo,
            "state_root": resolved_root,
            "state_root_sha256": state_root_binding(state_root),
        }
        if launch_id:
            record["launch_id"] = launch_id
        try:
            fd = os.open(own_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            die(f"duplicate listener: role={role} lease appeared during startup")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    return own_path


def release_listener_lease(
    path: Path,
    role: str,
    repo: Path,
    *,
    launch_id: str = "",
) -> None:
    """Release only the exact lease created by this process."""
    expected = {
        "pid": os.getpid(),
        "role": role,
        "repo": os.path.normcase(str(repo.resolve())),
        "state_root": str(path.parent.parent.resolve()),
        "state_root_sha256": state_root_binding(path.parent.parent),
    }
    if launch_id:
        expected["launch_id"] = launch_id
    try:
        with control_plane_lock(path.parent / ".registry.lock"):
            lease = _read_listener_lease(path)
            if lease == expected:
                path.unlink(missing_ok=True)
    except (ControlPlaneDenied, OSError) as exc:
        print(f"awf_listen: listener lease cleanup deferred: {exc}", file=sys.stderr)


def die(msg: str):
    print(f"awf_listen: {msg}", file=sys.stderr)
    raise SystemExit(2)


def build_handler(
    python_exe: str,
    role_script: str,
    role: str,
    *,
    on_type: str = "",
    upstream_remote: str = "upstream",
    head_remote: str = "fork",
    state_root: Path | None = None,
) -> str:
    """Build the agent-bus --on handler command.

    This string exists only because Agent Bus currently accepts a handler
    template rather than structured handler argv. Path parts use the common
    double-quote subset; payload placeholders are substituted and shell-quoted
    by Agent Bus. Agent Workflow launches Agent Bus itself through awf_executor.
    """
    fields = _role_handler_fields(
        role,
        on_type=on_type,
        upstream_remote=upstream_remote,
        head_remote=head_remote,
        state_root=state_root,
        quote_paths=True,
    )
    return f'"{python_exe}" "{role_script}" {role} ' + " ".join(fields)


def _role_handler_fields(
    role: str,
    *,
    on_type: str = "",
    upstream_remote: str = "upstream",
    head_remote: str = "fork",
    state_root: Path | None = None,
    quote_paths: bool = False,
) -> list[str]:
    fields = [
        "--event-id",
        "{id}",
        "--input-type",
        "{type}",
        "--delivery-id",
        "{payload.awf_delivery_id}",
        "--payload-sha256",
        "{payload.awf_payload_sha256}",
        "--source-event-id",
        "{payload.awf_source_event_id}",
        "--branch",
        "{payload.branch}",
        "--card",
        "{payload.card}",
        "--commit",
        "{payload.commit}",
        "--model",
        "{payload.model}",
        "--tool",
        "{payload.tool}",
        "--report",
        "{payload.report}",
    ]
    if on_type.endswith("-v3"):
        fields += [
            "--provenance-version",
            "{payload.provenance_version}",
            "--upstream-repo",
            "{payload.upstream_repo}",
            "--upstream-remote",
            upstream_remote,
            "--base-ref",
            "{payload.base_ref}",
            "--base-sha",
            "{payload.base_sha}",
            "--head-repo",
            "{payload.head_repo}",
            "--head-remote",
            head_remote,
            "--head-ref",
            "{payload.head_ref}",
            "--head-sha",
            "{payload.head_sha}",
            "--pull-request",
            "{payload.pull_request}",
        ]
    if (
        role == "coder"
        and on_type
        in {
            "task:awf-rework",
            "task:awf-rework-v2",
            "task:awf-rework-v3",
        }
    ) or (role == "architect" and on_type.startswith("decision:awf-")):
        fields += [
            "--review-report",
            "{payload.review_report_path}",
            "--review-feedback",
            "{payload.review_report}",
        ]
    else:
        fields += ["--review-report", "{payload.review_report}"]
    if state_root is not None:
        state_root_value = f'"{state_root}"' if quote_paths else str(state_root)
        fields += [
            "--state-root",
            state_root_value,
            "--state-root-sha256",
            state_root_binding(state_root),
        ]
    return fields


def build_handler_argv(
    python_exe: str,
    role_script: str,
    role: str,
    *,
    on_type: str = "",
    upstream_remote: str = "upstream",
    head_remote: str = "fork",
    state_root: Path | None = None,
) -> list[str]:
    """Build the awf.handler-argv.v1 role handler argv for Agent Bus."""
    return [
        python_exe,
        role_script,
        role,
        *_role_handler_fields(
            role,
            on_type=on_type,
            upstream_remote=upstream_remote,
            head_remote=head_remote,
            state_root=state_root,
        ),
    ]


def build_preflight_handler(
    python_exe: str,
    preflight_script: str,
    command: str,
    *,
    config_path: Path,
    state_root: Path,
) -> str:
    """Build the narrow no-model control handler accepted by Agent Bus v1."""
    fields = _preflight_handler_fields(
        command,
        config_path=config_path,
        state_root=state_root,
        quote_paths=True,
    )
    return f'"{python_exe}" "{preflight_script}" {command} ' + " ".join(fields)


def _preflight_handler_fields(
    command: str,
    *,
    config_path: Path,
    state_root: Path,
    quote_paths: bool = False,
) -> list[str]:
    state_root_value = f'"{state_root}"' if quote_paths else str(state_root)
    fields = [
        "--event-id",
        "{id}",
        "--event-type",
        "{type}",
        "--probe-id",
        "{payload.probe_id}",
        "--fingerprint",
        "{payload.fingerprint}",
        "--source-role",
        "{payload.source_role}",
        "--target-role",
        "{payload.target_role}",
        "--state-root",
        state_root_value,
    ]
    if command == "handle-request":
        config_value = f'"{config_path}"' if quote_paths else str(config_path)
        fields += ["--config", config_value]
    else:
        fields += [
            "--request-event-id",
            "{payload.request_event_id}",
            "--request-child-rc",
            "{payload.request_child_rc}",
        ]
    return fields


def build_preflight_handler_argv(
    python_exe: str,
    preflight_script: str,
    command: str,
    *,
    config_path: Path,
    state_root: Path,
) -> list[str]:
    """Build the awf.handler-argv.v1 no-model Preflight handler argv."""
    return [
        python_exe,
        preflight_script,
        command,
        *_preflight_handler_fields(
            command,
            config_path=config_path,
            state_root=state_root,
        ),
    ]


def build_plan_start_handler_argv(
    python_exe: str,
    plan_script: str,
    *,
    repo: Path,
    profile_path: str,
    profile_sha256: str,
    tool: str,
    model: str,
    config_path: Path,
    authority_manifest: Path,
    state_root: Path,
    upstream_remote: str,
    head_remote: str,
    head_repo: str,
    gh_bin: str,
) -> list[str]:
    """Build the one structured Plan start handler without a new protocol."""
    return [
        python_exe,
        plan_script,
        "handle-start",
        "--run-id",
        "{payload.run_id}",
        "--mode",
        "{payload.mode}",
        "--plan-json",
        "{payload.plan}",
        "--architect-json",
        "{payload.architect}",
        "--coder-json",
        "{payload.coder}",
        "--reviewer-json",
        "{payload.reviewer}",
        "--payload-sha256",
        "{payload.awf_payload_sha256}",
        "--delivery-id",
        "{payload.awf_delivery_id}",
        "--repo",
        str(repo),
        "--state-root",
        str(state_root),
        "--profile",
        profile_path,
        "--profile-sha256",
        profile_sha256,
        "--tool",
        tool,
        "--model",
        model,
        "--config",
        str(config_path),
        "--authority-manifest",
        str(authority_manifest),
        "--upstream-remote",
        upstream_remote,
        "--head-remote",
        head_remote,
        "--head-repo",
        head_repo,
        "--gh-bin",
        gh_bin,
    ]


def handler_argv_json(argv: list[str]) -> str:
    """Serialize handler argv for agent-bus.listen.on-argv.v1."""
    return json.dumps([str(value) for value in argv], ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="awf_listen")
    p.add_argument("--role", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--profile-path", default="", help=argparse.SUPPRESS)
    p.add_argument("--profile-sha256", default="", help=argparse.SUPPRESS)
    p.add_argument("--tool", default="opencode")
    p.add_argument("--tool-executable", default="", help=argparse.SUPPRESS)
    p.add_argument("--model", default="")
    p.add_argument("--on-type", dest="on_type", default="")
    p.add_argument("--base", default="master")
    p.add_argument("--upstream-repo", default="")
    p.add_argument("--upstream-remote", default="upstream")
    p.add_argument("--head-repo", default="")
    p.add_argument("--head-remote", default="fork")
    p.add_argument("--base-ref", default="main")
    p.add_argument("--gh-bin", default="gh")
    p.add_argument("--state-root", type=Path, default=None)
    p.add_argument("--node-launch-id", default="", help=argparse.SUPPRESS)
    p.add_argument(
        "--enable-preflight",
        action="store_true",
        help="register the no-model disposable Preflight control handlers",
    )
    p.add_argument(
        "--enable-finding",
        action="store_true",
        help="enable the maintainer-only Dogfood Finding Phase A prompt/capture path",
    )
    p.add_argument("--exit-after-idle", dest="idle", type=int, default=None)
    p.add_argument("--no-push", dest="no_push", action="store_true")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="strict dispatch.env path (default: AWF_DISPATCH_ENV or ~/.config/awf/dispatch.env)",
    )
    p.add_argument(
        "--authority-manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "authority-manifest.example.json",
    )
    a = p.parse_args(argv)
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", a.role):
        die("role must be a lowercase safe identifier")
    if a.node_launch_id and not re.fullmatch(r"[0-9a-f]{32}", a.node_launch_id):
        die("node launch identity is invalid")
    if a.node_launch_id and a.state_root is None:
        die("node-managed listener requires an explicit --state-root")
    listener_root = (a.state_root or default_state_root()).expanduser().resolve()
    inherited_root = os.environ.get("AWF_STATE_ROOT")
    if inherited_root and Path(inherited_root).expanduser().resolve() != listener_root:
        die("state-root mismatch between listener argv and inherited environment")
    listener_binding = state_root_binding(listener_root)
    inherited_binding = os.environ.get("AWF_STATE_ROOT_SHA256", "")
    if inherited_binding and inherited_binding != listener_binding:
        die("state-root binding mismatch between listener argv and inherited environment")
    os.environ["AWF_STATE_ROOT"] = str(listener_root)
    os.environ["AWF_STATE_ROOT_SHA256"] = listener_binding

    try:
        config_path = a.config or default_config_path()
    except RuntimeError:
        config_path = None
    if config_path is not None and config_path.exists():
        try:
            load_into_environment(config_path)
        except ConfigError as exc:
            die(f"invalid operations configuration: {exc}")
    elif a.config is not None:
        die("configured operations file is unavailable")

    script_dir = Path(__file__).resolve().parent
    role_script = str(script_dir / "awf_role.py")
    preflight_script = str(script_dir / "awf_preflight.py")
    plan_script = str(script_dir / "awf_plan.py")
    if a.role not in DEFAULT_ON_TYPE and not a.on_type:
        die(f"role '{a.role}' has no default --on-type; pass --on-type")
    on_type = a.on_type or DEFAULT_ON_TYPE[a.role]
    if on_type.endswith("-v3") and (not a.upstream_repo or not a.head_repo):
        die("v3 listeners require --upstream-repo and --head-repo trusted local configuration")

    repo = check_workspace_readiness(Path(a.repo), a.role)

    url = os.environ.get("AGENT_BUS_URL")
    if not url:
        die("set AGENT_BUS_URL or create the strict operations configuration")
    token_var = "AWF_ARCH_TOKEN" if a.role == "architect" else f"AWF_{a.role.upper()}_TOKEN"
    token = os.environ.get(token_var)
    if not token:
        die(f"set {token_var} or create the strict operations configuration")
    configured_bus = os.environ.get("AWF_BUS_BIN", "agent-bus")
    bus = native_executable(configured_bus)
    try:
        authority = load_authority_manifest(a.authority_manifest)
        authorize_operation(authority, "listener_restart")
    except ControlPlaneDenied as exc:
        die(f"authority manifest denied listener operation: {exc}")

    # Force UTF-8 for the whole process tree (the agent-bus listener and every handler
    # it spawns inherit this). No-op on macOS/Linux; on Windows it stops child Python
    # from defaulting to the gbk locale codec and crashing on non-ASCII output.
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    configure_network_bypass(os.environ, url)

    # Config the handler needs is passed via the ENVIRONMENT (inherited by the
    # agent-bus listener and thus by each handler process it spawns).
    os.environ["AWF_SCRIPT_DIR"] = str(script_dir)
    os.environ["AWF_REPO_DIR"] = str(repo)
    os.environ["AWF_PROFILE_PATH"] = a.profile_path
    os.environ["AWF_PROFILE_SHA256"] = a.profile_sha256
    os.environ["AWF_TOOL"] = a.tool
    if a.tool_executable:
        tool_key = {
            "codex": "AWF_CODEX_BIN",
            "opencode": "AWF_OPENCODE_BIN",
            "pi": "AWF_PI_BIN",
        }.get(a.tool)
        if tool_key is None:
            die("selected tool has no executable binding")
        os.environ[tool_key] = a.tool_executable
        tool_parent = str(Path(a.tool_executable).expanduser().absolute().parent)
        os.environ["PATH"] = os.pathsep.join(
            item for item in (tool_parent, os.environ.get("PATH", "")) if item
        )
    os.environ["AWF_MODEL"] = a.model
    os.environ["AWF_BASE"] = a.base
    os.environ["AWF_UPSTREAM_REPO"] = a.upstream_repo
    os.environ["AWF_UPSTREAM_REMOTE"] = a.upstream_remote
    os.environ["AWF_HEAD_REPO"] = a.head_repo
    os.environ["AWF_HEAD_REMOTE"] = a.head_remote
    os.environ["AWF_BASE_REF"] = a.base_ref
    os.environ["AWF_GH_BIN"] = a.gh_bin
    os.environ["AWF_NO_PUSH"] = "1" if a.no_push else "0"
    os.environ["AWF_CONTROL_PLANE"] = "1"
    os.environ["AWF_FINDING_ENABLED"] = "1" if a.enable_finding else "0"
    os.environ["AWF_AUTHORITY_MANIFEST"] = str(a.authority_manifest.resolve())
    if a.enable_preflight and config_path is not None:
        os.environ["AWF_DISPATCH_ENV"] = str(config_path.resolve())
    role_types = [on_type]
    if a.role == "coder" and on_type == DEFAULT_ON_TYPE["coder"]:
        role_types.append("task:awf-rework-v3")
    elif a.role == "architect" and on_type == DEFAULT_ON_TYPE["architect"]:
        role_types.append("decision:awf-blocked-v3")
    os.environ["AWF_ACTIVE_ROUTE_TYPES"] = ",".join(role_types)
    os.environ["AGENT_BUS_TOKEN"] = token
    os.environ["AGENT_BUS_AGENT"] = a.role

    print(f"[listen] role={a.role} repo={repo} tool={a.tool} model={a.model or '<default>'}")
    print(f"[listen] on '{on_type}' -> {role_script}")
    print(
        f"[listen] stop locally with Ctrl-C; remote stop: "
        f"agent-bus send --to {a.role} --type control:shutdown"
    )

    listen_argv = [
        bus,
        "listen",
        "--agent",
        a.role,
        "--workdir",
        str(repo),
        "--handler-timeout",
        "3600",
    ]
    if a.idle is not None:
        listen_argv += ["--exit-after-idle", str(a.idle)]
    handler_argv = build_handler_argv(
        sys.executable,
        role_script,
        a.role,
        on_type=on_type,
        upstream_remote=a.upstream_remote,
        head_remote=a.head_remote,
        state_root=listener_root,
    )
    listen_argv += ["--on-argv", on_type, handler_argv_json(handler_argv)]
    for secondary_type in role_types[1:]:
        secondary_handler_argv = build_handler_argv(
            sys.executable,
            role_script,
            a.role,
            on_type=secondary_type,
            upstream_remote=a.upstream_remote,
            head_remote=a.head_remote,
            state_root=listener_root,
        )
        listen_argv += ["--on-argv", secondary_type, handler_argv_json(secondary_handler_argv)]
    if a.enable_preflight and config_path is not None:
        preflight_root = listener_root
        listen_argv += [
            "--on-argv",
            PREFLIGHT_REQUEST_TYPE,
            handler_argv_json(
                build_preflight_handler_argv(
                    sys.executable,
                    preflight_script,
                    "handle-request",
                    config_path=config_path.resolve(),
                    state_root=preflight_root,
                )
            ),
            "--on-argv",
            PREFLIGHT_RESULT_TYPE,
            handler_argv_json(
                build_preflight_handler_argv(
                    sys.executable,
                    preflight_script,
                    "handle-result",
                    config_path=config_path.resolve(),
                    state_root=preflight_root,
                )
            ),
        ]
        if a.role == "architect" and on_type == DEFAULT_ON_TYPE["architect"]:
            if not a.profile_path or not a.profile_sha256:
                die("Plan start registration requires an exact profile binding")
            listen_argv += [
                "--on-argv",
                PLAN_START_TYPE,
                handler_argv_json(
                    build_plan_start_handler_argv(
                        sys.executable,
                        plan_script,
                        repo=repo,
                        profile_path=a.profile_path,
                        profile_sha256=a.profile_sha256,
                        tool=a.tool,
                        model=a.model,
                        config_path=config_path.resolve(),
                        authority_manifest=a.authority_manifest.resolve(),
                        state_root=listener_root,
                        upstream_remote=a.upstream_remote,
                        head_remote=a.head_remote,
                        head_repo=a.head_repo,
                        gh_bin=a.gh_bin,
                    )
                ),
            ]

    try:
        lease_path = acquire_listener_lease(
            listener_root,
            a.role,
            repo,
            launch_id=a.node_launch_id,
        )
    except (ControlPlaneDenied, OSError) as exc:
        die(f"listener ownership gate failed: {exc}")
    try:
        try:
            return run_command(
                listen_argv,
                allow_shell_wrapper=True,
                secrets=(token,),
            ).returncode
        except KeyboardInterrupt:
            print(f"awf_listen: role={a.role} stopped locally", file=sys.stderr)
            return 130
        except ExecutionFailure as exc:
            die(str(exc))
    finally:
        release_listener_lease(
            lease_path,
            a.role,
            repo,
            launch_id=a.node_launch_id,
        )


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("awf_listen: stopped locally", file=sys.stderr)
        exit_code = 130
    raise SystemExit(exit_code)
