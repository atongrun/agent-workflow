#!/usr/bin/env python3
"""Fail-closed loop-start readiness checks for Agent Workflow.

Fast mode is strictly read-only. Deep mode is explicit and uses disposable
control events handled by the existing role listeners; it never enters a
model-backed role path or uses manual event lifecycle commands.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from awf_config import ConfigError, default_config_path, load_config, native_executable
from awf_control_plane import (
    ControlPlaneDenied,
    RunLedger,
    authorize_operation,
    default_state_root,
    load_authority_manifest,
)
from awf_executor import ExecutionFailure, detect_runtime
from awf_executor import run as run_command
from awf_network import add_url_host_to_no_proxy

REPORT_FORMAT = "awf.preflight-report.v1"
REQUEST_TYPE = "control:awf-preflight-v1"
RESULT_TYPE = "control:awf-preflight-result-v1"
ROLE_TOKEN = {
    "architect": "AWF_ARCH_TOKEN",
    "coder": "AWF_CODER_TOKEN",
    "reviewer": "AWF_REVIEWER_TOKEN",
}
AUTHORING_LAYERS = {"runtime", "configuration", "git-local", "workflow-control"}
REMOTE_LAYERS = AUTHORING_LAYERS | {
    "network",
    "agent-bus",
    "git-remote",
    "github",
    "model-tool",
}
PROBE_ID_RE = re.compile(r"^awf-preflight-[0-9a-f]{32}$")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class PreflightError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass
class Layer:
    id: str
    status: str
    code: str
    duration_ms: int
    evidence: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "error_code": self.code,
            "duration_ms": self.duration_ms,
            "evidence": self.evidence,
        }


@dataclass
class FastResult:
    report: dict[str, object]
    config: dict[str, str]
    fingerprint: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat()


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    with temp.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def probe_dir(state_root: Path, probe_id: str) -> Path:
    if not PROBE_ID_RE.fullmatch(probe_id):
        raise PreflightError("DEEP_IDENTITY_INVALID", "probe identity is invalid")
    return state_root.resolve() / "preflight" / "probes" / probe_id


def cache_path(state_root: Path) -> Path:
    return state_root.resolve() / "preflight" / "latest-deep.json"


def checked(
    layer_id: str,
    code: str,
    operation: Callable[[], dict[str, object]],
) -> Layer:
    started = time.monotonic()
    try:
        evidence = operation()
        status = "PASS"
        error_code = ""
    except PreflightError as exc:
        evidence = {"message": str(exc)}
        status = "FAIL"
        error_code = exc.code
    except (ControlPlaneDenied, ConfigError) as exc:
        evidence = {"message": str(exc)}
        status = "FAIL"
        error_code = code
    except (OSError, ValueError, json.JSONDecodeError):
        evidence = {"message": "readiness evidence is unavailable or invalid"}
        status = "FAIL"
        error_code = code
    return Layer(
        layer_id,
        status,
        error_code,
        max(0, round((time.monotonic() - started) * 1000)),
        evidence,
    )


def execute(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float = 20,
    secrets: tuple[str, ...] = (),
    allow_shell_wrapper: bool = False,
):
    try:
        return run_command(
            argv,
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            secrets=secrets,
            allow_shell_wrapper=allow_shell_wrapper,
        )
    except ExecutionFailure as exc:
        raise PreflightError("COMMAND_FAILED", exc.diagnostic.kind) from None


def require_success(completed, code: str) -> None:
    if completed.returncode != 0:
        raise PreflightError(code, "read-only command failed")


def executable(value: str) -> str:
    candidate = native_executable(value)
    resolved = shutil.which(candidate) or (candidate if Path(candidate).is_file() else "")
    if not resolved:
        raise PreflightError("EXECUTABLE_MISSING", "configured executable was not found")
    return resolved


def role_environment(config: dict[str, str], role: str) -> tuple[dict[str, str], str]:
    token = config.get(ROLE_TOKEN[role], "")
    url = config.get("AGENT_BUS_URL", "")
    if not token or not url:
        raise PreflightError("CONFIG_REQUIRED_KEY_MISSING", "role Bus configuration is incomplete")
    environment = dict(os.environ)
    environment.update({"AGENT_BUS_URL": url, "AGENT_BUS_TOKEN": token, "AGENT_BUS_AGENT": role})
    add_url_host_to_no_proxy(environment, url)
    return environment, token


def pending_count(config: dict[str, str], role: str) -> int:
    environment, token = role_environment(config, role)
    bus = executable(config.get("AWF_BUS_BIN", "agent-bus"))
    completed = execute(
        [bus, "pending", "--agent", role, "--count"],
        env=environment,
        secrets=(token,),
        allow_shell_wrapper=True,
    )
    require_success(completed, "BUS_PENDING_FAILED")
    value = completed.stdout.strip()
    if not value.isdigit():
        raise PreflightError("BUS_PENDING_INVALID", "pending count was not an integer")
    return int(value)


def parse_repo_slug(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PreflightError("GIT_REMOTE_UNTRUSTED", "remote URL is not canonical GitHub HTTPS")
    slug = parsed.path.strip("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug):
        raise PreflightError("GIT_REMOTE_UNTRUSTED", "remote repository identity is invalid")
    return slug


def proxy_check(value: str) -> None:
    if not value:
        return
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise PreflightError("PROXY_CREDENTIALS_PRESENT", "proxy contains embedded credentials")


def is_tailnet_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return host.casefold().endswith(".ts.net")


def fingerprint_for(
    config: dict[str, str],
    *,
    runtime: str,
    repo: Path,
    source_role: str,
    target_role: str,
    upstream_remote: str,
    head_remote: str,
) -> str:
    selected = {
        "runtime": runtime,
        "repo": str(repo.resolve()),
        "source_role": source_role,
        "target_role": target_role,
        "upstream_remote": upstream_remote,
        "head_remote": head_remote,
        "config": {key: config.get(key, "") for key in sorted(config)},
        "proxy": {
            key: os.environ.get(key, "")
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy")
        },
    }
    return hashlib.sha256(("awf-preflight-v1\0" + canonical(selected)).encode()).hexdigest()


def proof_mac(
    value: dict[str, object],
    config: dict[str, str],
    source_role: str,
    target_role: str,
) -> str:
    source = config.get(ROLE_TOKEN[source_role], "")
    target = config.get(ROLE_TOKEN[target_role], "")
    if not source or not target:
        return ""
    key = hashlib.sha256(
        ("awf-preflight-cache-v1\0" + source + "\0" + target).encode("utf-8")
    ).digest()
    body = {name: item for name, item in value.items() if name != "proof_mac"}
    return hmac.new(key, canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()


def sign_deep_report(
    value: dict[str, object],
    config: dict[str, str],
    source_role: str,
    target_role: str,
) -> dict[str, object]:
    signed = dict(value)
    signed["proof_mac"] = proof_mac(signed, config, source_role, target_role)
    return signed


def load_current_cache(
    path: Path,
    fingerprint: str,
    now: datetime,
    *,
    config: dict[str, str],
    source_role: str,
    target_role: str,
) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(str(value["expires_at"]))
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None
    deep = value.get("deep")
    layers = value.get("layers")
    expected_pending = {source_role: 0, target_role: 0}
    if (
        value.get("format") != REPORT_FORMAT
        or value.get("mode") != "deep"
        or value.get("status") != "PASS"
        or value.get("allow_remote_dispatch") is not True
        or value.get("required_next_action") != "remote_dispatch_allowed"
        or value.get("fingerprint") != fingerprint
        or expires <= now
        or not isinstance(deep, dict)
        or deep.get("current") is not True
        or not PROBE_ID_RE.fullmatch(str(deep.get("probe_id", "")))
        or type(deep.get("request_event_id")) is not int
        or int(deep["request_event_id"]) < 1
        or type(deep.get("reply_event_id")) is not int
        or int(deep["reply_event_id"]) < 1
        or deep.get("source_role") != source_role
        or deep.get("target_role") != target_role
        or deep.get("pending_before") != expected_pending
        or deep.get("pending_after") != expected_pending
        or any(
            deep.get(field) != "pass"
            for field in (
                "request_handler",
                "request_child",
                "result_handler",
                "result_child",
            )
        )
        or deep.get("request_ack_evidence") != "inferred-handler-success-and-zero-pending"
        or deep.get("reply_ack_evidence") != "inferred-handler-success-and-zero-pending"
        or not isinstance(layers, list)
        or any(
            not any(
                isinstance(layer, dict)
                and layer.get("id") == required
                and layer.get("status") == "PASS"
                for layer in layers
            )
            for required in REMOTE_LAYERS
        )
        or not FINGERPRINT_RE.fullmatch(str(value.get("proof_mac", "")))
        or not hmac.compare_digest(
            str(value.get("proof_mac", "")),
            proof_mac(value, config, source_role, target_role),
        )
    ):
        return None
    return value


def run_fast(args: argparse.Namespace) -> FastResult:
    now = utc_now()
    profile = getattr(args, "profile", "loop")
    config: dict[str, str] = {}
    runtime_info = detect_runtime()
    repo = args.repo.resolve()

    runtime_layer = checked(
        "runtime",
        "RUNTIME_UNAVAILABLE",
        lambda: {
            "runtime": runtime_info.kind.value,
            "executor_boundary": "awf_executor",
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
    )

    def configuration() -> dict[str, object]:
        nonlocal config
        if not args.config.is_file():
            raise PreflightError("CONFIG_MISSING", "strict operations configuration is missing")
        config = load_config(args.config)
        required = {"AGENT_BUS_URL", ROLE_TOKEN[args.source_role]}
        if profile == "loop":
            required.add(ROLE_TOKEN[args.target_role])
        missing = sorted(key for key in required if not config.get(key))
        if missing:
            raise PreflightError(
                "CONFIG_REQUIRED_KEY_MISSING", "required role configuration is incomplete"
            )
        executable(config.get("AWF_BUS_BIN", "agent-bus"))
        return {"strict_loader": True, "owner_only": True, "required_keys": "present"}

    config_layer = checked("configuration", "CONFIG_INVALID", configuration)

    def network() -> dict[str, object]:
        if not config:
            raise PreflightError("CONFIG_INVALID", "network configuration is unavailable")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            proxy_check(os.environ.get(key, ""))
        url = config["AGENT_BUS_URL"]
        host = urlsplit(url).hostname
        if not host:
            raise PreflightError("BUS_URL_INVALID", "Bus URL has no host")
        child = dict(os.environ)
        add_url_host_to_no_proxy(child, url)
        entries = {entry.casefold() for entry in child["NO_PROXY"].split(",") if entry}
        if host.casefold() not in entries or child["NO_PROXY"] != child["no_proxy"]:
            raise PreflightError(
                "NO_PROXY_INVALID", "Bus host proxy bypass could not be normalized"
            )
        evidence: dict[str, object] = {"proxy_credentials": False, "bus_bypass": True}
        if is_tailnet_host(host):
            tailscale = executable("tailscale")
            status = execute([tailscale, "status", "--json"], timeout=10)
            require_success(status, "TAILSCALE_UNAVAILABLE")
            ping = execute([tailscale, "ping", "--until-direct=false", "--c=1", host], timeout=15)
            require_success(ping, "TAILSCALE_ROUTE_MISSING")
            evidence["tailscale"] = "reachable"
        else:
            evidence["tailscale"] = "not-required"
        return evidence

    network_layer = checked("network", "NETWORK_INVALID", network)

    def bus() -> dict[str, object]:
        if not config:
            raise PreflightError("CONFIG_INVALID", "Bus configuration is unavailable")
        environment, token = role_environment(config, args.source_role)
        bus_bin = executable(config.get("AWF_BUS_BIN", "agent-bus"))
        doctor = execute(
            [bus_bin, "doctor"],
            env=environment,
            timeout=20,
            secrets=(token,),
            allow_shell_wrapper=True,
        )
        require_success(doctor, "BUS_HEALTH_FAILED")
        roles = (
            (args.source_role,)
            if profile == "handoff"
            else (
                args.source_role,
                args.target_role,
            )
        )
        return {
            "health": "pass",
            "pending": {role: pending_count(config, role) for role in roles},
        }

    bus_layer = checked("agent-bus", "BUS_HEALTH_FAILED", bus)

    def git_local() -> dict[str, object]:
        if profile == "handoff" and not getattr(args, "repo_required", True):
            return {"worktree": "not-requested", "branch": "not-requested"}
        inside = execute(["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"])
        require_success(inside, "GIT_NOT_WORKTREE")
        branch = execute(["git", "-C", str(repo), "branch", "--show-current"])
        require_success(branch, "GIT_BRANCH_UNREADABLE")
        if not branch.stdout.strip():
            raise PreflightError("GIT_DETACHED", "repository is detached")
        return {"worktree": True, "branch": branch.stdout.strip()}

    git_local_layer = checked("git-local", "GIT_NOT_WORKTREE", git_local)

    remote_facts: dict[str, str] = {}

    def git_remote() -> dict[str, object]:
        if profile == "handoff":
            if not getattr(args, "repo_required", True):
                return {"push_dry_run": "not-requested"}
            dry = execute(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(repo),
                    "push",
                    "--dry-run",
                ],
                timeout=45,
            )
            require_success(dry, "GIT_PUSH_DRYRUN_FAILED")
            return {"push_dry_run": True, "compatibility": "legacy-default-remote"}
        for label, remote in (("upstream", args.upstream_remote), ("head", args.head_remote)):
            result = execute(["git", "-C", str(repo), "remote", "get-url", remote])
            require_success(result, "GIT_REMOTE_MISSING")
            fetch_url = result.stdout.strip()
            remote_facts[label] = parse_repo_slug(fetch_url)
            push = execute(["git", "-C", str(repo), "remote", "get-url", "--push", "--all", remote])
            require_success(push, "GIT_REMOTE_MISSING")
            push_urls = push.stdout.strip().splitlines()
            if push_urls != [fetch_url]:
                raise PreflightError(
                    "GIT_REMOTE_UNTRUSTED", "remote push URL differs from its fetch URL"
                )
            parse_repo_slug(push_urls[0])
        if remote_facts["upstream"].casefold() == remote_facts["head"].casefold():
            raise PreflightError("GIT_FORK_NOT_DISTINCT", "head remote is not a contribution fork")
        branch = execute(["git", "-C", str(repo), "branch", "--show-current"]).stdout.strip()
        dry = execute(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(repo),
                "push",
                "--dry-run",
                args.head_remote,
                f"HEAD:refs/heads/{branch}",
            ],
            timeout=45,
        )
        require_success(dry, "GIT_FORK_DRYRUN_FAILED")
        return {"upstream": "read-only", "head": "fork", "push_dry_run": True}

    git_remote_layer = checked("git-remote", "GIT_REMOTE_INVALID", git_remote)

    def github() -> dict[str, object]:
        if profile == "handoff":
            return {"readiness": "not-part-of-legacy-contract"}
        gh = executable(args.gh_bin)
        auth = execute([gh, "auth", "status", "--active", "--hostname", "github.com"], timeout=20)
        require_success(auth, "GH_AUTH_FAILED")
        if not remote_facts.get("upstream"):
            raise PreflightError("GH_REPO_UNKNOWN", "upstream repository identity is unavailable")
        view = execute(
            [gh, "repo", "view", remote_facts["upstream"], "--json", "nameWithOwner"],
            timeout=20,
        )
        require_success(view, "GH_REPO_READ_FAILED")
        return {"authenticated": True, "upstream_readable": True, "operations": "read-only"}

    github_layer = checked("github", "GH_READINESS_FAILED", github)

    def model_tool() -> dict[str, object]:
        if not config:
            raise PreflightError("CONFIG_INVALID", "tool configuration is unavailable")
        configured = getattr(args, "model_tool", "")
        if not configured and profile == "handoff":
            return {"executable": "not-requested", "model_invoked": False}
        if not configured:
            raise PreflightError(
                "MODEL_TOOL_NOT_CONFIGURED",
                "pass the model-tool executable selected for this runtime",
            )
        tool = executable(configured)
        version = execute([tool, "--version"], timeout=15, allow_shell_wrapper=True)
        require_success(version, "MODEL_TOOL_UNEXECUTABLE")
        return {
            "executable": True,
            "selection": "explicit",
            "probe": "version-only",
            "model_invoked": False,
        }

    model_layer = checked("model-tool", "MODEL_TOOL_UNAVAILABLE", model_tool)

    def workflow() -> dict[str, object]:
        manifest = load_authority_manifest(args.authority_manifest)
        authorize_operation(manifest, "diagnose")
        evidence: dict[str, object] = {"authority": "readable", "diagnose": "authorized"}
        if args.run_id:
            RunLedger(args.state_root, args.run_id).recover()
            evidence["ledger"] = "recovered"
        else:
            root = args.state_root.resolve() / "control-plane" / "runs"
            if root.exists() and not root.is_dir():
                raise PreflightError("LEDGER_UNREADABLE", "run ledger root is not a directory")
            if root.exists() and not os.access(root, os.R_OK | os.X_OK):
                raise PreflightError("LEDGER_UNREADABLE", "run ledger root is not readable")
            evidence["ledger"] = "root-readable" if root.exists() else "not-yet-created"
        return evidence

    workflow_layer = checked("workflow-control", "AUTHORITY_OR_LEDGER_INVALID", workflow)
    layers = [
        runtime_layer,
        config_layer,
        network_layer,
        bus_layer,
        git_local_layer,
        git_remote_layer,
        github_layer,
        model_layer,
        workflow_layer,
    ]
    fingerprint = fingerprint_for(
        config,
        runtime=runtime_info.kind.value,
        repo=repo,
        source_role=args.source_role,
        target_role=args.target_role,
        upstream_remote=args.upstream_remote,
        head_remote=args.head_remote,
    )
    current_cache = load_current_cache(
        cache_path(args.state_root),
        fingerprint,
        now,
        config=config,
        source_role=args.source_role,
        target_role=args.target_role,
    )
    failed = {layer.id for layer in layers if layer.status != "PASS"}
    allow_taskcard = not bool(failed & AUTHORING_LAYERS)
    remote_fast = not bool(failed & REMOTE_LAYERS)
    if not allow_taskcard:
        action = "fix_fast_preflight"
    elif args.intent == "taskcard":
        action = "author_taskcard"
    elif not remote_fast:
        action = "fix_fast_preflight"
    elif current_cache is None:
        action = "run_deep_preflight"
    else:
        action = "remote_dispatch_allowed"
    allow_remote = action == "remote_dispatch_allowed"
    report = {
        "format": REPORT_FORMAT,
        "mode": "fast",
        "generated_at": iso(now),
        "status": "PASS"
        if (allow_taskcard if args.intent == "taskcard" else allow_remote)
        else "FAIL",
        "allow_taskcard_authoring": allow_taskcard,
        "allow_remote_dispatch": allow_remote,
        "required_next_action": action,
        "layers": [layer.as_dict() for layer in layers],
        "fingerprint": fingerprint,
        "deep": {
            "required": args.intent == "remote-dispatch" and current_cache is None,
            "current": current_cache is not None,
            "expires_at": current_cache.get("expires_at") if current_cache else None,
        },
    }
    return FastResult(report, config, fingerprint)


def wait_for_result(path: Path, timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
            if isinstance(value, dict):
                return value
        time.sleep(0.1)
    raise PreflightError("DEEP_REPLY_TIMEOUT", "disposable result was not acknowledged in time")


def wait_for_zero(config: dict[str, str], roles: tuple[str, str], timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    latest: dict[str, int] = {}
    while time.monotonic() < deadline:
        latest = {role: pending_count(config, role) for role in roles}
        if all(value == 0 for value in latest.values()):
            return latest
        time.sleep(0.2)
    raise PreflightError("DEEP_PENDING_DRIFT", "disposable queues did not return to baseline")


def _run_deep(args: argparse.Namespace) -> dict[str, object]:
    args.intent = "remote-dispatch"
    fast = run_fast(args)
    cache = load_current_cache(
        cache_path(args.state_root),
        fast.fingerprint,
        utc_now(),
        config=fast.config,
        source_role=args.source_role,
        target_role=args.target_role,
    )
    if cache is not None and not args.force:
        return cache
    fast_failures = [
        layer
        for layer in fast.report["layers"]
        if layer["id"] in REMOTE_LAYERS and layer["status"] != "PASS"
    ]
    if fast_failures:
        report = dict(fast.report)
        report.update({"mode": "deep", "status": "FAIL", "allow_remote_dispatch": False})
        report["required_next_action"] = "fix_fast_preflight"
        return report
    roles = (args.source_role, args.target_role)
    before = {role: pending_count(fast.config, role) for role in roles}
    if any(before.values()):
        report = dict(fast.report)
        report.update({"mode": "deep", "status": "FAIL", "allow_remote_dispatch": False})
        report["required_next_action"] = "fix_fast_preflight"
        report["deep"] = {
            "required": True,
            "error_code": "DEEP_NONZERO_BASELINE",
            "pending_before": before,
        }
        return report
    probe_id = "awf-preflight-" + uuid.uuid4().hex
    result_file = probe_dir(args.state_root, probe_id) / "source-result.json"
    environment, token = role_environment(fast.config, args.source_role)
    bus = executable(fast.config.get("AWF_BUS_BIN", "agent-bus"))
    payload = canonical(
        {
            "format": "awf.preflight-control.v1",
            "probe_id": probe_id,
            "source_role": args.source_role,
            "target_role": args.target_role,
            "fingerprint": fast.fingerprint,
        }
    )
    sent = execute(
        [
            bus,
            "send",
            "--from",
            args.source_role,
            "--to",
            args.target_role,
            "--type",
            REQUEST_TYPE,
            "--payload",
            payload,
        ],
        env=environment,
        timeout=20,
        secrets=(token,),
        allow_shell_wrapper=True,
    )
    if sent.returncode != 0:
        raise PreflightError("DEEP_SEND_FAILED", "disposable request could not be sent")
    result = wait_for_result(result_file, args.timeout)
    after = wait_for_zero(fast.config, roles, min(args.timeout, 20))
    expected = {
        "format": "awf.preflight-control-result.v1",
        "probe_id": probe_id,
        "fingerprint": fast.fingerprint,
        "request_type": REQUEST_TYPE,
        "result_type": RESULT_TYPE,
        "source_role": args.source_role,
        "target_role": args.target_role,
        "request_child_rc": 0,
        "result_child_rc": 0,
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise PreflightError("DEEP_IDENTITY_MISMATCH", "disposable result identity is invalid")
    request_event = result.get("request_event_id")
    reply_event = result.get("reply_event_id")
    if not isinstance(request_event, int) or request_event < 1:
        raise PreflightError("DEEP_ACK_NOT_PROVEN", "request event identity is missing")
    if not isinstance(reply_event, int) or reply_event < 1:
        raise PreflightError("DEEP_ACK_NOT_PROVEN", "result event identity is missing")
    completed = utc_now()
    report = {
        **fast.report,
        "mode": "deep",
        "generated_at": iso(completed),
        "expires_at": iso(completed + timedelta(seconds=args.ttl_seconds)),
        "status": "PASS",
        "allow_taskcard_authoring": True,
        "allow_remote_dispatch": True,
        "required_next_action": "remote_dispatch_allowed",
        "deep": {
            "required": True,
            "current": True,
            "probe_id": probe_id,
            "source_role": args.source_role,
            "target_role": args.target_role,
            "request_event_id": request_event,
            "reply_event_id": reply_event,
            "pending_before": before,
            "pending_after": after,
            "request_handler": "pass",
            "request_child": "pass",
            "result_handler": "pass",
            "result_child": "pass",
            "request_ack_evidence": "inferred-handler-success-and-zero-pending",
            "reply_ack_evidence": "inferred-handler-success-and-zero-pending",
        },
    }
    report = sign_deep_report(report, fast.config, args.source_role, args.target_role)
    atomic_write(cache_path(args.state_root), report)
    return report


def run_deep(args: argparse.Namespace) -> dict[str, object]:
    """Return a versioned denial report for every recoverable Deep failure."""
    try:
        return _run_deep(args)
    except PreflightError as exc:
        try:
            base = run_fast(args).report
        except Exception:  # the report below stays credential-free and fail-closed
            base = {
                "format": REPORT_FORMAT,
                "generated_at": iso(utc_now()),
                "layers": [],
                "fingerprint": "",
            }
        layers = base.get("layers", [])
        fast_failed = any(
            isinstance(layer, dict)
            and layer.get("id") in REMOTE_LAYERS
            and layer.get("status") != "PASS"
            for layer in layers
        )
        return {
            **base,
            "mode": "deep",
            "status": "FAIL",
            "allow_taskcard_authoring": bool(base.get("allow_taskcard_authoring", False)),
            "allow_remote_dispatch": False,
            "required_next_action": "fix_fast_preflight" if fast_failed else "run_deep_preflight",
            "deep": {"required": True, "current": False, "error_code": exc.code},
        }


def validate_handler_identity(
    *, event_type: str, expected_type: str, probe_id: str, fingerprint: str
) -> None:
    if event_type != expected_type:
        raise PreflightError("DEEP_TYPE_MISMATCH", "control event type is invalid")
    if not PROBE_ID_RE.fullmatch(probe_id) or not FINGERPRINT_RE.fullmatch(fingerprint):
        raise PreflightError("DEEP_IDENTITY_INVALID", "control event identity is invalid")


def positive_int(value: object, label: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        raise PreflightError("DEEP_IDENTITY_INVALID", f"{label} is invalid") from None
    if parsed < 1:
        raise PreflightError("DEEP_IDENTITY_INVALID", f"{label} is invalid")
    return parsed


def child_probe() -> int:
    completed = execute(
        [sys.executable, "-c", "import os; raise SystemExit(0 if os.getpid() > 0 else 1)"],
        timeout=10,
    )
    return completed.returncode


def handle_request(args: argparse.Namespace) -> int:
    validate_handler_identity(
        event_type=args.event_type,
        expected_type=REQUEST_TYPE,
        probe_id=args.probe_id,
        fingerprint=args.fingerprint,
    )
    if args.target_role not in ROLE_TOKEN or args.source_role not in ROLE_TOKEN:
        raise PreflightError("DEEP_ROLE_INVALID", "control role is invalid")
    if os.environ.get("AGENT_BUS_AGENT") != args.target_role:
        raise PreflightError("DEEP_ROLE_MISMATCH", "request reached the wrong role listener")
    child_rc = child_probe()
    if child_rc != 0:
        raise PreflightError("DEEP_HANDLER_FAILED", "request child failed")
    config = load_config(args.config)
    environment, token = role_environment(config, args.target_role)
    bus = executable(config.get("AWF_BUS_BIN", "agent-bus"))
    payload = canonical(
        {
            "format": "awf.preflight-control-result.v1",
            "probe_id": args.probe_id,
            "fingerprint": args.fingerprint,
            "request_event_id": positive_int(args.event_id, "request event ID"),
            "request_type": REQUEST_TYPE,
            "result_type": RESULT_TYPE,
            "source_role": args.source_role,
            "target_role": args.target_role,
            "request_child_rc": child_rc,
        }
    )
    result = execute(
        [
            bus,
            "send",
            "--from",
            args.target_role,
            "--to",
            args.source_role,
            "--type",
            RESULT_TYPE,
            "--payload",
            payload,
        ],
        env=environment,
        secrets=(token,),
        allow_shell_wrapper=True,
    )
    if result.returncode != 0:
        raise PreflightError("DEEP_RESULT_SEND_FAILED", "control result could not be sent")
    atomic_write(
        probe_dir(args.state_root, args.probe_id) / "target-result.json",
        {
            "format": "awf.preflight-target-evidence.v1",
            "probe_id": args.probe_id,
            "request_event_id": positive_int(args.event_id, "request event ID"),
            "child_rc": child_rc,
            "reply_sent": True,
        },
    )
    return 0


def handle_result(args: argparse.Namespace) -> int:
    validate_handler_identity(
        event_type=args.event_type,
        expected_type=RESULT_TYPE,
        probe_id=args.probe_id,
        fingerprint=args.fingerprint,
    )
    if os.environ.get("AGENT_BUS_AGENT") != args.source_role:
        raise PreflightError("DEEP_ROLE_MISMATCH", "result reached the wrong role listener")
    try:
        request_child_rc = int(str(args.request_child_rc))
    except (TypeError, ValueError):
        raise PreflightError("DEEP_IDENTITY_INVALID", "request child result is invalid") from None
    if request_child_rc != 0:
        raise PreflightError("DEEP_HANDLER_FAILED", "request child did not succeed")
    child_rc = child_probe()
    if child_rc != 0:
        raise PreflightError("DEEP_HANDLER_FAILED", "result child failed")
    value = {
        "format": "awf.preflight-control-result.v1",
        "probe_id": args.probe_id,
        "fingerprint": args.fingerprint,
        "request_event_id": positive_int(args.request_event_id, "request event ID"),
        "reply_event_id": positive_int(args.event_id, "reply event ID"),
        "request_type": REQUEST_TYPE,
        "result_type": RESULT_TYPE,
        "source_role": args.source_role,
        "target_role": args.target_role,
        "request_child_rc": request_child_rc,
        "result_child_rc": child_rc,
    }
    atomic_write(probe_dir(args.state_root, args.probe_id) / "source-result.json", value)
    return 0


def common(parser: argparse.ArgumentParser) -> None:
    try:
        config = default_config_path()
    except RuntimeError:
        config = Path("dispatch.env").resolve()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=config)
    parser.add_argument("--state-root", type=Path, default=default_state_root())
    parser.add_argument(
        "--authority-manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "authority-manifest.example.json",
    )
    parser.add_argument("--source-role", choices=sorted(ROLE_TOKEN), default="architect")
    parser.add_argument("--target-role", choices=sorted(ROLE_TOKEN), default="coder")
    parser.add_argument("--upstream-remote", default="upstream")
    parser.add_argument("--head-remote", default="fork")
    parser.add_argument("--gh-bin", default="gh")
    parser.add_argument(
        "--model-tool",
        default="",
        help="explicit model CLI executable to probe with --version",
    )
    parser.add_argument("--run-id", default="")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="awf-preflight")
    commands = value.add_subparsers(dest="command", required=True)
    fast = commands.add_parser("fast")
    common(fast)
    fast.add_argument("--intent", choices=("taskcard", "remote-dispatch"), default="taskcard")
    deep = commands.add_parser("deep")
    common(deep)
    deep.add_argument("--ttl-seconds", type=int, default=86400)
    deep.add_argument("--timeout", type=float, default=60)
    deep.add_argument("--force", action="store_true")
    request = commands.add_parser("handle-request", help=argparse.SUPPRESS)
    result = commands.add_parser("handle-result", help=argparse.SUPPRESS)
    for handler in (request, result):
        handler.add_argument("--event-id", required=True)
        handler.add_argument("--event-type", required=True)
        handler.add_argument("--probe-id", required=True)
        handler.add_argument("--fingerprint", required=True)
        handler.add_argument("--source-role", required=True)
        handler.add_argument("--target-role", required=True)
        handler.add_argument("--state-root", type=Path, default=default_state_root())
    request.add_argument("--config", type=Path, default=default_config_path())
    result.add_argument("--request-event-id", required=True)
    result.add_argument("--request-child-rc", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "fast":
            report = run_fast(args).report
        elif args.command == "deep":
            if args.ttl_seconds < 1 or args.timeout <= 0:
                raise PreflightError("DEEP_ARGUMENT_INVALID", "TTL and timeout must be positive")
            report = run_deep(args)
        elif args.command == "handle-request":
            return handle_request(args)
        else:
            return handle_result(args)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("status") == "PASS" else 1
    except PreflightError as exc:
        print(f"awf-preflight: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, ControlPlaneDenied) as exc:
        print(f"awf-preflight: denied: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
