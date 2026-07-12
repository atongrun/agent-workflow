#!/usr/bin/env python3
"""awf_role — cross-platform Agent Workflow role handler.

This replaces the bash role handlers (roles/coder.sh, roles/reviewer.sh) and the
local executor (executors/local.sh). It is invoked by a role listener as the
Agent Bus `--on` handler when a stage event arrives:

    python awf_role.py coder    --branch B --card C --commit H --model M --tool T --report R
    python awf_role.py reviewer --branch B --card C ... --report R --base BASE

Why Python instead of bash: on Windows, agent-bus runs handlers through
`cmd.exe` (subprocess shell=True), where bash scripts collide with cmd quoting,
WSL's bash shadowing git-bash, and spaces in the git-bash path. Python runs
identically on macOS and Windows with no shell dialect, so one file works on
every executor machine.

Design:
  - Named arguments (not positional) so stage-to-stage field order can never drift.
  - Per-listener config comes from the environment (set by awf_listen.py):
      AWF_SCRIPT_DIR, AWF_REPO_DIR, AWF_TOOL, AWF_MODEL, AWF_BASE, AWF_NO_PUSH,
      AGENT_BUS_URL, AWF_BUS_BIN, AWF_<ROLE>_TOKEN, AWF_OPENCODE_BIN
  - The card/prompt travel as FILES (never inlined into a shell string).
  - External commands run via a list argv (no shell) so nothing is re-parsed;
    Windows .cmd/.bat shims are handled explicitly.
  - Exit 0 == success -> the agent-bus listener ACKs the event.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def log(msg: str) -> None:
    print(f"[awf_role] {msg}", flush=True)


def die(msg: str, code: int = 1):
    print(f"awf_role: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        die(f"missing required environment variable {name}")
    return val or ""


def spawn(argv: list[str], *, cwd: str | None = None, stdin: str | None = None) -> int:
    """Run a command as a real argv (no shell). Handles Windows .cmd/.bat shims.

    Returns the process exit code. stdin, if given, is fed to the process.
    """
    # On Windows, .cmd/.bat are not directly executable by CreateProcess; they
    # must go through the command interpreter. Wrap only those.
    run_argv = argv
    if os.name == "nt" and argv and argv[0].lower().endswith((".cmd", ".bat")):
        run_argv = ["cmd", "/c", *argv]
    log("exec: " + " ".join(run_argv))
    proc = subprocess.run(
        run_argv,
        cwd=cwd,
        input=stdin,
        text=True,
    )
    return proc.returncode


def git(repo: str, *args: str) -> int:
    return spawn(["git", "-C", repo, *args])


def git_out(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args], text=True, capture_output=True
    )
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# git helpers shared by all roles
# ---------------------------------------------------------------------------

def fetch_and_checkout(repo: str, branch: str) -> None:
    """Fetch the branch from origin and check it out (creating a tracking branch)."""
    log(f"fetch + checkout {branch} in {repo}")
    # Best-effort fetch; the branch may be local-only in single-machine tests.
    subprocess.run(["git", "-C", repo, "fetch", "--quiet", "origin", branch])
    if git(repo, "checkout", "-q", branch) != 0:
        if git(repo, "checkout", "-q", "-B", branch, f"origin/{branch}") != 0:
            die(f"cannot checkout branch {branch}")


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# tool adapters (inlined — no bash adapter files needed)
# ---------------------------------------------------------------------------

def tool_opencode_exec(repo: str, card_file: str, prompt_file: str, model: str) -> int:
    """Run OpenCode as an executor: edit code in `repo` per the card + prompt."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    argv = [binp, "run", "--dir", repo, "-f", card_file]
    if model:
        argv += ["-m", model]
    argv += [read_text(prompt_file)]
    return spawn(argv, cwd=repo)


def tool_codex_review(repo: str, base: str, prompt_file: str, card_file: str, model: str) -> int:
    """Run Codex as a reviewer: review the branch vs base. Read-only; instructions via stdin."""
    binp = env("AWF_CODEX_BIN", "codex")
    argv = [binp, "review", "-C", repo, "--base", base]
    if model:
        argv += ["-c", f"model={model}"]
    argv += ["-"]  # read review instructions from stdin
    stdin = read_text(prompt_file)
    if card_file and Path(card_file).is_file():
        stdin += "\n\n--- TaskCard (acceptance criteria to verify) ---\n\n" + read_text(card_file)
    return spawn(argv, cwd=repo, stdin=stdin)


def tool_opencode_review(repo: str, base: str, prompt_file: str, card_file: str, model: str) -> int:
    """Fallback reviewer using OpenCode (when Codex is unavailable)."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    argv = [binp, "run", "--dir", repo]
    if card_file and Path(card_file).is_file():
        argv += ["-f", card_file]
    if model:
        argv += ["-m", model]
    argv += [read_text(prompt_file)]
    return spawn(argv, cwd=repo)


# ---------------------------------------------------------------------------
# Agent Bus event emission (reuse the agent-bus CLI for auth consistency)
# ---------------------------------------------------------------------------

def send_event(from_role: str, to_role: str, etype: str, payload: dict) -> bool:
    url = env("AGENT_BUS_URL")
    bus = env("AWF_BUS_BIN", "agent-bus")
    token = env(f"AWF_{from_role.upper()}_TOKEN")
    if not (url and token):
        log(f"no AGENT_BUS_URL/AWF_{from_role.upper()}_TOKEN; skipping {etype} announcement")
        return False
    child_env = dict(os.environ)
    child_env["AGENT_BUS_URL"] = url
    child_env["AGENT_BUS_TOKEN"] = token
    child_env["AGENT_BUS_AGENT"] = from_role
    argv = [bus, "send", "--from", from_role, "--to", to_role,
            "--type", etype, "--payload", json.dumps(payload)]
    if os.name == "nt" and bus.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", *argv]
    log(f"send {etype}: {from_role} -> {to_role}")
    rc = subprocess.run(argv, env=child_env).returncode
    if rc != 0:
        log(f"WARN: failed to send {etype} (rc={rc})")
    return rc == 0


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------

def role_coder(a: argparse.Namespace) -> int:
    repo = env("AWF_REPO_DIR", required=True)
    script_dir = env("AWF_SCRIPT_DIR", required=True)
    prompt_file = os.path.join(script_dir, "executor-prompt.md")
    tool = env("AWF_TOOL", a.tool or "opencode")
    model = env("AWF_MODEL", a.model or "")
    no_push = env("AWF_NO_PUSH", "0") == "1"

    fetch_and_checkout(repo, a.branch)
    card_file = os.path.join(repo, a.card)
    if not Path(card_file).is_file():
        die(f"card not found after checkout: {card_file}")

    log(f"coder: branch={a.branch} tool={tool} model={model or '<default>'}")
    if tool == "opencode":
        rc = tool_opencode_exec(repo, card_file, prompt_file, model)
    else:
        die(f"coder: unsupported tool '{tool}'")
    if rc != 0:
        die(f"tool '{tool}' failed (rc={rc}); not announcing review")

    # commit + push the executor's output back to the same branch
    git(repo, "add", "-A")
    if git(repo, "diff", "--cached", "--quiet") != 0:
        msg = f"feat(awf): executor output for {a.branch} [{tool}]"
        if git(repo, "commit", "-q", "-m", msg) != 0:
            die("git commit failed (is git user.name/user.email configured on this machine?)")
        log(f"committed executor output on {a.branch}")
    else:
        log("no changes produced by the tool")
    if no_push:
        log("AWF_NO_PUSH=1: skipping push")
    elif git(repo, "push", "-u", "origin", a.branch) != 0:
        die("push failed (reviewer will not see the changes)")
    else:
        log(f"pushed {a.branch}")

    new_commit = git_out(repo, "rev-parse", "HEAD") or a.commit
    send_event("coder", "reviewer", "task:awf-review", {
        "task_id": a.branch.rsplit("/", 1)[-1],
        "branch": a.branch, "card": a.card, "commit": new_commit,
        "report": a.report, "tool": tool, "model": model,
    })
    return 0


def role_reviewer(a: argparse.Namespace) -> int:
    repo = env("AWF_REPO_DIR", required=True)
    script_dir = env("AWF_SCRIPT_DIR", required=True)
    prompt_file = os.path.join(script_dir, "reviewer-prompt.md")
    tool = env("AWF_TOOL", a.tool or "")
    model = env("AWF_MODEL", a.model or "")
    base = env("AWF_BASE", a.base or "master")

    fetch_and_checkout(repo, a.branch)
    card_file = os.path.join(repo, a.card)

    log(f"reviewer: branch={a.branch} tool={tool or '<human>'} base={base}")
    verdict = "needs-human-review"
    if tool == "codex":
        rc = tool_codex_review(repo, base, prompt_file, card_file, model)
        verdict = "tool-review-complete" if rc == 0 else "needs-human-review"
    elif tool == "opencode":
        rc = tool_opencode_review(repo, base, prompt_file, card_file, model)
        verdict = "tool-review-complete" if rc == 0 else "needs-human-review"
    else:
        log(f"no reviewer tool configured; branch {a.branch} checked out for human review")

    send_event("reviewer", "architect", "decision:awf-ready", {
        "task_id": a.branch.rsplit("/", 1)[-1],
        "branch": a.branch, "commit": a.commit,
        "verdict": verdict, "report": a.report,
    })
    return 0


ROLES = {"coder": role_coder, "reviewer": role_reviewer}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="awf_role", description="Agent Workflow role handler")
    p.add_argument("role", choices=sorted(ROLES))
    p.add_argument("--branch", required=True)
    p.add_argument("--card", default="")
    p.add_argument("--commit", default="")
    p.add_argument("--model", default="")
    p.add_argument("--tool", default="")
    p.add_argument("--report", default="")
    p.add_argument("--base", default="")
    a = p.parse_args(argv)
    return ROLES[a.role](a)


if __name__ == "__main__":
    raise SystemExit(main())
