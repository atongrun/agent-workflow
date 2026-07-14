"""Regression tests for the cross-machine role handler."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "awf_role.py"
SPEC = importlib.util.spec_from_file_location("awf_role", MODULE_PATH)
assert SPEC and SPEC.loader
awf_role = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(awf_role)


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
    """The OpenCode executor adapter passes model_env() to spawn()."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["env"] = kwargs.get("env")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")

    awf_role.tool_opencode_exec(str(tmp_path), "card.md", str(prompt_file), "")

    assert "AGENT_BUS_TOKEN" not in captured["env"]


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
    """The OpenCode reviewer adapter passes model_env() to spawn()."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["env"] = kwargs.get("env")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")

    awf_role.tool_opencode_review(str(tmp_path), "main", str(prompt_file), "", "")

    assert "AGENT_BUS_TOKEN" not in captured["env"]


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
    card.write_text("card")

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
    card.write_text("card")
    report = tmp_path / "report.md"
    report.write_text("report content")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_NO_PUSH", "1")
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "tool_opencode_exec", lambda *a, **kw: 0)
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
    card.write_text("card")
    report = tmp_path / "report.md"
    report.write_text("report content")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_NO_PUSH", "1")
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "tool_opencode_exec", lambda *a, **kw: 0)
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
