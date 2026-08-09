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
from agent_workflow.resources import operations_dir

sys.path.insert(0, str(operations_dir()))
import awf_listen

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
from agent_workflow import cli, node, status
from agent_workflow.resources import operations_dir, schemas_dir, templates_dir

operations = operations_dir()
schemas = schemas_dir()
templates = templates_dir()
required = [
    operations / "awf_listen.py",
    operations / "awf_role.py",
    operations / "awf_dispatch.py",
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
sys.path.insert(0, str(operations))
import awf_control_plane
import awf_dispatch
import awf_listen
import awf_role
assert Path(awf_listen.__file__).resolve().is_relative_to(operations)
assert Path(awf_role.__file__).resolve().is_relative_to(operations)
assert awf_control_plane.DEFAULT_ROUTES
assert callable(awf_dispatch.main)
assert status.STATUS_FORMAT == "awf.node-status.v1"
assert node.READINESS_FORMAT == "awf.node-readiness.v1"
assert Path(cli._ops_module().__file__).resolve().is_relative_to(operations)
assert cli._authority_manifest_for_repo(Path.cwd()) == (
    operations / "authority-manifest.example.json"
)
"""
        subprocess.run([str(python), "-c", proof], check=True, cwd=outside, env=clean_env)
        verify_listener_pid_binding(python, root, clean_env)
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
