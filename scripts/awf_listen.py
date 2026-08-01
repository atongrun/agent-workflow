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
    AWF_OPENCODE_BIN / AWF_CODEX_BIN           (tool binaries; optional)

control:shutdown is built into `agent-bus listen`; the VPS can stop this listener
with `agent-bus send --to <role> --type control:shutdown`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from awf_config import ConfigError, default_config_path, load_into_environment, native_executable
from awf_control_plane import (
    ControlPlaneDenied,
    authorize_operation,
    default_state_root,
    load_authority_manifest,
)

try:
    from awf_executor import ExecutionFailure
    from awf_executor import run as run_command
except ModuleNotFoundError:  # package import in tests
    from .awf_executor import ExecutionFailure
    from .awf_executor import run as run_command
from awf_network import add_url_host_to_no_proxy

PREFLIGHT_REQUEST_TYPE = "control:awf-preflight-v1"
PREFLIGHT_RESULT_TYPE = "control:awf-preflight-result-v1"

DEFAULT_ON_TYPE = {
    "architect": "decision:awf-ready-v3",
    "coder": "task:awf-impl-v3",
    "reviewer": "task:awf-review-v3",
}


def die(msg: str):
    print(f"awf_listen: {msg}", file=sys.stderr)
    raise SystemExit(2)


def build_handler(
    python_exe: str,
    role_script: str,
    role: str,
    *,
    on_type: str = "",
) -> str:
    """Build the agent-bus --on handler command.

    This string exists only because Agent Bus currently accepts a handler
    template rather than structured handler argv. Path parts use the common
    double-quote subset; payload placeholders are substituted and shell-quoted
    by Agent Bus. Agent Workflow launches Agent Bus itself through awf_executor.
    """
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
            "--base-ref",
            "{payload.base_ref}",
            "--base-sha",
            "{payload.base_sha}",
            "--head-repo",
            "{payload.head_repo}",
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
    return f'"{python_exe}" "{role_script}" {role} ' + " ".join(fields)


def build_preflight_handler(
    python_exe: str,
    preflight_script: str,
    command: str,
    *,
    config_path: Path,
    state_root: Path,
) -> str:
    """Build the narrow no-model control handler accepted by Agent Bus v1."""
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
        f'"{state_root}"',
    ]
    if command == "handle-request":
        fields += ["--config", f'"{config_path}"']
    else:
        fields += [
            "--request-event-id",
            "{payload.request_event_id}",
            "--request-child-rc",
            "{payload.request_child_rc}",
        ]
    return f'"{python_exe}" "{preflight_script}" {command} ' + " ".join(fields)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="awf_listen")
    p.add_argument("--role", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--tool", default="opencode")
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
    p.add_argument(
        "--enable-preflight",
        action="store_true",
        help="register the no-model disposable Preflight control handlers",
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
    if a.role not in DEFAULT_ON_TYPE and not a.on_type:
        die(f"role '{a.role}' has no default --on-type; pass --on-type")
    on_type = a.on_type or DEFAULT_ON_TYPE[a.role]
    if on_type.endswith("-v3") and (not a.upstream_repo or not a.head_repo):
        die("v3 listeners require --upstream-repo and --head-repo trusted local configuration")

    if not Path(a.repo).is_dir():
        die(f"repo not found: {a.repo}")

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
    add_url_host_to_no_proxy(os.environ, url)

    # Config the handler needs is passed via the ENVIRONMENT (inherited by the
    # agent-bus listener and thus by each handler process it spawns).
    os.environ["AWF_SCRIPT_DIR"] = str(script_dir)
    os.environ["AWF_REPO_DIR"] = a.repo
    os.environ["AWF_TOOL"] = a.tool
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
    os.environ["AWF_AUTHORITY_MANIFEST"] = str(a.authority_manifest.resolve())
    if a.enable_preflight and config_path is not None:
        os.environ["AWF_DISPATCH_ENV"] = str(config_path.resolve())
    active_types = [on_type]
    if a.role == "coder" and on_type == DEFAULT_ON_TYPE["coder"]:
        active_types.append("task:awf-rework-v3")
    elif a.role == "architect" and on_type == DEFAULT_ON_TYPE["architect"]:
        active_types.append("decision:awf-blocked-v3")
    os.environ["AWF_ACTIVE_ROUTE_TYPES"] = ",".join(active_types)
    os.environ["AGENT_BUS_TOKEN"] = token
    os.environ["AGENT_BUS_AGENT"] = a.role

    handler = build_handler(sys.executable, role_script, a.role, on_type=on_type)

    print(f"[listen] role={a.role} repo={a.repo} tool={a.tool} model={a.model or '<default>'}")
    print(f"[listen] on '{on_type}' -> {role_script}")
    print(f"[listen] stop via: agent-bus send --to {a.role} --type control:shutdown")

    listen_argv = [
        bus,
        "listen",
        "--agent",
        a.role,
        "--workdir",
        a.repo,
        "--handler-timeout",
        "3600",
    ]
    if a.idle is not None:
        listen_argv += ["--exit-after-idle", str(a.idle)]
    listen_argv += ["--on", on_type, handler]
    if len(active_types) > 1:
        rework_handler = build_handler(
            sys.executable,
            role_script,
            a.role,
            on_type=active_types[1],
        )
        listen_argv += ["--on", active_types[1], rework_handler]
    if a.enable_preflight and config_path is not None:
        preflight_root = (a.state_root or default_state_root()).resolve()
        listen_argv += [
            "--on",
            PREFLIGHT_REQUEST_TYPE,
            build_preflight_handler(
                sys.executable,
                preflight_script,
                "handle-request",
                config_path=config_path.resolve(),
                state_root=preflight_root,
            ),
            "--on",
            PREFLIGHT_RESULT_TYPE,
            build_preflight_handler(
                sys.executable,
                preflight_script,
                "handle-result",
                config_path=config_path.resolve(),
                state_root=preflight_root,
            ),
        ]

    try:
        return run_command(
            listen_argv,
            allow_shell_wrapper=True,
            secrets=(token,),
        ).returncode
    except ExecutionFailure as exc:
        die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
