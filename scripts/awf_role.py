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
import re
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


def child_env() -> dict[str, str]:
    """Environment for spawned children: inherit-and-augment, never replace.

    A bare ``env={}`` breaks Windows DLL loading, and a service/cmd.exe context can
    strip variables git needs. So we always start from the full parent environment and
    only *add* what we require. ``PYTHONUTF8=1`` makes child Python processes decode as
    UTF-8 (no-op on POSIX; stops gbk crashes on Windows).
    """
    e = dict(os.environ)
    e.setdefault("PYTHONUTF8", "1")
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


def model_env() -> dict[str, str]:
    """Environment for model subprocesses: inherit parent, strip Agent Bus tokens.

    Keeps PATH, platform variables, ordinary AWF_* configuration, and UTF-8 settings.
    Removes AGENT_BUS_TOKEN, AGENT_BUS_AGENT_TOKENS, and any key matching AWF_*_TOKEN
    so credentials never reach untrusted model processes (OpenCode, Codex).
    """
    e = child_env()
    e.pop("AGENT_BUS_TOKEN", None)
    e.pop("AGENT_BUS_AGENT_TOKENS", None)
    for k in list(e):
        if k.startswith("AWF_") and k.endswith("_TOKEN"):
            del e[k]
    return e


def spawn(
    argv: list[str],
    *,
    cwd: str | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Run a command as a real argv (no shell). Handles Windows .cmd/.bat shims.

    Returns the process exit code. ``stdin``, if given, is fed to the process via
    ``input=``. When no explicit input is provided the child receives
    ``subprocess.DEVNULL`` instead of inheriting the handler's stdin, which is
    unreliable (especially on Windows).

    ``env`` defaults to ``child_env()`` (full parent environment). Pass
    ``model_env()`` for model subprocesses to strip credentials.
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
        stdin=subprocess.DEVNULL if stdin is None else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env or child_env(),
    )
    return proc.returncode


def git(repo: str, *args: str) -> int:
    return spawn(["git", "-C", repo, *args])


def git_out(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        env=child_env(),
    )
    # Use rstrip to preserve leading space in porcelain format
    # (e.g. " M a.py" — leading space means unmodified in index)
    return proc.stdout.rstrip("\n\r")


# ---------------------------------------------------------------------------
# ImplementationReport gate
# ---------------------------------------------------------------------------


def check_report(report_path: str) -> None:
    """Fail if ``--report`` is empty or the path is not a regular file.

    Called by coder after successful model execution but before git writes,
    and by reviewer after checkout but before model execution.
    This is an existence gate only — no content or schema validation is performed.
    """
    if not report_path:
        die("--report is required; ImplementationReport must exist before commit or review")
    if not Path(report_path).is_file():
        die(f"ImplementationReport not found: {report_path}")


# ---------------------------------------------------------------------------
# Postflight contract
# ---------------------------------------------------------------------------


class PostflightContract:
    """Frozen postflight contract parsed from a TaskCard awf-postflight block."""

    def __init__(
        self,
        allowed_paths: list[str],
        verification_commands: list[list[str]],
    ) -> None:
        self.allowed_paths = list(allowed_paths)
        self.verification_commands = [list(cmd) for cmd in verification_commands]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PostflightContract):
            return NotImplemented
        return (
            self.allowed_paths == other.allowed_paths
            and self.verification_commands == other.verification_commands
        )

    def __repr__(self) -> str:
        return (
            f"PostflightContract(allowed_paths={self.allowed_paths!r}, "
            f"verification_commands={self.verification_commands!r})"
        )


_POSTFLIGHT_RE = re.compile(r"<!--\s*awf-postflight\s*\n(.*?)\n\s*-->", re.DOTALL)

# Artifact denylist — paths that always fail even if in allowed_paths.
_DENY_PREFIXES: tuple[str, ...] = (
    ".venv/",
    "venv/",
    "env/",
    "__pycache__/",
    "node_modules/",
    "dist/",
    "build/",
    "coverage/",
    "htmlcov/",
)
_DENY_EXACT: tuple[str, ...] = (
    "Thumbs.db",
    ".DS_Store",
    ".coverage",
    "coverage.xml",
)
_DENY_SUFFIXES: tuple[str, ...] = (
    ".swp",
    ".swo",
    ".swn",
    ".bak",
    ".orig",
    ".pyc",
    ".pyo",
    ".log",
    ".pid",
    ".egg-info",
)


def _is_env_denied(path: str) -> bool:
    """True for .env variants that carry secrets, excluding example templates.

    Matches by basename so .env variants at any path depth are detected.
    """
    basename = os.path.basename(path)
    if basename == ".env":
        return True
    if basename.startswith(".env."):
        # Allow documented examples
        return basename not in (".env.example", ".env.template", ".env.sample")
    return False


def _path_is_denied(path: str) -> bool:
    """Check a single repository-relative path against the artifact denylist.

    Directory patterns (e.g. ``node_modules/``, ``.venv/``) are matched at any
    depth by path component, not only at root.  ``.env`` variants are matched by
    basename.  Suffix-based patterns match at any depth.
    """
    if _is_env_denied(path):
        return True

    # Match directory prefixes at any depth via path component
    path_components = path.split("/")
    for prefix in _DENY_PREFIXES:
        stripped = prefix.rstrip("/")
        if stripped in path_components:
            return True

    if os.path.basename(path) in _DENY_EXACT:
        return True
    if path.endswith(_DENY_SUFFIXES):
        return True
    # Also deny files inside .egg-info directories
    if ".egg-info/" in path:
        return True
    return False


def parse_postflight_contract(card_path: str) -> PostflightContract:
    """Parse, validate, and freeze the awf-postflight contract from a TaskCard.

    Must be called before the model runs so that model edits to the card file
    (which is deliberately absent from ``allowed_paths``) cannot change the
    contract.
    """
    text = Path(card_path).read_text(encoding="utf-8")
    m = _POSTFLIGHT_RE.search(text)
    if not m:
        die("task card has no awf-postflight contract block")

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        die(f"malformed awf-postflight contract: {e}")

    if not isinstance(data, dict):
        die("awf-postflight contract must be a JSON object")

    # Reject extra keys
    allowed_keys = {"allowed_paths", "verification_commands"}
    extra = set(data) - allowed_keys
    if extra:
        die(f"unexpected awf-postflight keys: {', '.join(sorted(extra))}")

    # --- allowed_paths ---
    raw_paths = data.get("allowed_paths", [])
    if not isinstance(raw_paths, list) or not raw_paths:
        die("awf-postflight allowed_paths must be a non-empty array")

    normalized: list[str] = []
    seen: set[str] = set()
    for p in raw_paths:
        if not isinstance(p, str) or not p.strip():
            die(f"invalid allowed_path entry: {p!r}")
        if "\\" in p:
            die(f"allowed path must use forward slashes: {p!r}")
        if p.startswith("/"):
            die(f"allowed path must be repo-relative (no leading slash): {p!r}")
        if ":" in p:
            die(f"allowed path must not be drive-qualified: {p!r}")
        if ".." in p.split("/"):
            die(f"allowed path must not contain parent traversal: {p!r}")
        if p in seen:
            die(f"duplicate allowed path: {p!r}")
        seen.add(p)
        normalized.append(p)

    # --- verification_commands ---
    raw_cmds = data.get("verification_commands", [])
    if not isinstance(raw_cmds, list) or not raw_cmds:
        die("awf-postflight verification_commands must be a non-empty array")

    commands: list[list[str]] = []
    for i, cmd in enumerate(raw_cmds):
        if not isinstance(cmd, list) or len(cmd) == 0:
            die(f"verification_commands[{i}] must be a non-empty array of strings")
        if not all(isinstance(s, str) for s in cmd):
            die(f"verification_commands[{i}] must contain only strings")
        if cmd[0] == "":
            die(f"verification_commands[{i}] has an empty executable")
        argv = list(cmd)
        if argv[0] == "{python}":
            argv[0] = sys.executable
        commands.append(argv)

    return PostflightContract(allowed_paths=normalized, verification_commands=commands)


# ---------------------------------------------------------------------------
# Postflight gates (run after model succeeds, before git write / send_event)
# ---------------------------------------------------------------------------


def run_verifications(repo: str, contract: PostflightContract) -> None:
    """Run every verification command in order. Stop at the first failure.

    Verification runs before the final Git delta collection so that files
    created by verification are subject to path/artifact checks.
    """
    for i, argv in enumerate(contract.verification_commands):
        log(f"postflight verification [{i + 1}/{len(contract.verification_commands)}]")
        rc = spawn(argv, cwd=repo, env=model_env())
        if rc != 0:
            die(f"postflight verification [{i + 1}] failed (rc={rc})")


def _collect_delta_paths(repo: str) -> list[str]:
    """Return all repository-relative paths that differ from HEAD.

    Uses NUL-delimited git output for safe handling of all path names
    (spaces, Unicode, quotes).  Covers tracked changes (staged + unstaged
    vs HEAD) and untracked non-ignored files.  With ``--no-renames`` a
    renamed file appears as a delete of the old name and an add of the new
    name, so both sides are captured.
    """
    paths: list[str] = []

    # Tracked changes: staged + unstaged from HEAD
    tracked = git_out(repo, "diff", "--name-only", "HEAD", "--no-renames", "-z")
    if tracked:
        paths.extend(p for p in tracked.split("\0") if p)

    # Untracked non-ignored files
    untracked = git_out(repo, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked:
        paths.extend(p for p in untracked.split("\0") if p)

    return paths


def run_postflight_delta_gates(repo: str, contract: PostflightContract) -> None:
    """Enforce allowed paths, artifact denylist, narrow secret scan, and diff check.

    Must be called after ``run_verifications`` and before ``git add``.
    """
    delta_paths = _collect_delta_paths(repo)

    # 1. Empty set check
    if not delta_paths:
        die("postflight: no changes detected after model execution")

    # 2. Allowed-path gate
    allowed_set = set(contract.allowed_paths)
    offending: list[str] = []
    for p in delta_paths:
        if p not in allowed_set:
            offending.append(p)
    if offending:
        die(
            "postflight: changed path(s) not in allowed_paths:\n  " + "\n  ".join(sorted(offending))
        )

    # 3. Artifact denylist gate (checked even if path is allowed)
    denied: list[str] = []
    for p in delta_paths:
        if _path_is_denied(p):
            denied.append(p)
    if denied:
        die("postflight: artifact denylist violation:\n  " + "\n  ".join(sorted(denied)))

    # 4. Narrow secret scan — added lines in tracked diffs + untracked file content
    _narrow_secret_scan(repo, delta_paths)

    # 5. git diff --check on full HEAD delta (staged + unstaged)
    rc = git(repo, "diff", "HEAD", "--check")
    if rc != 0:
        die("postflight: git diff HEAD --check found whitespace errors")


# ---------------------------------------------------------------------------
# Narrow secret scan
# ---------------------------------------------------------------------------


# High-confidence credential detectors: (label, regex)
_SECRET_DETECTORS: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN\s+(?:\S+\s+)?PRIVATE\s+KEY-----")),
    ("credential-url", re.compile(r"https?://[^/:@\s]+:[^/@\s]+@")),
    ("github-token", re.compile(r"gh[puosr]_[A-Za-z0-9_]{36,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
]


def _scan_text(text: str) -> str | None:
    """Return the first matching detector label, or None."""
    for label, pat in _SECRET_DETECTORS:
        if pat.search(text):
            return label
    return None


def _narrow_secret_scan(repo: str, delta_paths: list[str] | None = None) -> None:
    """Scan added content from tracked diffs and untracked files for secrets.

    Uses the full HEAD→working-tree diff (staged + unstaged) for tracked
    changes and NUL-delimited git output for untracked file discovery.
    Reports the first hit per-path with detector label only — never the value.
    Fails closed on unreadable untracked files.
    """
    if delta_paths is None:
        delta_paths = _collect_delta_paths(repo)

    # Identify untracked paths with NUL-delimited output, then scan each tracked
    # path independently.  This avoids parsing quoted, human-readable patch
    # headers and prevents configured diff helpers from transforming content or
    # executing in the credential-bearing runner environment.
    untracked_out = git_out(repo, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = {path for path in untracked_out.split("\0") if path}

    for path in delta_paths:
        if path in untracked:
            continue
        diff_out = git_out(
            repo,
            "diff",
            "HEAD",
            "--no-color",
            "--no-renames",
            "--no-textconv",
            "--no-ext-diff",
            "--unified=0",
            "--",
            path,
        )
        in_hunk = False
        for line in diff_out.splitlines():
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk and line.startswith("+"):
                label = _scan_text(line[1:])
                if label:
                    die(f"postflight secret scan: {label} in {path}")

    # Untracked regular files.
    if untracked_out:
        for path in untracked_out.split("\0"):
            if not path:
                continue
            full = os.path.join(repo, path)
            if os.path.isfile(full):
                try:
                    content = Path(full).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    die(f"postflight secret scan: unreadable-file in untracked file {path}")
                label = _scan_text(content)
                if label:
                    die(f"postflight secret scan: {label} in untracked file {path}")


# ---------------------------------------------------------------------------
# git helpers shared by all roles
# ---------------------------------------------------------------------------


_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def fetch_and_checkout(repo: str, branch: str, expected_commit: str) -> None:
    """Synchronize a clean checkout to the exact remote task branch."""
    log(f"preflight + fetch + checkout {branch} in {repo}")
    if git(repo, "check-ref-format", "--branch", branch) != 0:
        die(f"invalid task branch {branch!r}")
    if not _COMMIT_RE.fullmatch(expected_commit):
        die("event commit must be a 7-64 character hexadecimal Git object ID")

    dirty = git_out(repo, "status", "--porcelain")
    if dirty:
        die("working tree is dirty; commit, stash, or clean it before retrying")

    all_heads = "+refs/heads/*:refs/remotes/origin/*"
    if git(repo, "fetch", "--quiet", "--prune", "origin", all_heads) != 0:
        die("cannot fetch latest refs from origin")

    remote_ref = f"refs/remotes/origin/{branch}"
    if git(repo, "show-ref", "--verify", "--quiet", remote_ref) != 0:
        die(f"remote branch origin/{branch} does not exist")

    resolved_expected = git_out(repo, "rev-parse", "--verify", f"{expected_commit}^{{commit}}")
    remote_head = git_out(repo, "rev-parse", f"origin/{branch}")
    if not resolved_expected:
        die(f"event commit {expected_commit} is not available after fetch")
    if remote_head != resolved_expected:
        die(
            f"origin/{branch} changed after dispatch; expected {resolved_expected}, "
            f"found {remote_head}"
        )

    local_ref = f"refs/heads/{branch}"
    if git(repo, "show-ref", "--verify", "--quiet", local_ref) == 0:
        ahead = git_out(repo, "rev-list", "--count", f"origin/{branch}..{branch}")
        if not ahead.isdigit():
            die(f"cannot compare local branch {branch} with origin/{branch}")
        if int(ahead) > 0:
            die(f"local branch {branch} has unpushed commits; refusing to overwrite it")

    if git(repo, "checkout", "-q", "-B", branch, f"origin/{branch}") != 0:
        die(f"cannot checkout branch {branch} from origin/{branch}")

    head = git_out(repo, "rev-parse", "HEAD")
    if not head or head != remote_head:
        die(f"checkout {branch} is not synchronized with origin/{branch}")


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
    argv += ["--", read_text(prompt_file)]
    return spawn(argv, cwd=repo, env=model_env())


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
    return spawn(argv, cwd=repo, stdin=stdin, env=model_env())


def tool_opencode_review(repo: str, base: str, prompt_file: str, card_file: str, model: str) -> int:
    """Fallback reviewer using OpenCode (when Codex is unavailable)."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    argv = [binp, "run", "--dir", repo]
    if card_file and Path(card_file).is_file():
        argv += ["-f", card_file]
    if model:
        argv += ["-m", model]
    argv += ["--", read_text(prompt_file)]
    return spawn(argv, cwd=repo, env=model_env())


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
    cenv = child_env()
    cenv["AGENT_BUS_URL"] = url
    cenv["AGENT_BUS_TOKEN"] = token
    cenv["AGENT_BUS_AGENT"] = from_role
    argv = [
        bus,
        "send",
        "--from",
        from_role,
        "--to",
        to_role,
        "--type",
        etype,
        "--payload",
        json.dumps(payload),
    ]
    if os.name == "nt" and bus.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", *argv]
    log(f"send {etype}: {from_role} -> {to_role}")
    rc = subprocess.run(argv, env=cenv, stdin=subprocess.DEVNULL).returncode
    if rc != 0:
        log(f"WARN: failed to send {etype} (rc={rc})")
    return rc == 0


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------


def role_coder(a: argparse.Namespace) -> int:
    # Resolve to an absolute path: a relative/unresolved cwd is what makes git behave
    # differently under a service (cmd.exe) vs. an interactive shell.
    repo = str(Path(env("AWF_REPO_DIR", required=True)).resolve())
    script_dir = env("AWF_SCRIPT_DIR", required=True)
    prompt_file = os.path.join(script_dir, "executor-prompt.md")
    tool = env("AWF_TOOL", a.tool or "opencode")
    model = env("AWF_MODEL", a.model or "")
    no_push = env("AWF_NO_PUSH", "0") == "1"

    fetch_and_checkout(repo, a.branch, a.commit)
    card_file = os.path.join(repo, a.card)
    if not Path(card_file).is_file():
        die(f"card not found after checkout: {card_file}")

    # 2. Parse and freeze the TaskCard postflight contract before model starts
    contract = parse_postflight_contract(card_file)

    log(f"coder: branch={a.branch} tool={tool} model={model or '<default>'}")
    if tool == "opencode":
        rc = tool_opencode_exec(repo, card_file, prompt_file, model)
    else:
        die(f"coder: unsupported tool '{tool}'")
    if rc != 0:
        die(f"tool '{tool}' failed (rc={rc}); not announcing review")

    # 4. ImplementationReport gate — fail before any write or downstream event
    check_report(a.report)

    # 5. Rerun every verification command from the frozen contract
    run_verifications(repo, contract)

    # 6. Enforce all delta gates (paths, artifacts, secrets, diff check)
    run_postflight_delta_gates(repo, contract)

    # 7. commit + push the executor's output back to the same branch
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
    if not send_event(
        "coder",
        "reviewer",
        "task:awf-review",
        {
            "task_id": a.branch.rsplit("/", 1)[-1],
            "branch": a.branch,
            "card": a.card,
            "commit": new_commit,
            "report": a.report,
            "tool": tool,
            "model": model,
        },
    ):
        die("failed to send reviewer event; implementation will not be ACKed")
    return 0


def role_reviewer(a: argparse.Namespace) -> int:
    repo = str(Path(env("AWF_REPO_DIR", required=True)).resolve())
    script_dir = env("AWF_SCRIPT_DIR", required=True)
    prompt_file = os.path.join(script_dir, "reviewer-prompt.md")
    tool = env("AWF_TOOL", a.tool or "")
    model = env("AWF_MODEL", a.model or "")
    base = env("AWF_BASE", a.base or "master")

    fetch_and_checkout(repo, a.branch, a.commit)

    # ImplementationReport gate — fail before any model invocation
    check_report(a.report)

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

    send_event(
        "reviewer",
        "architect",
        "decision:awf-ready",
        {
            "task_id": a.branch.rsplit("/", 1)[-1],
            "branch": a.branch,
            "commit": a.commit,
            "verdict": verdict,
            "report": a.report,
        },
    )
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
