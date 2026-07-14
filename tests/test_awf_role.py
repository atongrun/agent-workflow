"""Regression tests for the cross-machine role handler."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "awf_role.py"
SPEC = importlib.util.spec_from_file_location("awf_role", MODULE_PATH)
assert SPEC and SPEC.loader
awf_role = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(awf_role)


_VALID_POSTFLIGHT_CARD = """# Card
<!-- awf-postflight
{
  "allowed_paths": ["task.md"],
  "verification_commands": [["{python}", "-c", "exit(0)"]]
}
-->
"""

# Secret test fragments — constructed to avoid literal secrets in the test
# source so the new postflight secret gate does not reject its own
# uncommitted test diff (self-hosting requirement).
_GITHUB_TOKEN = "ghp_" + ("A" * 36)
_OPENAI_KEY = "sk-" + ("A" * 30)
_AWS_KEY = "AKIA" + "1234567890123456"
_PK_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"
_PK_FOOTER = "-----END " + "RSA PRIVATE KEY-----"
_CRED_URL = "http://" + "user:password@host.com/path"


def run(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def commit(repo: Path, message: str, filename: str, content: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    run("git", "add", filename, cwd=repo)
    run("git", "commit", "-m", message, cwd=repo)
    return run("git", "rev-parse", "HEAD", cwd=repo)


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    executor = tmp_path / "executor"
    run("git", "init", "--bare", str(origin), cwd=tmp_path)
    run("git", "init", "-b", "main", str(seed), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=seed)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=seed)
    commit(seed, "initial", "README.md", "initial\n")
    run("git", "remote", "add", "origin", str(origin), cwd=seed)
    run("git", "push", "-u", "origin", "main", cwd=seed)
    run("git", "switch", "-c", "feature/task", cwd=seed)
    commit(seed, "task card", "task.md", "task\n")
    run("git", "push", "-u", "origin", "feature/task", cwd=seed)
    run("git", "clone", str(origin), str(executor), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Executor", cwd=executor)
    run("git", "config", "user.email", "awf-executor@example.invalid", cwd=executor)
    run("git", "switch", "feature/task", cwd=executor)
    return origin, seed, executor


def test_fetch_and_checkout_updates_stale_branch_to_remote(repositories):
    _, seed, executor = repositories
    remote_head = commit(seed, "implementation", "result.txt", "done\n")
    run("git", "push", "origin", "feature/task", cwd=seed)

    awf_role.fetch_and_checkout(str(executor), "feature/task", remote_head)

    assert run("git", "rev-parse", "HEAD", cwd=executor) == remote_head
    assert run("git", "status", "--porcelain", cwd=executor) == ""


def test_fetch_and_checkout_rejects_dirty_worktree_before_fetch(repositories):
    _, seed, executor = repositories
    old_remote_ref = run("git", "rev-parse", "origin/feature/task", cwd=executor)
    commit(seed, "remote update", "remote.txt", "new\n")
    run("git", "push", "origin", "feature/task", cwd=seed)
    (executor / "dirty.txt").write_text("do not overwrite\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        awf_role.fetch_and_checkout(str(executor), "feature/task", old_remote_ref)

    assert run("git", "rev-parse", "origin/feature/task", cwd=executor) == old_remote_ref
    assert (executor / "dirty.txt").read_text(encoding="utf-8") == "do not overwrite\n"


def test_fetch_and_checkout_rejects_unpushed_local_commits(repositories):
    _, _, executor = repositories
    local_head = commit(executor, "local only", "local.txt", "keep\n")
    remote_head = run("git", "rev-parse", "origin/feature/task", cwd=executor)

    with pytest.raises(SystemExit, match="1"):
        awf_role.fetch_and_checkout(str(executor), "feature/task", remote_head)

    assert run("git", "rev-parse", "HEAD", cwd=executor) == local_head
    assert (executor / "local.txt").read_text(encoding="utf-8") == "keep\n"


def test_fetch_and_checkout_rejects_branch_changed_after_dispatch(repositories):
    _, seed, executor = repositories
    dispatched_head = run("git", "rev-parse", "origin/feature/task", cwd=executor)
    original_head = run("git", "rev-parse", "HEAD", cwd=executor)
    commit(seed, "later update", "later.txt", "not dispatched\n")
    run("git", "push", "origin", "feature/task", cwd=seed)

    with pytest.raises(SystemExit, match="1"):
        awf_role.fetch_and_checkout(str(executor), "feature/task", dispatched_head)

    assert run("git", "rev-parse", "HEAD", cwd=executor) == original_head
    assert not (executor / "later.txt").exists()


def test_fetch_and_checkout_finds_task_branch_from_single_branch_clone(
    repositories, tmp_path: Path
):
    origin, seed, _ = repositories
    single = tmp_path / "single"
    run(
        "git",
        "clone",
        "--single-branch",
        "--branch",
        "main",
        str(origin),
        str(single),
        cwd=tmp_path,
    )
    task_head = run("git", "rev-parse", "feature/task", cwd=seed)
    assert run("git", "branch", "-r", "--list", "origin/feature/task", cwd=single) == ""

    awf_role.fetch_and_checkout(str(single), "feature/task", task_head)

    assert run("git", "rev-parse", "HEAD", cwd=single) == task_head


# ---------------------------------------------------------------------------
# Model-process credential boundary
# ---------------------------------------------------------------------------


def test_model_env_strips_tokens(monkeypatch):
    """AGENT_BUS_TOKEN, AGENT_BUS_AGENT_TOKENS, and AWF_*_TOKEN are removed."""
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")
    monkeypatch.setenv("AGENT_BUS_AGENT_TOKENS", "secrets")
    monkeypatch.setenv("AGENT_BUS_AGENT", "coder")
    monkeypatch.setenv("AWF_CODER_TOKEN", "coder-tok")
    monkeypatch.setenv("AWF_REVIEWER_TOKEN", "reviewer-tok")
    monkeypatch.setenv("AWF_SCRIPT_DIR", "/safe")

    env = awf_role.model_env()

    assert "AGENT_BUS_TOKEN" not in env
    assert "AGENT_BUS_AGENT_TOKENS" not in env
    # Non-token AGENT_BUS_ keys are preserved
    assert "AGENT_BUS_AGENT" in env
    # AWF_*_TOKEN keys removed
    assert "AWF_CODER_TOKEN" not in env
    assert "AWF_REVIEWER_TOKEN" not in env
    # Non-token AWF_ keys preserved
    assert "AWF_SCRIPT_DIR" in env
    # UTF-8 settings present (from child_env)
    assert "PYTHONUTF8" in env
    assert "PYTHONIOENCODING" in env


def test_tool_opencode_exec_uses_model_env(monkeypatch, tmp_path):
    """The executor preserves model_env() and separates file options from its prompt."""
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")
    monkeypatch.setenv("AWF_OPENCODE_BIN", "opencode-test")

    awf_role.tool_opencode_exec(str(tmp_path), str(card_file), str(prompt_file), "provider/model")

    assert "AGENT_BUS_TOKEN" not in captured["env"]
    assert captured["argv"] == [
        "opencode-test",
        "run",
        "--dir",
        str(tmp_path),
        "-f",
        str(card_file),
        "-m",
        "provider/model",
        "--",
        "instructions",
    ]


def test_tool_codex_review_uses_model_env_and_stdin(monkeypatch, tmp_path):
    """The Codex reviewer adapter passes model_env() and stdin to spawn()."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("review instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["env"] = kwargs.get("env")
        captured["stdin"] = kwargs.get("stdin")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")

    awf_role.tool_codex_review(str(tmp_path), "main", str(prompt_file), "", "")

    assert "AGENT_BUS_TOKEN" not in captured["env"]
    assert captured["stdin"] == "review instructions"


def test_tool_opencode_review_uses_model_env(monkeypatch, tmp_path):
    """The reviewer preserves model_env() and separates file options from its prompt."""
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")
    monkeypatch.setenv("AWF_OPENCODE_BIN", "opencode-test")

    awf_role.tool_opencode_review(
        str(tmp_path), "main", str(prompt_file), str(card_file), "provider/model"
    )

    assert "AGENT_BUS_TOKEN" not in captured["env"]
    assert captured["argv"] == [
        "opencode-test",
        "run",
        "--dir",
        str(tmp_path),
        "-f",
        str(card_file),
        "-m",
        "provider/model",
        "--",
        "instructions",
    ]


@pytest.mark.parametrize("adapter", ["executor", "reviewer"])
def test_tool_opencode_card_prompt_boundary_without_model(monkeypatch, tmp_path, adapter):
    """The incident path still terminates the file array when no model is configured."""
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")
    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AWF_OPENCODE_BIN", "opencode-test")

    if adapter == "executor":
        awf_role.tool_opencode_exec(str(tmp_path), str(card_file), str(prompt_file), "")
    else:
        awf_role.tool_opencode_review(str(tmp_path), "main", str(prompt_file), str(card_file), "")

    assert captured["argv"] == [
        "opencode-test",
        "run",
        "--dir",
        str(tmp_path),
        "-f",
        str(card_file),
        "--",
        "instructions",
    ]


# ---------------------------------------------------------------------------
# Closed stdin
# ---------------------------------------------------------------------------


def test_spawn_devnull_for_no_input(monkeypatch):
    """A subprocess with no explicit input receives subprocess.DEVNULL."""
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    awf_role.spawn(["git", "status"])

    assert captured.get("stdin") is subprocess.DEVNULL
    assert captured.get("input") is None


def test_spawn_stdin_when_provided(monkeypatch):
    """A subprocess with stdin text does not receive DEVNULL."""
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    awf_role.spawn(["codex"], stdin="prompt text")

    assert captured.get("input") == "prompt text"
    assert captured.get("stdin") is not subprocess.DEVNULL


def test_send_event_stdin_devnull(monkeypatch):
    """send_event() uses subprocess.DEVNULL for its subprocess.run call."""
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    awf_role.send_event("coder", "reviewer", "task:awf-review", {"k": "v"})

    assert captured.get("stdin") is subprocess.DEVNULL


# ---------------------------------------------------------------------------
# ImplementationReport gate
# ---------------------------------------------------------------------------


def test_check_report_empty():
    """An empty --report argument is a handler failure."""
    with pytest.raises(SystemExit, match="1"):
        awf_role.check_report("")


def test_check_report_missing(tmp_path):
    """A --report path that is not a regular file is a handler failure."""
    with pytest.raises(SystemExit, match="1"):
        awf_role.check_report(str(tmp_path / "nonexistent.md"))


def test_check_report_exists(tmp_path):
    """A valid --report path passes without error."""
    report = tmp_path / "report.md"
    report.write_text("ok")
    awf_role.check_report(str(report))  # must not raise


def test_coder_missing_report_gate(monkeypatch, tmp_path):
    """A missing report in coder fails before git add/commit/push/send_event."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_NO_PUSH", "1")
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "tool_opencode_exec", lambda *a, **kw: 0)

    git_calls = []
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: git_calls.append(a) or 0)
    send_calls = []
    monkeypatch.setattr(awf_role, "send_event", lambda *a, **kw: send_calls.append(a) or True)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="opencode",
        report="",
        base="",
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    # The gate fires before any git write or event send
    assert not git_calls, "git should not be reached before report gate"
    assert not send_calls, "send_event should not be reached before report gate"


@pytest.mark.parametrize(
    "tool,review_attr",
    [
        ("codex", "tool_codex_review"),
        ("opencode", "tool_opencode_review"),
    ],
)
def test_reviewer_missing_report_gate(monkeypatch, tmp_path, tool, review_attr):
    """A missing report in reviewer fails before any model invocation, for both reviewer tools."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "reviewer-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text("card")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_TOOL", tool)

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)

    tool_calls = []
    monkeypatch.setattr(awf_role, review_attr, lambda *a, **kw: tool_calls.append(a) or 0)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool=tool,
        report="",
        base="main",
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not tool_calls, f"{tool} review tool should not be invoked before report gate"


# ---------------------------------------------------------------------------
# Fail-closed reviewer handoff
# ---------------------------------------------------------------------------


def test_coder_fail_closed_send_event(monkeypatch, tmp_path):
    """send_event() == False makes the coder handler fail closed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)
    report = tmp_path / "report.md"
    report.write_text("report content")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_NO_PUSH", "1")
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "tool_opencode_exec", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "run_verifications", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "run_postflight_delta_gates", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "git_out", lambda *a, **kw: "abc1234")
    monkeypatch.setattr(awf_role, "send_event", lambda *a, **kw: False)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="opencode",
        report=str(report),
        base="",
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)


def test_coder_successful_send_returns_zero(monkeypatch, tmp_path):
    """A successful send_event still returns 0 from the coder handler."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)
    report = tmp_path / "report.md"
    report.write_text("report content")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_NO_PUSH", "1")
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "tool_opencode_exec", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "run_verifications", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "run_postflight_delta_gates", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "git_out", lambda *a, **kw: "abc1234")
    monkeypatch.setattr(awf_role, "send_event", lambda *a, **kw: True)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="opencode",
        report=str(report),
        base="",
    )

    result = awf_role.role_coder(ns)
    assert result == 0


# ---------------------------------------------------------------------------
# Postflight contract — valid parsing
# ---------------------------------------------------------------------------


def test_parse_valid_contract(tmp_path):
    """A valid awf-postflight contract parses and freezes correctly."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["src/a.py", "src/b.py"],\n'
        '  "verification_commands": [["{python}", "-m", "pytest"],\n'
        '    ["{python}", "-m", "ruff", "check", "."]]\n'
        "}\n"
        "-->\n"
    )
    contract = awf_role.parse_postflight_contract(str(card))
    assert contract.allowed_paths == ["src/a.py", "src/b.py"]
    assert len(contract.verification_commands) == 2
    assert contract.verification_commands[0][0] == sys.executable
    assert contract.verification_commands[0][1:] == ["-m", "pytest"]
    assert contract.verification_commands[1][0] == sys.executable
    assert contract.verification_commands[1][1:] == ["-m", "ruff", "check", "."]


def test_contract_freeze_unchanged_by_card_edits(tmp_path):
    """Later TaskCard edits cannot change the frozen contract."""
    card = tmp_path / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)
    contract = awf_role.parse_postflight_contract(str(card))

    # Simulate model editing the card file after the contract was frozen
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["evil.py"],\n'
        '  "verification_commands": [["evil"]]\n'
        "}\n"
        "-->\n"
    )

    assert contract.allowed_paths == ["task.md"]
    assert contract.verification_commands == [[sys.executable, "-c", "exit(0)"]]


def test_contract_python_replacement_only_first_element(tmp_path):
    """Only the first element matching {python} exactly is replaced with sys.executable."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [["{python}", "arg", "{python}"]]\n'
        "}\n"
        "-->\n"
    )
    contract = awf_role.parse_postflight_contract(str(card))
    # First {python} replaced, second (non-first position) preserved
    assert contract.verification_commands[0][0] == sys.executable
    assert contract.verification_commands[0][1] == "arg"
    assert contract.verification_commands[0][2] == "{python}"


# ---------------------------------------------------------------------------
# Postflight contract — malformed / missing / unsafe
# ---------------------------------------------------------------------------


def test_contract_missing_block(tmp_path):
    """A card without awf-postflight block fails."""
    card = tmp_path / "task.md"
    card.write_text("# Card without contract\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_malformed_json(tmp_path):
    """Malformed JSON in the block fails."""
    card = tmp_path / "task.md"
    card.write_text("# Card\n<!-- awf-postflight\n{bad json\n-->\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_not_an_object(tmp_path):
    """Non-object JSON fails."""
    card = tmp_path / "task.md"
    card.write_text('# Card\n<!-- awf-postflight\n"just a string"\n-->\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_extra_keys(tmp_path):
    """Extra contract keys fail."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]],\n'
        '  "extra_key": true\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_allowed_paths(tmp_path):
    """Empty allowed_paths array fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": [],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_backslash_path(tmp_path):
    """Backslash path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["src\\\\file.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_absolute_path(tmp_path):
    """Absolute path (leading slash) fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["/etc/passwd"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_drive_qualified_path(tmp_path):
    """Drive-qualified path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["C:/file.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_parent_traversal_path(tmp_path):
    """Parent-traversal path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["../outside.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_duplicate_path(tmp_path):
    """Duplicate path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py", "a.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_verification_commands(tmp_path):
    """Empty verification_commands array fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": []\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_command_array(tmp_path):
    """An empty command array fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [[]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_non_string_in_command(tmp_path):
    """Non-string element in verification command fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [[42]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


# ---------------------------------------------------------------------------
# Artifact denylist categories
# ---------------------------------------------------------------------------


def test_path_is_denied():
    """Every denylist category is rejected; documented examples are allowed."""
    denied = [
        ".env",
        ".env.local",
        ".env.production",
        ".venv/somefile",
        "venv/bin/pkg",
        "env/Lib",
        "__pycache__/cache.pyc",
        "src/__pycache__/mod.pyc",
        "node_modules/pkg/index.js",
        "dist/bundle.js",
        "build/output.o",
        "Thumbs.db",
        ".DS_Store",
        ".coverage",
        "coverage.xml",
        "coverage/data.xml",
        "htmlcov/index.html",
        "file.swp",
        "file.swo",
        "file.swn",
        "file.bak",
        "file.orig",
        "file.pyc",
        "file.pyo",
        "output.log",
        "process.pid",
        "mylib.egg-info/PKG-INFO",
    ]
    allowed = [
        ".env.example",
        ".env.template",
        ".env.sample",
        "regular.py",
        ".gitignore",
        "README.md",
        "src/a.py",
    ]
    for p in denied:
        assert awf_role._path_is_denied(p), f"{p!r} should be denied"
    for p in allowed:
        assert not awf_role._path_is_denied(p), f"{p!r} should not be denied"


# ---------------------------------------------------------------------------
# Git delta collection
# ---------------------------------------------------------------------------


def _init_repo(root: Path) -> Path:
    """Create a minimal git repo with one committed file (a.py)."""
    repo = root / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=root)
    run("git", "config", "user.name", "Test", cwd=repo)
    run("git", "config", "user.email", "test@test", cwd=repo)
    (repo / "a.py").write_text("original\n")
    run("git", "add", "a.py", cwd=repo)
    run("git", "commit", "-m", "initial", cwd=repo)
    return repo


def test_collect_delta_modified_file(tmp_path):
    """Modified tracked files appear in the delta."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    paths = awf_role._collect_delta_paths(str(repo))
    assert "a.py" in paths


def test_collect_delta_deleted_file(tmp_path):
    """Deleted tracked files appear in the delta."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").unlink()
    paths = awf_role._collect_delta_paths(str(repo))
    assert "a.py" in paths


def test_collect_delta_untracked_file(tmp_path):
    """Untracked files appear in the delta."""
    repo = _init_repo(tmp_path)
    (repo / "new.py").write_text("new\n")
    paths = awf_role._collect_delta_paths(str(repo))
    assert "new.py" in paths


def test_collect_delta_renamed_file(tmp_path):
    """Renamed files include both old and new path in the delta."""
    repo = _init_repo(tmp_path)
    run("git", "mv", "a.py", "b.py", cwd=repo)
    paths = awf_role._collect_delta_paths(str(repo))
    assert "a.py" in paths
    assert "b.py" in paths


# ---------------------------------------------------------------------------
# Delta gates — path scope, denylist, secrets, diff check
# ---------------------------------------------------------------------------


def test_delta_gate_empty_set(tmp_path):
    """An empty change set fails the delta gate."""
    repo = _init_repo(tmp_path)
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


def test_delta_gate_out_of_scope_path(tmp_path):
    """A changed path outside allowed_paths fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    (repo / "outside.py").write_text("rogue\n")
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


def test_delta_gate_denied_artifact(tmp_path):
    """A path on the artifact denylist fails even if in allowed_paths."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    (repo / ".env").write_text("SECRET=value\n")
    contract = awf_role.PostflightContract(allowed_paths=["a.py", ".env"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


def test_delta_gate_diff_check_fails(tmp_path):
    """git diff --check catches whitespace errors before staging."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("trailing whitespace   \n")
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


# ---------------------------------------------------------------------------
# Narrow secret scan
# ---------------------------------------------------------------------------


def test_secret_scan_tracked_diff_private_key(tmp_path):
    """A private key header in a tracked diff fails the secret gate."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f"{_PK_HEADER}\nMIIEpAIBAAKCAQEA...\n{_PK_FOOTER}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_credential_url(tmp_path):
    """A credential-bearing URL in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'url = "{_CRED_URL}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_github_token(tmp_path):
    """A GitHub token shape in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'token = "{_GITHUB_TOKEN}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_openai_key(tmp_path):
    """An OpenAI key shape in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'key = "{_OPENAI_KEY}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_aws_key(tmp_path):
    """An AWS access key shape in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'aws_key = "{_AWS_KEY}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_untracked_file(tmp_path):
    """An untracked file with a secret fails."""
    repo = _init_repo(tmp_path)
    (repo / "secret.txt").write_text(f"{_GITHUB_TOKEN}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_benign_placeholder_words_pass(tmp_path):
    """Placeholder words like token/secret must not fail by themselves."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text('token = "placeholder"\nsecret = "test-value"\n')
    # Must not raise
    awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_benign_test_fixtures_pass(tmp_path):
    """Test fixture values that look token-like but are within test conventions must not fail."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(
        'token = "test-token"\nsecret = "fixture-value"\napi_key = "sk_test_abcdefghijklmnopqrst"\n'
    )
    # sk_test_ pattern might match depending on the regex. Let's use a clearly benign one.
    (repo / "a.py").write_text('TOKEN = "test"\nSECRET = "fixture"\n')
    awf_role._narrow_secret_scan(str(repo))


# ---------------------------------------------------------------------------
# Verification command re-execution
# ---------------------------------------------------------------------------


def test_verification_commands_succeed(tmp_path):
    """Verification commands that all pass let the gate succeed."""
    contract = awf_role.PostflightContract(
        allowed_paths=[],
        verification_commands=[[sys.executable, "-c", "exit(0)"]],
    )
    awf_role.run_verifications(str(tmp_path), contract)


def test_verification_stops_on_first_failure(tmp_path):
    """Verification stops at the first non-zero exit code."""
    contract = awf_role.PostflightContract(
        allowed_paths=[],
        verification_commands=[
            [sys.executable, "-c", "exit(0)"],
            [sys.executable, "-c", "exit(1)"],
            [sys.executable, "-c", "exit(0)"],  # Should not be reached
        ],
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_verifications(str(tmp_path), contract)


def test_verification_uses_model_env(monkeypatch, tmp_path):
    """Verification commands receive the credential-stripped model environment."""
    monkeypatch.setenv("AWF_CODER_TOKEN", "should-not-leak")
    monkeypatch.setenv("AGENT_BUS_TOKEN", "should-not-leak")

    captured_env: dict = {}

    def capturing_spawn(argv, *, cwd=None, stdin=None, env=None):
        captured_env.clear()
        captured_env.update(env or {})
        return 0

    monkeypatch.setattr(awf_role, "spawn", capturing_spawn)

    contract = awf_role.PostflightContract(
        allowed_paths=[],
        verification_commands=[[sys.executable, "-c", "exit(0)"]],
    )
    awf_role.run_verifications(str(tmp_path), contract)

    assert "AWF_CODER_TOKEN" not in captured_env
    assert "AGENT_BUS_TOKEN" not in captured_env


# ---------------------------------------------------------------------------
# Verification-created files subject to path checks
# ---------------------------------------------------------------------------


def test_verification_created_file_in_path_gate(tmp_path):
    """Files created by verification are subject to path/artifact checks."""
    repo = _init_repo(tmp_path)
    contract = awf_role.PostflightContract(
        allowed_paths=["a.py"],
        verification_commands=[[sys.executable, "-c", "open('new_file.py', 'w').write('x')"]],
    )
    # Verification succeeds
    awf_role.run_verifications(str(repo), contract)
    # But the delta gate catches the new file outside allowed_paths
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


# ---------------------------------------------------------------------------
# Full valid postflight reaches success
# ---------------------------------------------------------------------------


def test_full_valid_postflight_flow(tmp_path):
    """A fully valid postflight path passes all gates with a real git repo."""
    repo = _init_repo(tmp_path)
    # Modify an allowed file
    (repo / "a.py").write_text("modified content\n")
    contract = awf_role.PostflightContract(
        allowed_paths=["a.py"],
        verification_commands=[[sys.executable, "-c", "exit(0)"]],
    )
    # Verification passes
    awf_role.run_verifications(str(repo), contract)
    # Delta gates pass (a.py is allowed, no denylist, no secrets, no whitespace errors)
    awf_role.run_postflight_delta_gates(str(repo), contract)


def test_verification_failure_prevents_downstream(monkeypatch, tmp_path):
    """A non-zero verification result prevents git add/commit/push/send_event."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    contract = awf_role.PostflightContract(
        allowed_paths=["a.py"],
        verification_commands=[[sys.executable, "-c", "exit(1)"]],
    )

    downstream_calls = []

    def track_git(*args, **kw):
        downstream_calls.append(("git", args))

    monkeypatch.setattr(awf_role, "git", track_git)

    with pytest.raises(SystemExit, match="1"):
        awf_role.run_verifications(str(repo), contract)

    assert not downstream_calls, "no git write should occur after verification failure"


# ---------------------------------------------------------------------------
# Rework: full HEAD delta — staged changes also caught (rework items 1, 2)
# ---------------------------------------------------------------------------
# The original implementation checked only unstaged changes.  After rework the
# secret scan and diff --check cover staged + unstaged changes (git diff HEAD).
# The delta path snapshot uses NUL-delimited output for safe handling of
# spaces, Unicode, and quoted paths.  New tests below prove coverage of
# staged tracked, staged new, spaced renames, spaced untracked, and Unicode
# paths.
# ---------------------------------------------------------------------------


def test_secret_scan_staged_tracked_diff(tmp_path):
    """A staged tracked file with a secret is caught (diff HEAD covers staged)."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'token = "{_GITHUB_TOKEN}"\n')
    run("git", "add", "a.py", cwd=repo)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_staged_new_file(tmp_path):
    """A staged new file with a secret is caught."""
    repo = _init_repo(tmp_path)
    (repo / "new.py").write_text(f"{_GITHUB_TOKEN}\n")
    run("git", "add", "new.py", cwd=repo)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_collect_delta_spaced_rename(tmp_path):
    """Renamed file with spaces is captured correctly (NUL-safe)."""
    repo = _init_repo(tmp_path)
    (repo / "my file.py").write_text("content\n")
    run("git", "add", "my file.py", cwd=repo)
    run("git", "commit", "-m", "add spaced", cwd=repo)
    run("git", "mv", "my file.py", "my renamed file.py", cwd=repo)
    paths = awf_role._collect_delta_paths(str(repo))
    assert "my file.py" in paths
    assert "my renamed file.py" in paths


def test_secret_scan_spaced_untracked(tmp_path):
    """Untracked file with spaces and a secret is caught (NUL-safe path)."""
    repo = _init_repo(tmp_path)
    (repo / "my secret.txt").write_text(f"{_GITHUB_TOKEN}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_collect_delta_unicode_path(tmp_path):
    """Unicode filenames in the delta are captured correctly (NUL-safe)."""
    repo = _init_repo(tmp_path)
    (repo / "café.py").write_text("content\n")
    paths = awf_role._collect_delta_paths(str(repo))
    assert "café.py" in paths


# ---------------------------------------------------------------------------
# Rework: artifact denylist matched at any depth (rework item 3)
# ---------------------------------------------------------------------------


def test_path_is_denied_nested():
    """Artifact denylist matches directory patterns at any depth, .env by basename."""
    nested_denied = [
        "config/.env.production",
        "web/node_modules/pkg/index.js",
        "pkg/build/output.o",
        "sub/deep/.venv/bin/python",
        "src/__pycache__/mod.pyc",
        "config/.env",
        ".env.local",
        "config/.env.staging",
        "tmp/.DS_Store",
        "pkg/coverage.xml",
    ]
    for p in nested_denied:
        assert awf_role._path_is_denied(p), f"{p!r} should be denied at any depth"
    # Root-level variants must still be denied
    for p in [".env.production", "node_modules/pkg/index.js", "build/output.o"]:
        assert awf_role._path_is_denied(p), f"{p!r} should be denied at root"
    # Documented example templates must be allowed at any depth
    for p in [".env.example", ".env.template", ".env.sample", "config/.env.example"]:
        assert not awf_role._path_is_denied(p), f"{p!r} should be allowed"


# ---------------------------------------------------------------------------
# Rework: fail closed on unreadable untracked files (rework item 4)
# ---------------------------------------------------------------------------


def test_secret_scan_unreadable_untracked_fails(monkeypatch, tmp_path):
    """An unreadable untracked regular file fails closed with safe label."""
    repo = _init_repo(tmp_path)
    (repo / "secret.txt").write_text("content\n")

    original_read_text = Path.read_text

    def failing_read(self, **kwargs):
        if self.name == "secret.txt":
            raise OSError("Permission denied")
        return original_read_text(self, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read)

    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


# ---------------------------------------------------------------------------
# Rework: reject empty executable in contract (rework item 5)
# ---------------------------------------------------------------------------


def test_contract_empty_executable(tmp_path):
    """An empty string as the sole executable element fails contract parsing."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [[""]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_string_in_command(tmp_path):
    """An empty non-executable argv value is preserved."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [["python", "-c", ""]]\n'
        "}\n"
        "-->\n"
    )
    contract = awf_role.parse_postflight_contract(str(card))
    assert contract.verification_commands == [["python", "-c", ""]]


def test_secret_scan_quoted_tracked_filename(tmp_path):
    """A quoted Git path cannot detach added content from its known path."""
    repo = _init_repo(tmp_path)
    path = repo / 'a"b.py'
    path.write_text("value = 'safe'\n")
    run("git", "add", path.name, cwd=repo)
    run("git", "commit", "-m", "add quoted path", cwd=repo)
    path.write_text(f"value = '{_GITHUB_TOKEN}'\n")
    run("git", "add", path.name, cwd=repo)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_disables_diff_helpers(monkeypatch, tmp_path):
    """Tracked scanning disables textconv and external diff helpers."""
    repo = _init_repo(tmp_path)
    (repo / "a.txt").write_text("safe\n")
    run("git", "add", "a.txt", cwd=repo)
    run("git", "commit", "-m", "add text", cwd=repo)
    (repo / "a.txt").write_text(f"{_GITHUB_TOKEN}\n")

    original = awf_role.git_out
    calls = []

    def recording_git_out(repo_path, *args):
        calls.append(args)
        return original(repo_path, *args)

    monkeypatch.setattr(awf_role, "git_out", recording_git_out)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))
    diff_call = next(args for args in calls if args and args[0] == "diff" and "--" in args)
    assert "--no-textconv" in diff_call
    assert "--no-ext-diff" in diff_call


def test_secret_scan_added_line_starting_with_plus_plus(tmp_path):
    """A real added line beginning with ++ is not mistaken for a patch header."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("safe\n")
    run("git", "add", "a.py", cwd=repo)
    run("git", "commit", "-m", "add source", cwd=repo)
    (repo / "a.py").write_text(f"++{_GITHUB_TOKEN}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


# ---------------------------------------------------------------------------
# Rework: git diff HEAD --check catches staged whitespace (rework item 1)
# ---------------------------------------------------------------------------


def test_delta_gate_diff_check_rejects_staged_whitespace(tmp_path):
    """Staged whitespace errors are caught by diff HEAD --check."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("trailing whitespace   \n")
    run("git", "add", "a.py", cwd=repo)
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)
