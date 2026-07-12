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
import subprocess
import sys
from pathlib import Path

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
    """Convert a git-bash POSIX path (/d/...) to native (D:\\...) for probing on
    native Windows Python. dispatch.env stores POSIX form (git-bash sources it);
    we only convert for on-disk existence checks. No-op off Windows."""
    if os.name != "nt":
        return path
    if len(path) >= 3 and path[0] == "/" and path[2] == "/" and path[1].isalpha():
        path = f"{path[1].upper()}:/" + path[3:]
    return path.replace("/", "\\")


def is_file(path: str) -> bool:
    return Path(posix_to_native(path)).is_file()


def parse_env_file(path: Path) -> dict:
    """Parse `export KEY=VALUE` lines into a dict. Values are held, never logged."""
    out: dict = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def check_windows_acl(dest: Path) -> None:
    """On Windows, os.chmod can't express owner-only, so assert via icacls that
    the file's ACL was tightened (no inherited ACEs granting Administrators /
    Users / Everyone). awf_bootstrap.py sets this with `icacls /inheritance:r`.

    icacls echoes the file PATH on the first output line, then one ACE per line
    like `  DOMAIN\\user:(F)`. We must inspect only the ACE lines — the path
    itself often contains 'Users' (C:\\Users\\...) and would false-positive a
    naive substring scan of the whole blob."""
    proc = subprocess.run(["icacls", str(dest)], capture_output=True, text=True)
    if proc.returncode != 0:
        record(WARN, "dispatch.env is owner-only", "icacls could not read the ACL")
        return
    # icacls prints `<path> PRINCIPAL:(perms)` on line 1, then indented
    # `PRINCIPAL:(perms)` lines. Extract the ACE tokens with a regex so the
    # file path (which lives under C:\Users\...) can't be mistaken for a
    # 'Users' grant. Each ACE = a principal followed by :(...) permission flags.
    aces = re.findall(r"([A-Za-z0-9 \\_.-]+):(\([A-Za-z,()]*\)+)", proc.stdout)
    if not aces:
        record(WARN, "dispatch.env is owner-only", "could not parse icacls ACEs")
        return
    inherited = any("(I)" in perms for _principal, perms in aces)
    broad_names = ("Administrators", "Users", "Everyone", "Authenticated Users")
    broad = any(any(b in principal for b in broad_names) for principal, _perms in aces)
    if inherited or broad:
        record(
            FAIL,
            "dispatch.env is owner-only",
            "ACL grants more than the owner - re-run awf_bootstrap.py (icacls lockdown)",
        )
    else:
        record(PASS, "dispatch.env is owner-only", "icacls: no inherited/broad ACEs")


def check_dispatch_env(dest: Path, role: str) -> dict:
    if not dest.is_file():
        record(FAIL, "dispatch.env exists", f"{dest} not found -run awf_bootstrap.py")
        return {}
    record(PASS, "dispatch.env exists", str(dest))

    # permissions must be owner-only -never group/world/Administrators readable.
    if os.name != "nt":
        mode = stat.S_IMODE(dest.stat().st_mode)
        if mode & 0o077:
            record(
                FAIL, "dispatch.env is owner-only", f"mode is {oct(mode)} -run: chmod 600 {dest}"
            )
        else:
            record(PASS, "dispatch.env is owner-only", oct(mode))
    else:
        check_windows_acl(dest)

    env = parse_env_file(dest)
    # required: URL + the token var for this role + bus bin.
    need = ["AGENT_BUS_URL", ROLE_TO_TOKEN_VAR[role]]
    for key in need:
        if env.get(key):
            record(PASS, f"{key} set", "(value withheld)" if "TOKEN" in key else env[key])
        else:
            record(FAIL, f"{key} set", "missing from dispatch.env")
    if env.get("AWF_BUS_BIN"):
        record(PASS, "AWF_BUS_BIN set", env["AWF_BUS_BIN"])
    else:
        record(WARN, "AWF_BUS_BIN set", "unset -falls back to `agent-bus` on PATH")
    return env


def check_tool(env: dict, bin_key: str, default_name: str, label: str, required: bool) -> None:
    path = env.get(bin_key, "") or default_name
    ok = is_file(path) or (
        # bare name on PATH
        (os.sep not in path and "/" not in path)
        and subprocess.run(
            ["where" if os.name == "nt" else "which", path],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    if ok:
        record(PASS, f"{label} present", path)
    else:
        record(FAIL if required else WARN, f"{label} present", f"not found: {path}")


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
        or subprocess.run(
            ["where" if os.name == "nt" else "which", bus],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    ):
        record(WARN, "agent-bus reachable + token scope", f"agent-bus binary not found: {bus}")
        return
    child = dict(os.environ)
    child["AGENT_BUS_URL"] = url
    child["AGENT_BUS_TOKEN"] = token
    child["AGENT_BUS_AGENT"] = role
    # dispatch.env stores the git-bash POSIX path; native Windows Python's
    # CreateProcess needs D:\... form to actually launch the binary.
    argv = [posix_to_native(bus), "pending", "--count"]
    if os.name == "nt" and bus.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", *argv]
    try:
        proc = subprocess.run(argv, env=child, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        record(WARN, "agent-bus reachable + token scope", f"cannot exec {bus}")
        return
    except subprocess.TimeoutExpired:
        record(FAIL, "agent-bus reachable + token scope", f"timed out talking to {url}")
        return
    if proc.returncode == 0:
        record(PASS, "agent-bus reachable + token scope", f"{url} (pending --count ok)")
    else:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        detail = err[-1] if err else f"exit {proc.returncode}"
        record(FAIL, "agent-bus reachable + token scope", detail)


def check_git_push(repo: str) -> None:
    if not repo:
        record(WARN, "git can push", "--repo not given; skipped")
        return
    rp = Path(repo)
    if not (rp / ".git").exists():
        record(WARN, "git can push", f"{repo} is not a git work tree; skipped")
        return
    # --dry-run tests auth + connectivity WITHOUT pushing anything.
    proc = subprocess.run(
        ["git", "-C", repo, "push", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if proc.returncode == 0:
        record(PASS, "git can push", f"{repo} (push --dry-run ok)")
    else:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        detail = err[-1] if err else f"exit {proc.returncode}"
        record(FAIL, "git can push", detail)


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
    a = p.parse_args(argv)

    # Windows consoles default to a non-UTF-8 codec (gbk/cp936); tool/git error
    # text in `detail` may contain characters it can't encode. Reconfigure so a
    # stray byte degrades to a replacement char instead of crashing the report.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # older Python / non-reconfigurable stream

    dest = Path(a.dest) if a.dest else Path.home() / ".config/awf/dispatch.env"
    print(f"awf handoff-check - role={a.role}")
    print("=" * 56)

    env = check_dispatch_env(dest, a.role)
    if env:
        check_bus_reachable(env, a.role)
        # coder needs the executor tool; reviewer/architect don't strictly.
        if a.role == "coder":
            check_tool(env, "AWF_OPENCODE_BIN", "opencode", "opencode (executor)", required=True)
    check_git_push(a.repo)

    print()
    n_fail = 0
    for status, label, detail in results:
        n_fail += status == FAIL
        line = f"  [{MARK[status]}] {status:4} {label}"
        if detail:
            line += f" - {detail}"
        print(line)
    print("=" * 56)
    if n_fail:
        print(f"RESULT: FAIL ({n_fail} required check(s) failed). Not ready to take over.")
        return 1
    print("RESULT: PASS. This machine is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
