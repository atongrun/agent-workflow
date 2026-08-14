"""CLI integration tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from agent_workflow import __version__, cli
from agent_workflow.manifest import derive_manifest, write_manifest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_awf(*args: str, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", "agent_workflow.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return completed


def test_plan_check_rejects_run_manifest_as_authority_before_compilation(
    monkeypatch, tmp_path: Path, capsys
):
    task_card = tmp_path / "card.md"
    task_card.write_text(
        "## Task ID\n\nTASK-001\n\n## Working Context\n\n- **Task branch**: `feature/TASK-001`\n",
        encoding="utf-8",
    )
    manifest_path = write_manifest(
        tmp_path / "run-manifest.json",
        derive_manifest(task_card, branch="feature/TASK-001", tool="codex"),
    )
    monkeypatch.setattr(
        cli,
        "compile_run_contract",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("compiler must not run")),
    )

    result = cli.cmd_plan_check(
        SimpleNamespace(
            repo=str(tmp_path),
            run_manifest=str(manifest_path),
            authority_manifest=str(manifest_path),
            state_root=str(tmp_path / "state"),
            run="",
            profile=[],
        )
    )

    assert result == 1
    error = capsys.readouterr().err
    assert "awf.authority-manifest.v1" in error
    assert "awf.run-manifest.v1" in error


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


def test_preflight_forwards_to_packaged_operation(monkeypatch):
    received = []
    operation = SimpleNamespace(main=lambda argv: received.append(argv) or 7)
    monkeypatch.setitem(sys.modules, "awf_preflight", operation)

    result = cli.main(["preflight", "resume-deep", "--probe-id", "probe-1"])

    assert result == 7
    assert received == [["resume-deep", "--probe-id", "probe-1"]]


def test_preflight_does_not_expose_internal_handler_commands(monkeypatch, capsys):
    operation = SimpleNamespace(main=lambda _argv: 0)
    monkeypatch.setitem(sys.modules, "awf_preflight", operation)

    result = cli.main(["preflight", "handle-result"])

    assert result == 2
    assert capsys.readouterr().err == "ERROR: awf preflight supports only resume-deep\n"


def test_feedback_status_forwards_to_packaged_operation(monkeypatch, tmp_path):
    received = []
    operation = SimpleNamespace(main=lambda argv: received.append(argv) or 0)
    monkeypatch.setitem(sys.modules, "awf_feedback", operation)

    result = cli.main(["feedback", "status", "--state-root", str(tmp_path), "--json"])

    assert result == 0
    assert received == [["status", "--state-root", str(tmp_path), "--json"]]


def test_feedback_flush_forwards_bounded_operator_options(monkeypatch, tmp_path):
    received = []
    operation = SimpleNamespace(main=lambda argv: received.append(argv) or 0)
    monkeypatch.setitem(sys.modules, "awf_feedback", operation)
    config = tmp_path / "dispatch.env"

    result = cli.main(
        [
            "feedback",
            "flush",
            "--state-root",
            str(tmp_path),
            "--config",
            str(config),
            "--limit",
            "3",
        ]
    )

    assert result == 0
    assert received == [
        [
            "flush",
            "--state-root",
            str(tmp_path),
            "--config",
            str(config),
            "--limit",
            "3",
        ]
    ]


def test_feedback_ingest_forwards_payload_as_one_argument(monkeypatch, tmp_path):
    received = []
    operation = SimpleNamespace(main=lambda argv: received.append(argv) or 0)
    monkeypatch.setitem(sys.modules, "awf_feedback", operation)
    payload = '{"format":"awf.finding-occurrence.v1"}'

    result = cli.main(
        [
            "feedback",
            "ingest",
            "--state-root",
            str(tmp_path),
            "--payload-json",
            payload,
        ]
    )

    assert result == 0
    assert received == [["ingest", "--state-root", str(tmp_path), "--payload-json", payload]]


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
        assert "WARN" not in result.stdout

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

    def test_validate_workflow_with_missing_role_and_transition_fails(self, tmp_path: Path):
        workflow = tmp_path / "invalid-workflow.yaml"
        workflow.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: invalid-workflow
  version: "0.1.0"
spec:
  description: test
  stages:
    - id: plan
      role: does-not-exist
      onSuccess: nowhere-stage
      onFailure: failed
  terminalStates: [completed, failed]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(workflow))

        assert result.returncode != 0
        assert "role 'does-not-exist' not found" in result.stdout
        assert "onSuccess target 'nowhere-stage'" in result.stdout

    def test_validate_workflow_with_duplicate_stage_id_fails(self, tmp_path: Path):
        workflow = tmp_path / "duplicate-stage.yaml"
        workflow.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: duplicate-stage
  version: "0.1.0"
spec:
  description: test
  stages:
    - id: plan
      role: planner
      onSuccess: completed
    - id: plan
      role: planner
      onSuccess: completed
  terminalStates: [completed]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(workflow))

        assert result.returncode != 0
        assert "duplicate stage id 'plan'" in result.stdout

    def test_validate_role_with_semantic_conflict_fails(self, tmp_path: Path):
        role = tmp_path / "conflicting-role.yaml"
        role.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: conflicting-role
  version: "0.1.0"
spec:
  description: test
  responsibilities: []
  capabilities: [modify-code]
  forbiddenActions: [modify-code]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(role))

        assert result.returncode != 0
        assert "appears in both capabilities and forbiddenActions" in result.stdout

    def test_validate_schema_invalid_role_fails_without_traceback(self, tmp_path: Path):
        role = tmp_path / "invalid-role.yaml"
        role.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata: invalid
spec:
  description: test
  responsibilities: []
  capabilities: []
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(role), cwd=tmp_path)

        assert result.returncode != 0
        assert "is not of type 'object'" in result.stdout
        assert "Traceback" not in result.stderr

    def test_validate_nonmapping_document_fails_without_traceback(self, tmp_path: Path):
        resource = tmp_path / "invalid-document.yaml"
        resource.write_text("[]\n", encoding="utf-8")

        result = run_awf("validate", str(resource), cwd=tmp_path)

        assert result.returncode != 0
        assert result.stdout == f"FAIL {resource}: resource document must be an object\n"
        assert "Traceback" not in result.stderr

    def test_validate_multidocument_resources_with_valid_handoff_passes(self, tmp_path: Path):
        resources = tmp_path / "resources.yaml"
        resources.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: local-role
  version: "0.1.0"
spec:
  description: test
  responsibilities: []
  capabilities: []
---
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: local-workflow
  version: "0.1.0"
spec:
  description: test
  stages:
    - id: local-stage
      role: local-role
      onSuccess: completed
  terminalStates: [completed]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(resources), cwd=tmp_path)

        assert result.returncode == 0
        assert "WARN" not in result.stdout
        assert result.stdout == f"PASS {resources}\n"

    def test_validate_multidocument_role_semantics_ignore_sibling_schema_error(
        self, tmp_path: Path
    ):
        resources = tmp_path / "resources.yaml"
        resources.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: conflicting-role
  version: "0.1.0"
spec:
  description: test
  responsibilities: []
  capabilities: [modify-code]
  forbiddenActions: [modify-code]
---
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: invalid-role
  version: "0.1.0"
spec:
  description: test
  responsibilities: []
---
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: local-workflow
  version: "0.1.0"
spec:
  description: test
  stages:
    - id: local-stage
      role: conflicting-role
      onSuccess: completed
  terminalStates: [completed]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(resources), cwd=tmp_path)

        assert result.returncode != 0
        assert "spec: 'capabilities' is a required property" in result.stdout
        assert "role 'conflicting-role': action 'modify-code'" in result.stdout
        assert "role 'conflicting-role' not found" not in result.stdout

    def test_validate_uses_roles_in_validation_target(self, tmp_path: Path):
        (tmp_path / "local-role.yaml").write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: local-role
  version: "0.1.0"
spec:
  description: test
  responsibilities: []
  capabilities: []
""",
            encoding="utf-8",
        )
        (tmp_path / "local-workflow.yaml").write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: local-workflow
  version: "0.1.0"
spec:
  description: test
  stages:
    - id: local-stage
      role: local-role
      onSuccess: completed
  terminalStates: [completed]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(tmp_path), cwd=tmp_path)

        assert result.returncode == 0
        assert "WARN" not in result.stdout
        assert "2/2 passed" in result.stdout

    def test_validate_without_role_sources_warns_but_checks_transitions(self, tmp_path: Path):
        workflow = tmp_path / "duplicate-stage.yaml"
        workflow.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: duplicate-stage
  version: "0.1.0"
spec:
  description: test
  stages:
    - id: plan
      role: does-not-exist
      onSuccess: completed
    - id: plan
      role: does-not-exist
      onSuccess: completed
  terminalStates: [completed]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(workflow), cwd=tmp_path)

        assert result.returncode != 0
        assert "WARN" in result.stdout
        assert "role existence checks skipped" in result.stdout
        assert "role 'does-not-exist' not found" not in result.stdout
        assert "duplicate stage id 'plan'" in result.stdout

    def test_validate_without_role_sources_warns_but_can_pass(self, tmp_path: Path):
        workflow = tmp_path / "valid-workflow.yaml"
        workflow.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: valid-workflow
  version: "0.1.0"
spec:
  description: test
  stages:
    - id: plan
      role: does-not-exist
      onSuccess: completed
  terminalStates: [completed]
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(workflow), cwd=tmp_path)

        assert result.returncode == 0
        assert "WARN" in result.stdout
        assert "role existence checks skipped" in result.stdout
        assert "role 'does-not-exist' not found" not in result.stdout
        assert f"PASS {workflow}" in result.stdout

    def test_validate_schema_error_uses_its_actual_path(self, tmp_path: Path):
        role = tmp_path / "missing-capabilities.yaml"
        role.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: valid-name
  version: "0.1.0"
spec:
  description: test
  responsibilities: []
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(role))

        assert result.returncode != 0
        assert result.stdout == f"FAIL {role}: spec: 'capabilities' is a required property\n"

    def test_validate_metadata_schema_error_does_not_use_spec_prefix(self, tmp_path: Path):
        role = tmp_path / "uppercase-name.yaml"
        role.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: Uppercase
  version: "0.1.0"
spec:
  description: test
  responsibilities: []
  capabilities: []
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(role))

        assert result.returncode != 0
        assert result.stdout == (
            f"FAIL {role}: metadata/name: 'Uppercase' does not match '^[a-z][a-z0-9-]*$'\n"
        )

    def test_validate_parse_error_prints_target_once(self, tmp_path: Path):
        malformed = tmp_path / "malformed.yaml"
        malformed.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata: [
""",
            encoding="utf-8",
        )

        result = run_awf("validate", str(malformed))

        assert result.returncode != 0
        assert "YAML parse error" in result.stdout
        assert result.stdout.count(str(malformed)) == 1

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

    def test_inspect_directory_fails_without_traceback(self):
        result = run_awf("inspect", "roles")

        assert result.returncode != 0
        assert "cannot inspect a directory" in result.stderr
        assert "Traceback" not in result.stderr

    def test_inspect_os_error_fails_without_traceback(self, tmp_path: Path, monkeypatch, capsys):
        resource = tmp_path / "resource.yaml"
        resource.write_text("apiVersion: agent-workflow/v1alpha1\n", encoding="utf-8")

        def raise_os_error(path: Path):
            raise OSError("simulated read failure")

        monkeypatch.setattr(cli, "parse_all_resources", raise_os_error)

        exit_code = cli.cmd_inspect(Namespace(target=str(resource)))
        captured = capsys.readouterr()

        assert exit_code == 1
        assert captured.out == ""
        assert captured.err == "ERROR: simulated read failure\n"
        assert "Traceback" not in captured.err


def test_run_uses_owner_manifest_values_and_listener_run_id(monkeypatch, tmp_path: Path, capsys):
    card = tmp_path / "card.md"
    card.write_text(
        "## Task ID\n\nDOGFOOD-001\n\n- **Task branch**: `card-branch`\n",
        encoding="utf-8",
    )
    values = derive_manifest(card, branch="owner-branch", tool="codex", rework_budget=4)
    manifest = write_manifest(tmp_path / ".awf" / "run-manifest.json", values)
    captured = {}

    class FakeLedger:
        def __init__(self, _state_root, run_id):
            captured["run_id"] = run_id

        def initialize(self, packet, **kwargs):
            captured["packet"] = packet
            captured["kwargs"] = kwargs

    class FakeOps:
        ControlPlaneDenied = RuntimeError
        RunLedger = FakeLedger

        @staticmethod
        def load_authority_manifest(_path):
            return {"allowed_operations": ["diagnose"]}

        @staticmethod
        def authority_manifest_binding(_manifest):
            return {"sha256": "sha256:" + "a" * 64, "allowed_operations": ["diagnose"]}

        @staticmethod
        def build_context_packet(**kwargs):
            return kwargs

    monkeypatch.setattr(cli, "_ops_module", lambda: FakeOps)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", ""),
    )
    args = Namespace(
        repo=str(tmp_path),
        card="card.md",
        manifest=str(manifest),
        branch="",
        tool="",
        model="",
        run="",
        state_root=str(tmp_path / "state"),
        rework_budget=1,
    )

    assert cli.cmd_run(args) == 0
    assert captured["run_id"] == "task-owner-branch"
    assert captured["packet"]["branch"] == "owner-branch"
    assert captured["kwargs"]["rework_budget"] == 4
    assert "run=task-owner-branch" in capsys.readouterr().out


def test_authority_manifest_prefers_downstream_override_then_packaged_default(
    monkeypatch, tmp_path: Path
):
    packaged = tmp_path / "package" / "authority.json"
    monkeypatch.setattr(cli, "authority_manifest_path", lambda: packaged)

    assert cli._authority_manifest_for_repo(tmp_path) == packaged

    downstream = tmp_path / "scripts" / "authority-manifest.example.json"
    downstream.parent.mkdir()
    downstream.write_text("{}\n", encoding="utf-8")
    assert cli._authority_manifest_for_repo(tmp_path) == downstream


def test_status_labels_unrecorded_health_and_queue(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "_load_run",
        lambda _args: (
            object,
            (
                {"terminal_state": "", "attempts": 0, "decisions": []},
                {
                    "stage": "implement",
                    "phase": "",
                    "transition": "",
                    "next_action": "clean_checkout",
                },
            ),
        ),
    )
    result = cli.cmd_status(Namespace(run="task-DOGFOOD-001", state_root="/tmp/state"))
    output = capsys.readouterr().out

    assert result == 0
    assert "checkpoint=not_recorded" in output
    assert "health: listener=not_recorded bus=not_recorded postflight=not_recorded" in output
    assert "queue: pending=not_recorded attempts=0" in output
