#!/usr/bin/env python3
"""Install one built wheel and prove operations work outside the source checkout."""

from __future__ import annotations

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
from agent_workflow import cli
from agent_workflow.resources import operations_dir, templates_dir

operations = operations_dir()
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
assert Path(cli._ops_module().__file__).resolve().is_relative_to(operations)
assert cli._authority_manifest_for_repo(Path.cwd()) == (
    operations / "authority-manifest.example.json"
)
"""
        subprocess.run([str(python), "-c", proof], check=True, cwd=outside, env=clean_env)
        subprocess.run(
            [str(awf), "version"],
            check=True,
            cwd=outside,
            env=clean_env,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
