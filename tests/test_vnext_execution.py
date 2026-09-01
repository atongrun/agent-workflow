import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_workflow.vnext.contracts import RoleBinding, TaskProposal, TaskSpec
from agent_workflow.vnext.coordinator import CoordinatorError, GitHubEffects
from agent_workflow.vnext.executor import JobSpec, ReceiptStatus, SSHExecutor
from agent_workflow.vnext.host import HostConfig, HostError, HostRunner


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def job(base_sha: str, verification: tuple[str, ...]) -> JobSpec:
    roles = (
        RoleBinding("architect", "pi", "local"),
        RoleBinding("coder", "opencode", "windows-coder"),
        RoleBinding("reviewer", "codex", "local"),
    )
    proposal = TaskProposal(
        "Add the exact VNext marker",
        ("result.txt",),
        ("result.txt contains vnext",),
        (verification,),
    )
    task = TaskSpec(
        "run-1-task-01",
        1,
        "owner/repo",
        "main",
        base_sha,
        "awf/run-1-task-01",
        proposal,
        roles,
    )
    return JobSpec("job-1", "operation-1", task)


def repository(tmp_path: Path) -> tuple[Path, Path, str]:
    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "AWF Test")
    git(source, "config", "user.email", "awf@example.invalid")
    (source / "README.md").write_text("base\n", encoding="utf-8")
    git(source, "add", "README.md")
    git(source, "commit", "-m", "base")
    git(tmp_path, "init", "--bare", str(remote))
    git(source, "remote", "add", "origin", str(remote))
    git(source, "push", "origin", "main")
    return source, remote, git(source, "rev-parse", "HEAD")


def fake_provider(tmp_path: Path) -> Path:
    script = tmp_path / "fake-opencode"
    script.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys
workspace = pathlib.Path(sys.argv[sys.argv.index('--dir') + 1])
(workspace / 'result.txt').write_text('vnext\\n', encoding='utf-8')
print(json.dumps({'status': 'completed', 'summary': 'implemented', 'diagnostics': ''}))
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_host_runner_validates_commits_and_publishes_exact_frozen_ref(tmp_path: Path) -> None:
    source, remote, base = repository(tmp_path)
    provider = fake_provider(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    runner = HostRunner(HostConfig(str(source), str(remote), str(state), str(provider)))
    spec = job(
        base,
        (
            sys.executable,
            "-c",
            "from pathlib import Path; assert Path('result.txt').read_text() == 'vnext\\n'",
        ),
    )
    receipt = runner.execute(spec)
    assert receipt.status == ReceiptStatus.TERMINAL
    assert receipt.diagnostics == ""
    assert receipt.result == {
        "status": "completed",
        "summary": "implemented",
        "diagnostics": "",
    }
    assert receipt.provenance is not None
    commit = receipt.provenance["commit_sha"]
    assert (
        git(source, "ls-remote", str(remote), "refs/heads/awf/run-1-task-01").split()[0] == commit
    )
    assert runner.inspect("job-1") == receipt
    assert runner.execute(spec) == receipt


def test_host_runner_denies_stable_job_id_request_hash_conflict(tmp_path: Path) -> None:
    source, remote, base = repository(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    runner = HostRunner(
        HostConfig(str(source), str(remote), str(state), str(fake_provider(tmp_path)))
    )
    first = job(base, (sys.executable, "-c", "assert True"))
    assert runner.execute(first).status == ReceiptStatus.TERMINAL
    conflicting = JobSpec(first.job_id, "different-operation", first.task)
    with pytest.raises(HostError, match="conflicting request hash"):
        runner.execute(conflicting)


def test_ssh_executor_uses_fixed_command_stdin_and_shell_false(monkeypatch) -> None:
    observed = {}

    def fake_run(argv, **kwargs):
        observed.update(argv=argv, **kwargs)
        receipt = {
            "job_id": "job-1",
            "request_sha256": "a" * 64,
            "status": "NOT_FOUND",
            "result": None,
            "provenance": None,
            "diagnostics": "",
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(receipt).encode(), b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    receipt = SSHExecutor("windows-coder").inspect("job-1")
    assert receipt.status == ReceiptStatus.NOT_FOUND
    assert observed["argv"] == ["ssh", "windows-coder", "awf-agent", "inspect"]
    assert observed["shell"] is False
    assert json.loads(observed["input"]) == {"job_id": "job-1"}
    assert "job-1" not in observed["argv"]


def test_model_environment_strips_secret_named_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AWF_TEST_TOKEN", "do-not-pass")
    source, remote, base = repository(tmp_path)
    provider = fake_provider(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    runner = HostRunner(HostConfig(str(source), str(remote), str(state), str(provider)))
    receipt = runner.execute(job(base, (sys.executable, "-c", "assert True")))
    assert receipt.status == ReceiptStatus.TERMINAL
    assert "do-not-pass" not in receipt.diagnostics


def test_github_effects_reuse_only_exact_single_pr(monkeypatch, tmp_path: Path) -> None:
    effects = GitHubEffects(tmp_path, "owner/repo")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        value = [{"number": 42, "headRefOid": "a" * 40}]
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert (
        effects.ensure_pr(
            task_ref="awf/run-1-task-01",
            base_ref="main",
            head_sha="a" * 40,
            title="task",
        )
        == 42
    )
    assert calls[0][0:3] == ["gh", "pr", "list"]
    assert calls[0][calls[0].index("--head") + 1] == "awf/run-1-task-01"


def test_github_effects_deny_duplicate_pr(monkeypatch, tmp_path: Path) -> None:
    effects = GitHubEffects(tmp_path, "owner/repo")

    def duplicate(argv, **kwargs):
        value = [
            {"number": 1, "headRefOid": "a" * 40},
            {"number": 2, "headRefOid": "a" * 40},
        ]
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(subprocess, "run", duplicate)
    with pytest.raises(CoordinatorError, match="multiple PRs"):
        effects.ensure_pr(
            task_ref="awf/run-1-task-01",
            base_ref="main",
            head_sha="a" * 40,
            title="task",
        )
