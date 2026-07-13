"""Regression tests for the cross-machine role handler."""

from __future__ import annotations

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
