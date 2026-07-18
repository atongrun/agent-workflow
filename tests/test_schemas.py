"""Schema validation tests for all resource files."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_workflow.validation import validate_directory, validate_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ROLES_DIR = PROJECT_ROOT / "roles"
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
EXAMPLES_DIR = PROJECT_ROOT / "examples"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"


def collect_yaml_files(directory: Path) -> list[Path]:
    """Collect all YAML files in a directory (non-recursive)."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))


class TestSchemaValidation:
    """All role/workflow files must pass JSON Schema validation."""

    @pytest.mark.parametrize("role_file", collect_yaml_files(ROLES_DIR))
    def test_role_passes_schema(self, role_file: Path):
        errors = validate_file(role_file)
        assert not errors, f"Schema validation failed for {role_file.name}: {errors}"

    @pytest.mark.parametrize("wf_file", collect_yaml_files(WORKFLOWS_DIR))
    def test_workflow_passes_schema(self, wf_file: Path):
        errors = validate_file(wf_file)
        assert not errors, f"Schema validation failed for {wf_file.name}: {errors}"


class TestExampleValidation:
    """All example files must pass schema validation."""

    def test_examples_directory_passes_validation(self):
        results = validate_directory(EXAMPLES_DIR)
        failing = {path: errs for path, errs in results.items() if errs}
        assert not failing, f"Example validation failures: {failing}"


class TestSchemaFilesExist:
    """All required schemas must exist."""

    REQUIRED_SCHEMAS = [
        "role.schema.json",
        "workflow.schema.json",
        "artifact.schema.json",
    ]

    @pytest.mark.parametrize("schema_file", REQUIRED_SCHEMAS)
    def test_schema_exists(self, schema_file: str):
        path = SCHEMAS_DIR / schema_file
        assert path.exists(), f"Schema missing: {schema_file}"


class TestMissingNameValidation:
    """Resource without metadata.name must fail validation."""

    def test_missing_name_fails(self, tmp_path: Path):
        file_path = tmp_path / "bad-role.yaml"
        file_path.write_text("""
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  version: "0.1.0"
spec:
  description: test
  responsibilities: [test]
  capabilities: [test]
""")
        errors = validate_file(file_path)
        assert errors
        assert any("required" in e.lower() or "name" in e.lower() for e in errors)

    def test_invalid_kind_fails(self, tmp_path: Path):
        file_path = tmp_path / "bad-kind.yaml"
        file_path.write_text("""
apiVersion: agent-workflow/v1alpha1
kind: UnknownKind
metadata:
  name: test
  version: "0.1.0"
spec: {}
""")
        errors = validate_file(file_path)
        assert errors
        assert any("unknown kind" in e.lower() for e in errors)


class TestPlanningArtifactTypes:
    """Method-level planning artifacts are recognized without opening their content schema."""

    @pytest.mark.parametrize("artifact_type", ["ArchitectureRecord", "PhasePlan"])
    def test_planning_artifact_type_passes(self, tmp_path: Path, artifact_type: str):
        file_path = tmp_path / f"{artifact_type}.yaml"
        file_path.write_text(
            f"""
apiVersion: agent-workflow/v1alpha1
kind: Artifact
metadata:
  name: planning-artifact
  version: "0.1.0"
spec:
  artifactId: artifact-1
  artifactType: {artifact_type}
  schemaVersion: "0.1.0"
  workflowRunId: run-1
  createdAt: "2026-07-18T00:00:00Z"
  createdBy:
    role: planner
    runner: manual
  content: {{}}
"""
        )

        assert not validate_file(file_path)

    def test_unknown_artifact_type_fails(self, tmp_path: Path):
        file_path = tmp_path / "unknown-artifact.yaml"
        file_path.write_text(
            """
apiVersion: agent-workflow/v1alpha1
kind: Artifact
metadata:
  name: unknown-artifact
  version: "0.1.0"
spec:
  artifactId: artifact-1
  artifactType: ArbitraryGraphState
  schemaVersion: "0.1.0"
  workflowRunId: run-1
  createdAt: "2026-07-18T00:00:00Z"
  createdBy:
    role: planner
    runner: manual
  content: {}
"""
        )

        errors = validate_file(file_path)
        assert errors
        assert any("artifactType" in error or "enum" in error for error in errors)
