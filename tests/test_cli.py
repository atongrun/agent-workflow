"""CLI integration tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

from agent_workflow import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_awf(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", "agent_workflow.cli", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        env=env,
    )
    completed.stdout = completed.stdout.decode("utf-8")
    completed.stderr = completed.stderr.decode("utf-8")
    return completed


class TestCLIVersion:
    def test_version_prints_version(self):
        result = run_awf("version")
        assert result.returncode == 0
        assert result.stdout == f"awf {__version__}\n"

    def test_version_exit_code_zero(self):
        result = run_awf("version")
        assert result.returncode == 0

    def test_runtime_version_matches_project_metadata(self):
        project_metadata = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert __version__ == project_metadata["project"]["version"]


class TestCLIValidate:
    def test_validate_role_passes(self):
        result = run_awf("validate", "roles/planner.yaml")
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_validate_all_roles_passes(self):
        result = run_awf("validate", "roles")
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_validate_workflows_passes(self):
        result = run_awf("validate", "workflows")
        assert result.returncode == 0

    def test_validate_examples_passes(self):
        result = run_awf("validate", "examples")
        assert result.returncode == 0

    def test_validate_invalid_file_fails(self, tmp_path: Path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("""
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  version: "0.1.0"
spec:
  description: test
""")
        result = run_awf("validate", str(bad_file))
        assert result.returncode != 0
        assert "FAIL" in result.stdout

    def test_validate_missing_file_fails(self):
        result = run_awf("validate", "nonexistent.yaml")
        assert result.returncode != 0


class TestCLIInspect:
    def test_inspect_workflow_shows_stages(self):
        result = run_awf("inspect", "workflows/feature-delivery.yaml")
        assert result.returncode == 0
        assert "name: feature-delivery" in result.stdout
        assert "kind: Workflow" in result.stdout
        assert "plan" in result.stdout
        assert "implement" in result.stdout

    def test_inspect_role_shows_capabilities(self):
        result = run_awf("inspect", "roles/planner.yaml")
        assert result.returncode == 0
        assert "kind: Role" in result.stdout
        assert "capabilities" in result.stdout
