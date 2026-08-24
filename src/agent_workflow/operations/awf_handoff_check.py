#!/usr/bin/env python3
"""awf_handoff_check -"can I take over on this machine?" self-check.

A single command a new agent / a freshly-bootstrapped machine runs to confirm
the runtime layer is ready: dispatch.env present + locked down + complete,
Agent Bus reachable with a valid token scope, git can push, and the executor
tool is present. Emits a PASS / FAIL / WARN checklist and exits non-zero if any
required check fails.

    python awf_handoff_check.py --role coder --repo /path/to/agent-bus
    python awf_handoff_check.py --role architect          # dispatcher machine

Hard rule: token VALUES are never printed. Checks assert *presence* and
*that a scoped call succeeds*, never the secret itself.

This is the runtime-layer complement to file-based handoff (AI Memory + HANDOFF
recover context; this confirms the machine is actually wired up).
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from pathlib import Path

from agent_workflow.operations.awf_config import ConfigError, load_config, native_executable
from agent_workflow.operations.awf_control_plane import default_state_root

try:
    from agent_workflow.operations.awf_executor import ExecutionFailure
    from agent_workflow.operations.awf_executor import run as run_command
except ModuleNotFoundError:  # package import in tests
    from agent_workflow.operations.awf_executor import ExecutionFailure
    from agent_workflow.operations.awf_executor import run as run_command
from agent_workflow.operations.awf_network import add_url_host_to_no_proxy
from agent_workflow.operations.awf_preflight import run_fast

ROLE_TO_TOKEN_VAR = {
    "architect": "AWF_ARCH_TOKEN",
    "coder": "AWF_CODER_TOKEN",
    "reviewer": "AWF_REVIEWER_TOKEN",
}

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
# ASCII marks only: the Windows console default codec (gbk/cp936) cannot encode
# ✓/✗, which would crash the report with UnicodeEncodeError.
MARK = {PASS: "+", FAIL: "x", WARN: "!"}

results: list = []  # (status, label, detail)


def record(status: str, label: str, detail: str = "") -> None:
    results.append((status, label, detail))


def posix_to_native(path: str) -> str:
    """Translate legacy Git-Bash paths for native Windows probes."""
    return native_executable(path)


def is_file(path: str) -> bool:
    return Path(posix_to_native(path)).is_file()


def parse_env_file(path: Path) -> dict:
    """Compatibility wrapper around the single strict configuration loader."""
    return load_config(path)


def parse_icacls_aces(dest: Path, output: str) -> list[tuple[str, str]]:
    """Extract ACL principals without treating the echoed target path as an ACE."""
    target = str(dest)
    aces = []
    for line in output.splitlines():
        entry = line.strip()
        if entry.casefold().startswith(target.casefold()):
            entry = entry[len(target) :].strip()
        match = re.fullmatch(r"(.+?):((?:\([A-Za-z,]+\))+)", entry)
        if match:
            aces.append((match.group(1), match.group(2)))
        elif ":(" in entry:
            return []
    return aces


def check_windows_acl(dest: Path) -> None:
    """On Windows, assert that every ACE belongs to the current principal and
    that none are inherited. awf_bootstrap.py sets this with `icacls /inheritance:r`.

    icacls echoes the file PATH on the first output line, then one ACE per line
    like `  DOMAIN\\user:(F)`. We must inspect only the ACE lines — the path
    itself often contains 'Users' (C:\\Users\\...) and would false-positive a
    naive substring scan of the whole blob."""
    proc = run_command(["icacls", str(dest)], capture_output=True, text=True)
    if proc.returncode != 0:
        record(FAIL, "dispatch.env is owner-only", "icacls could not read the ACL")
        return
    aces = parse_icacls_aces(dest, proc.stdout)
    if not aces:
        record(FAIL, "dispatch.env is owner-only", "could not parse icacls ACEs")
        return

    whoami = run_command(["whoami"], capture_output=True, text=True)
    principal = whoami.stdout.strip() if whoami.returncode == 0 else ""
    if not principal:
        record(FAIL, "dispatch.env is owner-only", "could not determine the current principal")
        return

    inherited = any("(I)" in perms for _principal, perms in aces)
    unexpected = any(ace_principal.casefold() != principal.casefold() for ace_principal, _ in aces)
    if inherited or unexpected:
        record(
            FAIL,
            "dispatch.env is owner-only",
            "ACL is inherited or grants another principal - re-run awf_bootstrap.py "
            "(icacls lockdown)",
        )
    else:
        record(PASS, "dispatch.env is owner-only", "icacls: current principal only")


def check_dispatch_env(dest: Path, role: str) -> dict:
    if not dest.is_file():
        record(FAIL, "dispatch.env exists", "not found - run awf_bootstrap.py")
        return {}
    record(PASS, "dispatch.env exists", "configured path withheld")

    # permissions must be owner-only -never group/world/Administrators readable.
    if os.name != "nt":
        mode = stat.S_IMODE(dest.stat().st_mode)
        if mode & 0o077:
            record(
                FAIL,
                "dispatch.env is owner-only",
                f"mode is {oct(mode)} - run chmod 600 on configured dispatch.env",
            )
        else:
            record(PASS, "dispatch.env is owner-only", oct(mode))
    else:
        check_windows_acl(dest)

    try:
        env = parse_env_file(dest)
        record(PASS, "dispatch.env parses strictly", "known keys only; values withheld")
    except ConfigError as exc:
        record(FAIL, "dispatch.env parses strictly", str(exc))
        return {}
    # required: URL + the token var for this role + bus bin.
    need = ["AGENT_BUS_URL", ROLE_TO_TOKEN_VAR[role]]
    for key in need:
        if env.get(key):
            record(PASS, f"{key} set", "(value withheld)")
        else:
            record(FAIL, f"{key} set", "missing from dispatch.env")
    if env.get("AWF_BUS_BIN"):
        record(PASS, "AWF_BUS_BIN set", "(value withheld)")
    else:
        record(WARN, "AWF_BUS_BIN set", "unset -falls back to `agent-bus` on PATH")
    return env


def check_tool(env: dict, bin_key: str, default_name: str, label: str, required: bool) -> None:
    path = env.get(bin_key, "") or default_name
    ok = is_file(path) or (
        # bare name on PATH
        (os.sep not in path and "/" not in path)
        and run_command(
            ["where" if os.name == "nt" else "which", path],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    if ok:
        record(PASS, f"{label} present", "configured executable found")
    else:
        record(FAIL if required else WARN, f"{label} present", "configured executable not found")


def check_bus_reachable(env: dict, role: str) -> None:
    """Do a read-only, token-scoped Agent Bus call. Success == URL up + token valid."""
    url = env.get("AGENT_BUS_URL", "")
    token = env.get(ROLE_TO_TOKEN_VAR[role], "")
    bus = env.get("AWF_BUS_BIN", "agent-bus")
    if not (url and token):
        record(FAIL, "agent-bus reachable + token scope", "URL or token missing (see above)")
        return
    if not (
        is_file(bus)
        or run_command(
            ["where" if os.name == "nt" else "which", bus],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    ):
        record(WARN, "agent-bus reachable + token scope", "configured binary not found")
        return
    child = dict(os.environ)
    child["AGENT_BUS_URL"] = url
    child["AGENT_BUS_TOKEN"] = token
    child["AGENT_BUS_AGENT"] = role
    add_url_host_to_no_proxy(child, url)
    # Legacy files may still contain Git-Bash drive paths during migration;
    # native Windows CreateProcess needs the translated drive form.
    argv = [posix_to_native(bus), "pending", "--count"]
    try:
        proc = run_command(
            argv,
            env=child,
            capture_output=True,
            text=True,
            timeout=20,
            allow_shell_wrapper=True,
            secrets=(token,),
        )
    except ExecutionFailure as exc:
        status = FAIL if exc.diagnostic.kind == "timeout" else WARN
        record(status, "agent-bus reachable + token scope", exc.diagnostic.render())
        return
    count = proc.stdout.strip()
    if proc.returncode == 0 and count.isdigit():
        record(
            PASS,
            "agent-bus reachable + token scope",
            f"pending count={count}; endpoint withheld",
        )
    elif proc.returncode == 0:
        record(FAIL, "agent-bus reachable + token scope", "pending count was not an integer")
    else:
        record(
            FAIL,
            "agent-bus reachable + token scope",
            f"command failed (exit {proc.returncode}); endpoint withheld",
        )


def check_git_push(repo: str) -> None:
    if not repo:
        record(WARN, "git can push", "--repo not given; skipped")
        return
    rp = Path(repo)
    if not (rp / ".git").exists():
        record(WARN, "git can push", "repo path withheld; not a git work tree")
        return
    # --dry-run tests auth + connectivity WITHOUT pushing anything.
    proc = run_command(
        ["git", "-C", repo, "push", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if proc.returncode == 0:
        record(PASS, "git can push", "push --dry-run ok; repo path withheld")
    else:
        record(FAIL, "git can push", f"push --dry-run failed (exit {proc.returncode})")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="awf_handoff_check",
        description="Confirm this machine is ready to dispatch/execute Agent Workflow tasks.",
    )
    p.add_argument(
        "--role",
        default="coder",
        choices=sorted(ROLE_TO_TOKEN_VAR),
        help="which role's readiness to check (default: coder)",
    )
    p.add_argument("--repo", default="", help="target repo to test `git push --dry-run`")
    p.add_argument(
        "--dest", default="", help="dispatch.env path (default: ~/.config/awf/dispatch.env)"
    )
    p.add_argument(
        "--model-tool",
        default="",
        help="optional model CLI executable to probe with --version",
    )
    a = p.parse_args(argv)

    # Windows consoles default to a non-UTF-8 codec (gbk/cp936); tool/git error
    # text in `detail` may contain characters it can't encode. Reconfigure so a
    # stray byte degrades to a replacement char instead of crashing the report.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # older Python / non-reconfigurable stream

    dest = Path(a.dest) if a.dest else Path.home() / ".config/awf/dispatch.env"
    repo = Path(a.repo).resolve() if a.repo else Path.cwd().resolve()
    preflight_args = argparse.Namespace(
        repo=repo,
        repo_required=bool(a.repo),
        profile="handoff",
        config=dest.resolve(),
        state_root=default_state_root(),
        authority_manifest=Path(__file__).resolve().parent / "authority-manifest.example.json",
        source_role=a.role,
        target_role=a.role,
        upstream_remote="upstream",
        head_remote="fork",
        gh_bin="gh",
        model_tool=a.model_tool,
        run_id="",
        intent="taskcard",
    )
    report = run_fast(preflight_args).report
    print(f"awf handoff-check - role={a.role}")
    print("=" * 56)
    failures = 0
    for layer in report["layers"]:
        status = str(layer["status"])
        failures += status == FAIL
        mark = MARK[PASS if status == PASS else FAIL]
        line = f"  [{mark}] {status:4} {layer['id']}"
        if layer.get("error_code"):
            line += f" - {layer['error_code']}"
        print(line)
    print("=" * 56)
    if failures:
        print(f"RESULT: FAIL ({failures} required check(s) failed). Not ready to take over.")
        return 1
    print("RESULT: PASS. This machine is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
