#!/usr/bin/env python3
"""awf_role — cross-platform Agent Workflow role handler.

This replaces the bash role handlers (roles/coder.sh, roles/reviewer.sh) and the
local executor (executors/local.sh). It is invoked by a role listener as the
Agent Bus `--on` handler when a stage event arrives:

    python awf_role.py coder    --event-id ID --branch B --card C --commit H --tool T --report R
    python awf_role.py reviewer --event-id ID --branch B --card C ... --report R --base BASE

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
import time
from datetime import datetime, timezone
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


def event_run_directory(
    event_id: int,
    *,
    os_name: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the event-scoped OS state directory, always outside the checkout."""
    platform = os_name or os.name
    values = os.environ if environ is None else environ
    if platform == "nt":
        local_app_data = values.get("LOCALAPPDATA")
        if not local_app_data:
            die("LOCALAPPDATA is required for durable handler evidence on Windows")
        root = Path(local_app_data)
    else:
        xdg_state_home = values.get("XDG_STATE_HOME")
        root = Path(xdg_state_home) if xdg_state_home else (home or Path.home()) / ".local/state"
    return root / "agent-workflow" / "runs" / f"event-{event_id}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunEvidence:
    """Append durable phase records and atomically publish the latest run result."""

    def __init__(
        self,
        event_id: int,
        role: str,
        *,
        state_root: Path | None = None,
    ) -> None:
        self.event_id = event_id
        self.role = role
        self.run_dir = (
            Path(state_root) / f"event-{event_id}"
            if state_root is not None
            else event_run_directory(event_id)
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.run_dir / "handler.log"
        self.result_path = self.run_dir / "result.json"
        self.state: dict[str, object] = {
            "event_id": event_id,
            "role": role,
            "handler_pid": os.getpid(),
            "postflight_started": False,
            "postflight_status": "not_started",
        }

    def record(self, phase: str, **fields: object) -> None:
        """Persist one non-sensitive phase record and the latest aggregate state."""
        timestamp = _utc_now()
        if phase == "handler_exit":
            self.state["last_phase_before_exit"] = self.state.get("last_phase")
        self.state.update(fields)
        self.state["last_phase"] = phase
        self.state["updated_at"] = timestamp
        if "started_at" not in self.state:
            self.state["started_at"] = timestamp

        entry = {
            "time": timestamp,
            "event_id": self.event_id,
            "role": self.role,
            "phase": phase,
            **fields,
        }
        with self.log_path.open("a", encoding="utf-8", newline="\n") as log_file:
            log_file.write(json.dumps(entry, sort_keys=True) + "\n")
            log_file.flush()
            os.fsync(log_file.fileno())

        temp_path = self.result_path.with_name(f"result.json.tmp-{os.getpid()}")
        with temp_path.open("w", encoding="utf-8", newline="\n") as result_file:
            json.dump(self.state, result_file, indent=2, sort_keys=True)
            result_file.write("\n")
            result_file.flush()
            os.fsync(result_file.fileno())
        os.replace(temp_path, self.result_path)


def record(evidence: RunEvidence | None, phase: str, **fields: object) -> None:
    if evidence is not None:
        evidence.record(phase, **fields)


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


def verification_env() -> dict[str, str]:
    """Credential-free environment for default-locale verification commands."""
    e = model_env()
    e.pop("PYTHONUTF8", None)
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def spawn(
    argv: list[str],
    *,
    cwd: str | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    evidence: RunEvidence | None = None,
    tracked_phase: str | None = None,
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
    if evidence is not None and tracked_phase is not None:
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                run_argv,
                cwd=cwd,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env or child_env(),
            )
        except OSError as exc:
            record(
                evidence,
                f"{tracked_phase}_exit",
                **{
                    f"{tracked_phase}_rc": None,
                    f"{tracked_phase}_duration_seconds": round(time.monotonic() - started, 6),
                    f"{tracked_phase}_spawn_error": type(exc).__name__,
                },
            )
            raise
        record(
            evidence,
            f"{tracked_phase}_start",
            **{
                f"{tracked_phase}_pid": proc.pid,
                f"{tracked_phase}_cwd": str(Path(cwd).resolve()) if cwd else os.getcwd(),
            },
        )
        try:
            proc.communicate(stdin)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            record(
                evidence,
                f"{tracked_phase}_exit",
                **{
                    f"{tracked_phase}_rc": proc.poll(),
                    f"{tracked_phase}_duration_seconds": round(time.monotonic() - started, 6),
                    f"{tracked_phase}_interrupted": True,
                },
            )
            raise
        record(
            evidence,
            f"{tracked_phase}_exit",
            **{
                f"{tracked_phase}_rc": proc.returncode,
                f"{tracked_phase}_duration_seconds": round(time.monotonic() - started, 6),
            },
        )
        return proc.returncode
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


def push_and_verify_remote_head(repo: str, branch: str) -> str:
    """Push ``branch`` and return HEAD only after the exact remote ref matches it."""
    if git(repo, "push", "-u", "origin", branch) != 0:
        die("push failed (reviewer will not see the changes)")

    remote_ref = f"refs/remotes/origin/{branch}"
    refspec = f"+refs/heads/{branch}:{remote_ref}"
    if git(repo, "fetch", "--no-tags", "origin", refspec) != 0:
        die(f"failed to refresh origin/{branch} after push")

    local_head = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
    remote_head = git_out(repo, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    if not local_head:
        die("failed to resolve local HEAD after push")
    if not remote_head:
        die(f"failed to resolve refreshed origin/{branch} after push")
    if remote_head != local_head:
        die(f"refreshed origin/{branch} does not match local HEAD; reviewer handoff blocked")
    log(f"pushed and verified origin/{branch} at {local_head}")
    return local_head


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


_REVIEW_REPORT_RE = re.compile(r"<!--\s*awf-review-report\s*\n(.*?)\n\s*-->", re.DOTALL)
_REVIEW_VERDICTS = {"PASS", "REQUEST_CHANGES", "BLOCKED"}
_REVIEW_REPORT_MAX_BYTES = 16 * 1024
_REVIEW_REPORT_KEYS = {"verdict", "deterministic_failures", "blocked_reason"}
_DIFF_BODY_RE = re.compile(
    r"(?m)^(?:diff --git |@@ -|--- a/|\+\+\+ b/)|```(?:diff|patch)\s*$",
    re.IGNORECASE,
)


class DuplicateReviewReportKey(ValueError):
    """Raised when JSON object pairs contain a duplicate key."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateReviewReportKey(key)
        result[key] = value
    return result


def resolve_review_report_path(repo: str, report_path: str, implementation_report: str) -> Path:
    """Resolve one explicit repo-relative ReviewReport path without traversal."""
    if not report_path:
        die("--review-report is required")
    if "\\" in report_path or report_path.startswith("/") or ":" in report_path:
        die("ReviewReport path must be repository-relative and use forward slashes")
    if ".." in report_path.split("/"):
        die("ReviewReport path must not contain parent traversal")

    repo_root = Path(repo).resolve()
    resolved = (repo_root / report_path).resolve()
    if resolved == repo_root or repo_root not in resolved.parents:
        die("ReviewReport path escapes the repository")

    implementation_path = Path(implementation_report)
    if not implementation_path.is_absolute():
        implementation_path = repo_root / implementation_path
    if resolved == implementation_path.resolve():
        die("ReviewReport path must be distinct from ImplementationReport path")
    return resolved


def _validate_deterministic_failure(item: object, index: int) -> dict[str, object]:
    if not isinstance(item, dict):
        die(f"deterministic_failures[{index}] must be an object")
    expected = {"evidence", "required_correction"}
    if set(item) != expected:
        die(f"deterministic_failures[{index}] has invalid fields")
    correction = item["required_correction"]
    evidence = item["evidence"]
    if not isinstance(correction, str) or not correction.strip():
        die(f"deterministic_failures[{index}] requires a correction")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("kind"), str):
        die(f"deterministic_failures[{index}] requires structured evidence")

    kind = evidence["kind"]
    if kind == "criterion":
        expected_evidence = {"kind", "criterion"}
        valid = isinstance(evidence.get("criterion"), str) and bool(evidence["criterion"].strip())
    elif kind == "command":
        expected_evidence = {"kind", "command", "result"}
        valid = all(
            isinstance(evidence.get(key), str) and bool(evidence[key].strip())
            for key in ("command", "result")
        )
    elif kind == "file_line":
        expected_evidence = {"kind", "file", "line"}
        file_name = evidence.get("file")
        line = evidence.get("line")
        valid = (
            isinstance(file_name, str)
            and bool(file_name.strip())
            and not file_name.startswith("/")
            and "\\" not in file_name
            and ".." not in file_name.split("/")
            and isinstance(line, int)
            and not isinstance(line, bool)
            and line > 0
        )
    else:
        die(f"deterministic_failures[{index}] has unknown evidence kind")
    if set(evidence) != expected_evidence or not valid:
        die(f"deterministic_failures[{index}] lacks precise evidence")
    return {"evidence": dict(evidence), "required_correction": correction.strip()}


def parse_review_report(report_path: Path) -> dict[str, object]:
    """Validate and normalize a bounded ReviewReport for downstream payloads."""
    try:
        markdown = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        die(f"ReviewReport is missing or unreadable: {report_path}")
    if not markdown.strip():
        die("ReviewReport is empty")
    if _DIFF_BODY_RE.search(markdown):
        die("ReviewReport must not contain full diff or patch bodies")
    secret_label = _scan_text(markdown)
    if secret_label:
        die(f"ReviewReport contains prohibited {secret_label} material")

    blocks = _REVIEW_REPORT_RE.findall(markdown)
    if len(blocks) != 1:
        die("ReviewReport must contain exactly one awf-review-report object")
    try:
        data = json.loads(blocks[0], object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, DuplicateReviewReportKey):
        die("ReviewReport machine object is malformed or contains duplicate fields")
    if not isinstance(data, dict) or set(data) != _REVIEW_REPORT_KEYS:
        die("ReviewReport machine object has missing or unknown fields")

    verdict = data["verdict"]
    if not isinstance(verdict, str) or verdict not in _REVIEW_VERDICTS:
        die("ReviewReport verdict must be exactly PASS, REQUEST_CHANGES, or BLOCKED")
    failures = data["deterministic_failures"]
    if not isinstance(failures, list):
        die("ReviewReport deterministic_failures must be an array")
    normalized_failures = [
        _validate_deterministic_failure(item, index) for index, item in enumerate(failures)
    ]
    blocked_reason = data["blocked_reason"]
    if not isinstance(blocked_reason, str):
        die("ReviewReport blocked_reason must be a string")
    blocked_reason = blocked_reason.strip()

    if verdict == "PASS" and normalized_failures:
        die("PASS ReviewReport cannot contain deterministic failures")
    if verdict == "REQUEST_CHANGES" and not normalized_failures:
        die("REQUEST_CHANGES requires deterministic failure evidence")
    if verdict == "BLOCKED" and not blocked_reason:
        die("BLOCKED requires an escalation reason")
    if verdict != "BLOCKED" and blocked_reason:
        die("blocked_reason is only valid for BLOCKED")

    normalized: dict[str, object] = {
        "format": "awf.review-report.v1",
        "verdict": verdict,
        "deterministic_failures": normalized_failures,
        "blocked_reason": blocked_reason,
        "markdown": markdown,
    }
    # Match send_event()'s JSON representation so the bound applies to the bytes that
    # are actually embedded in the downstream payload, including escaped Unicode.
    encoded = json.dumps(normalized).encode("utf-8")
    if len(encoded) > _REVIEW_REPORT_MAX_BYTES:
        die("normalized ReviewReport exceeds 16 KiB")
    return normalized


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
        rc = spawn(argv, cwd=repo, env=verification_env())
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


def tool_opencode_exec(
    repo: str,
    card_file: str,
    prompt_file: str,
    model: str,
    evidence: RunEvidence | None = None,
) -> int:
    """Run OpenCode as an executor: edit code in `repo` per the card + prompt."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    argv = [binp, "run", "--dir", repo, "-f", card_file]
    if model:
        argv += ["-m", model]
    argv += ["--", read_text(prompt_file)]
    if evidence is not None:
        return spawn(
            argv,
            cwd=repo,
            env=model_env(),
            evidence=evidence,
            tracked_phase="opencode",
        )
    return spawn(argv, cwd=repo, env=model_env())


def tool_codex_review(
    repo: str,
    base: str,
    prompt_file: str,
    card_file: str,
    model: str,
    review_report_path: str,
) -> int:
    """Run Codex review and persist its final response at the exact report path."""
    binp = env("AWF_CODEX_BIN", "codex")
    argv = [
        binp,
        "exec",
        "-C",
        repo,
        "--sandbox",
        "read-only",
        "--output-last-message",
        review_report_path,
    ]
    if model:
        argv += ["--model", model]
    argv += ["review", "--base", base, "-"]
    stdin = read_text(prompt_file)
    stdin += f"\n\nWrite the complete ReviewReport to exactly: {review_report_path}\n"
    if card_file and Path(card_file).is_file():
        stdin += "\n\n--- TaskCard (acceptance criteria to verify) ---\n\n" + read_text(card_file)
    return spawn(argv, cwd=repo, stdin=stdin, env=model_env())


def tool_opencode_review(
    repo: str,
    base: str,
    prompt_file: str,
    card_file: str,
    model: str,
    review_report_path: str,
    evidence: RunEvidence | None = None,
) -> int:
    """Fallback reviewer using OpenCode (when Codex is unavailable)."""
    binp = env("AWF_OPENCODE_BIN", "opencode")
    argv = [binp, "run", "--dir", repo]
    if card_file and Path(card_file).is_file():
        argv += ["-f", card_file]
    if model:
        argv += ["-m", model]
    instructions = read_text(prompt_file)
    instructions += f"\n\nWrite the complete ReviewReport to exactly: {review_report_path}\n"
    argv += ["--", instructions]
    if evidence is not None:
        return spawn(
            argv,
            cwd=repo,
            env=model_env(),
            evidence=evidence,
            tracked_phase="opencode",
        )
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
    evidence = getattr(a, "evidence", None)

    fetch_and_checkout(repo, a.branch, a.commit)
    card_file = os.path.join(repo, a.card)
    if not Path(card_file).is_file():
        die(f"card not found after checkout: {card_file}")

    # 2. Parse and freeze the TaskCard postflight contract before model starts
    contract = parse_postflight_contract(card_file)

    log(f"coder: branch={a.branch} tool={tool} model={model or '<default>'}")
    if tool == "opencode":
        rc = tool_opencode_exec(repo, card_file, prompt_file, model, evidence)
    else:
        die(f"coder: unsupported tool '{tool}'")
    if rc != 0:
        die(f"tool '{tool}' failed (rc={rc}); not announcing review")

    record(
        evidence,
        "postflight_start",
        postflight_started=True,
        postflight_status="running",
    )
    try:
        # 4. ImplementationReport gate — fail before any write or downstream event
        check_report(a.report)

        # 5. Rerun every verification command from the frozen contract
        run_verifications(repo, contract)

        # 6. Enforce all delta gates (paths, artifacts, secrets, diff check)
        run_postflight_delta_gates(repo, contract)
    except BaseException:
        record(evidence, "postflight_fail", postflight_status="fail")
        raise
    record(evidence, "postflight_pass", postflight_status="pass")

    # 7. commit + push the executor's output back to the same branch
    record(evidence, "commit", commit_status="running")
    git(repo, "add", "-A")
    if git(repo, "diff", "--cached", "--quiet") != 0:
        msg = f"feat(awf): executor output for {a.branch} [{tool}]"
        if git(repo, "commit", "-q", "-m", msg) != 0:
            die("git commit failed (is git user.name/user.email configured on this machine?)")
        log(f"committed executor output on {a.branch}")
    else:
        log("no changes produced by the tool")
    commit_sha = git_out(repo, "rev-parse", "--verify", "HEAD^{commit}")
    record(evidence, "commit", commit_status="pass", commit_sha=commit_sha)
    if no_push:
        die(
            "AWF_NO_PUSH=1 cannot complete the trusted coder handler; "
            "remote review handoff requires a verified push"
        )
    record(evidence, "push", push_started=True)
    new_commit = push_and_verify_remote_head(repo, a.branch)
    record(evidence, "remote_sha_verified", remote_sha=new_commit)
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
            "review_report": a.review_report,
            "tool": tool,
            "model": model,
        },
    ):
        die("failed to send reviewer event; implementation will not be ACKed")
    record(evidence, "review_event_sent", review_event_sent=True)
    return 0


def role_reviewer(a: argparse.Namespace) -> int:
    repo = str(Path(env("AWF_REPO_DIR", required=True)).resolve())
    script_dir = env("AWF_SCRIPT_DIR", required=True)
    prompt_file = os.path.join(script_dir, "reviewer-prompt.md")
    tool = env("AWF_TOOL", a.tool or "")
    model = env("AWF_MODEL", a.model or "")
    base = env("AWF_BASE", a.base or "master")
    evidence = getattr(a, "evidence", None)

    fetch_and_checkout(repo, a.branch, a.commit)

    # ImplementationReport gate — fail before any model invocation
    check_report(a.report)
    review_report_path = resolve_review_report_path(repo, a.review_report, a.report)
    if git_out(repo, "ls-files", "--", a.review_report):
        die("ReviewReport path must not replace a tracked repository file")
    review_report_path.parent.mkdir(parents=True, exist_ok=True)
    if review_report_path.exists():
        review_report_path.unlink()

    card_file = os.path.join(repo, a.card)

    log(f"reviewer: branch={a.branch} tool={tool or '<human>'} base={base}")
    if tool == "codex":
        rc = tool_codex_review(repo, base, prompt_file, card_file, model, a.review_report)
    elif tool == "opencode":
        rc = tool_opencode_review(
            repo,
            base,
            prompt_file,
            card_file,
            model,
            a.review_report,
            evidence,
        )
    else:
        die("reviewer tool must be codex or opencode")
    if rc != 0:
        die(f"reviewer tool '{tool}' failed (rc={rc}); no verdict routed")

    review_report = parse_review_report(review_report_path)
    verdict = review_report["verdict"]
    route = {
        "PASS": ("architect", "decision:awf-ready"),
        "REQUEST_CHANGES": ("coder", "task:awf-rework"),
        "BLOCKED": ("architect", "decision:awf-blocked"),
    }[verdict]
    payload = {
        "task_id": a.branch.rsplit("/", 1)[-1],
        "branch": a.branch,
        "card": a.card,
        "commit": a.commit,
        "report": a.report,
        "review_report_path": a.review_report,
        "review_report": review_report,
        "tool": a.tool,
        "model": a.model,
    }
    if not send_event("reviewer", route[0], route[1], payload):
        die(f"failed to send {route[1]}; review event will not be ACKed")
    return 0


ROLES = {"coder": role_coder, "reviewer": role_reviewer}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="awf_role", description="Agent Workflow role handler")
    p.add_argument("role", choices=sorted(ROLES))
    p.add_argument("--event-id", required=True, type=int)
    p.add_argument("--branch", required=True)
    p.add_argument("--card", default="")
    p.add_argument("--commit", default="")
    p.add_argument("--model", default="")
    p.add_argument("--tool", default="")
    p.add_argument("--report", default="")
    p.add_argument("--review-report", dest="review_report", default="")
    p.add_argument("--base", default="")
    a = p.parse_args(argv)
    if a.event_id < 1:
        p.error("--event-id must be a positive integer")
    a.evidence = RunEvidence(a.event_id, a.role)
    a.evidence.record(
        "handler_start",
        handler_pid=os.getpid(),
        postflight_started=False,
        postflight_status="not_started",
    )
    try:
        rc = ROLES[a.role](a)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
        a.evidence.record("handler_exit", handler_rc=exit_code)
        raise
    except BaseException:
        a.evidence.record("handler_exit", handler_rc=1)
        raise
    a.evidence.record("handler_exit", handler_rc=rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
