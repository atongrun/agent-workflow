#!/usr/bin/env python3
"""Install one built wheel and prove operations work outside the source checkout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_awf(root: Path) -> Path:
    return root / ("Scripts/awf.exe" if os.name == "nt" else "bin/awf")


def verify_listener_pid_binding(
    python: Path,
    root: Path,
    clean_env: dict[str, str],
) -> None:
    state_root = root / "listener-state"
    repo = root / "listener-repo"
    repo.mkdir()
    child = """
import json
import sys
from pathlib import Path
from agent_workflow.operations import awf_listen

state_root = Path(sys.argv[1])
repo = Path(sys.argv[2])
launch_id = sys.argv[3]
lease_path = awf_listen.acquire_listener_lease(
    state_root, "coder", repo, launch_id=launch_id
)
print(json.dumps({
    "lease": json.loads(lease_path.read_text(encoding="utf-8")),
    "parent_pid": __import__("os").getppid(),
}), flush=True)
try:
    sys.stdin.read()
finally:
    awf_listen.release_listener_lease(
        lease_path, "coder", repo, launch_id=launch_id
    )
"""
    launch_id = "a" * 32
    process = subprocess.Popen(
        [str(python), "-c", child, str(state_root), str(repo), launch_id],
        cwd=root,
        env=clean_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        observation = json.loads(process.stdout.readline())
        lease = observation["lease"]
        assert lease["launch_id"] == launch_id
        if os.name == "nt":
            assert lease["pid"] != process.pid
            assert observation["parent_pid"] == process.pid
        else:
            assert lease["pid"] == process.pid
    finally:
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 0


def verify_plan_check(awf: Path, root: Path, clean_env: dict[str, str]) -> None:
    repo = root / "compiled-run-repo"
    repo.mkdir()
    state_root = root / "compiled-run-state"
    task_id = "WHEEL-CHECK-001"
    implementation = f".awf/artifacts/impl-report-{task_id}.md"
    review = f".awf/artifacts/review-report-{task_id}.md"
    card = repo / "task.md"
    card.write_text(
        f"## Task ID\n\n{task_id}\n\n"
        "<!-- awf-postflight\n"
        + json.dumps(
            {
                "allowed_paths": ["result.txt", implementation, review],
                "verification_commands": [["{python}", "-c", "print('wheel-check')"]],
            }
        )
        + "\n-->\n",
        encoding="utf-8",
    )
    manifest = repo / "run-manifest.json"
    profile_paths = []
    for role, tool, model, route in (
        ("coder", "opencode", "coder/model", "task:awf-impl-v3"),
        ("reviewer", "pi", "reviewer/model", "task:awf-review-v3"),
    ):
        profile = repo / f"{role}.json"
        profile.write_text(
            json.dumps(
                {
                    "format": "awf.node-profile.v1",
                    "name": f"wheel-{role}",
                    "role": role,
                    "repo": str(repo),
                    "tool": tool,
                    "model": model,
                    "on_type": route,
                    "state_root": str(state_root),
                    "upstream_repo": "owner/repo",
                    "head_repo": "owner/fork",
                }
            ),
            encoding="utf-8",
        )
        profile_paths.append(profile)
    subprocess.run(
        [
            str(awf),
            "setup",
            "--repo",
            str(repo),
            "--card",
            "task.md",
            "--run-manifest",
            str(manifest),
            "--branch",
            f"feature/{task_id}",
            "--tool",
            "opencode",
            "--model",
            "coder/model",
            "--reviewer-tool",
            "pi",
            "--reviewer-model",
            "reviewer/model",
            "--upstream-repo",
            "owner/repo",
            "--head-repo",
            "owner/fork",
            "--state-root",
            str(state_root),
            "--profile",
            f"coder={profile_paths[0]}",
            "--profile",
            f"reviewer={profile_paths[1]}",
        ],
        check=True,
        cwd=root / "outside-source",
        env=clean_env,
    )
    result = subprocess.run(
        [
            str(awf),
            "plan",
            "check",
            "--repo",
            str(repo),
            "--run-manifest",
            str(manifest),
        ],
        cwd=root / "outside-source",
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["format"] == "awf.run-contract-report.v1"
    assert report["compatibility"]["status"] == "compatible"
    subprocess.run(["git", "init"], check=True, cwd=repo, env=clean_env, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "installed-wheel@example.invalid"],
        check=True,
        cwd=repo,
        env=clean_env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Installed Wheel Check"],
        check=True,
        cwd=repo,
        env=clean_env,
    )
    subprocess.run(["git", "add", "."], check=True, cwd=repo, env=clean_env)
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        check=True,
        cwd=repo,
        env=clean_env,
        capture_output=True,
    )
    run = subprocess.run(
        [
            str(awf),
            "run",
            "--repo",
            str(repo),
            "--card",
            "task.md",
            "--run-manifest",
            str(manifest),
        ],
        cwd=root / "outside-source",
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert f"run=task-{task_id}" in run.stdout


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_installed_wheel.py <wheel>")
    candidate = Path(sys.argv[1]).resolve()
    wheels = sorted(candidate.glob("*.whl")) if candidate.is_dir() else [candidate]
    if len(wheels) != 1 or not wheels[0].is_file():
        raise SystemExit("expected exactly one built wheel")
    wheel = wheels[0]
    with tempfile.TemporaryDirectory(prefix="awf-installed-wheel-") as temp:
        root = Path(temp)
        environment = root / "venv"
        outside = root / "outside-source"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        python = venv_python(environment)
        awf = venv_awf(environment)
        clean_env = dict(os.environ)
        clean_env.pop("PYTHONPATH", None)
        subprocess.run(
            [str(python), "-m", "pip", "install", str(wheel)],
            check=True,
            cwd=outside,
            env=clean_env,
        )
        proof = """
import os
import sys
from pathlib import Path
from agent_workflow import cli, node, plan_loop, runtime, status
from agent_workflow.resources import operations_dir, schemas_dir, templates_dir

operations = operations_dir()
schemas = schemas_dir()
templates = templates_dir()
required = [
    operations / "awf_feedback.py",
    operations / "awf_listen.py",
    operations / "awf_role.py",
    operations / "awf_dispatch.py",
    operations / "awf_plan.py",
    operations / "authority-manifest.example.json",
    operations / "agent_adapters" / "pi.py",
    operations / "model-bin" / "model_git_guard.py",
    operations / "model-git-hooks" / "pre-commit",
    operations / "service" / "agent-workflow-listener.service.template",
    schemas / "node-profile.schema.json",
    templates / "artifacts" / "review-report.md",
]
assert all(path.is_file() for path in required), required
if os.name != "nt":
    executable_assets = [
        operations / "model-bin" / "git",
        operations / "model-git-hooks" / "pre-commit",
        operations / "model-git-hooks" / "pre-push",
        operations / "service" / "awf-listen-service.sh",
    ]
    assert all(os.access(path, os.X_OK) for path in executable_assets), executable_assets
from agent_workflow.operations import (
    awf_control_plane,
    awf_dispatch,
    awf_feedback,
    awf_listen,
    awf_plan,
    awf_role,
)
assert Path(awf_listen.__file__).resolve().is_relative_to(operations)
assert Path(awf_role.__file__).resolve().is_relative_to(operations)
assert awf_control_plane.DEFAULT_ROUTES
assert callable(awf_dispatch.main)
assert callable(awf_plan.start_plan)
assert awf_feedback.EVENT_TYPE == "feedback:awf-finding-v1"
assert status.STATUS_FORMAT == "awf.node-status.v1"
assert node.READINESS_FORMAT == "awf.node-readiness.v2"
assert runtime.RUN_SPEC_FORMAT == "awf.runtime-v2.run-spec.v1"
assert plan_loop.PLAN_RUN_FORMAT == "awf.plan-run.v1"
assert Path(runtime.__file__).resolve().parent.name == "runtime"
assert Path(cli._ops_module().__file__).resolve().is_relative_to(operations)
assert cli._authority_manifest_for_repo(Path.cwd()) == (
    operations / "authority-manifest.example.json"
)
"""
        subprocess.run([str(python), "-c", proof], check=True, cwd=outside, env=clean_env)
        verify_listener_pid_binding(python, root, clean_env)
        verify_plan_check(awf, root, clean_env)
        subprocess.run(
            [str(awf), "version"],
            check=True,
            cwd=outside,
            env=clean_env,
        )
        doctor_help = subprocess.run(
            [str(awf), "node", "doctor", "--help"],
            check=True,
            cwd=outside,
            env=clean_env,
            capture_output=True,
            text=True,
        )
        assert "--json" in doctor_help.stdout
        assert "--ttl-seconds" in doctor_help.stdout
        resume_help = subprocess.run(
            [str(awf), "preflight", "resume-deep", "--help"],
            check=True,
            cwd=outside,
            env=clean_env,
            capture_output=True,
            text=True,
        )
        assert "--probe-id" in resume_help.stdout
        feedback_help = subprocess.run(
            [str(awf), "feedback", "--help"],
            check=True,
            cwd=outside,
            env=clean_env,
            capture_output=True,
            text=True,
        )
        assert "status" in feedback_help.stdout
        assert "flush" in feedback_help.stdout
        assert "ingest" in feedback_help.stdout
        init_help = subprocess.run(
            [str(awf), "init", "--help"],
            check=True,
            cwd=outside,
            env=clean_env,
            capture_output=True,
            text=True,
        )
        assert "--roles" in init_help.stdout
        assert "--architect-runtime" in init_help.stdout
        assert "--finding-enabled" in init_help.stdout
        plan_start_help = subprocess.run(
            [str(awf), "plan", "start", "--help"],
            check=True,
            cwd=outside,
            env=clean_env,
            capture_output=True,
            text=True,
        )
        assert "--one-card" in plan_start_help.stdout
        assert "--milestone" in plan_start_help.stdout
        root_help = subprocess.run(
            [str(awf), "--help"],
            check=True,
            cwd=outside,
            env=clean_env,
            capture_output=True,
            text=True,
        )
        assert "logs" in root_help.stdout
        missing_profile = subprocess.run(
            [str(awf), "node", "status", "--profile", "missing-profile"],
            cwd=outside,
            env=clean_env,
            capture_output=True,
            text=True,
        )
        assert missing_profile.returncode == 1
        assert "profile is unavailable or invalid" in missing_profile.stderr
        assert "Traceback" not in missing_profile.stderr
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
