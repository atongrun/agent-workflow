"""Semantic validation tests for cross-resource consistency."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_workflow.validation import (
    load_role_map,
    validate_role_semantics,
    validate_workflow_semantics,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = PROJECT_ROOT / "roles"
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"


def _load_yaml_file(path: Path) -> dict:
    import yaml

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestWorkflowSemanticValidation:
    """Cross-resource semantic validation."""

    @pytest.fixture
    def role_map(self):
        return load_role_map(ROLES_DIR)

    def test_feature_delivery_stages_have_valid_roles(self, role_map):
        wf = _load_yaml_file(WORKFLOWS_DIR / "feature-delivery.yaml")
        errors = validate_workflow_semantics(wf, role_map)
        assert not errors, f"Semantic errors: {errors}"

    def test_all_workflows_have_valid_roles(self, role_map):
        for wf_file in sorted(WORKFLOWS_DIR.glob("*.yaml")):
            wf = _load_yaml_file(wf_file)
            errors = validate_workflow_semantics(wf, role_map)
            assert not errors, f"{wf_file.name} semantic errors: {errors}"

    def test_workflow_with_invalid_role_fails(self, role_map):
        wf = {
            "apiVersion": "agent-workflow/v1alpha1",
            "kind": "Workflow",
            "metadata": {"name": "test", "version": "0.1.0"},
            "spec": {
                "description": "test",
                "stages": [{"id": "s1", "role": "nonexistent-role", "onSuccess": "completed"}],
                "terminalStates": ["completed"],
            },
        }
        errors = validate_workflow_semantics(wf, role_map)
        assert errors
        assert any("not found" in e for e in errors)

    def test_duplicate_stage_id_fails(self, role_map):
        wf = {
            "apiVersion": "agent-workflow/v1alpha1",
            "kind": "Workflow",
            "metadata": {"name": "test", "version": "0.1.0"},
            "spec": {
                "description": "test",
                "stages": [
                    {"id": "plan", "role": "planner", "onSuccess": "completed"},
                    {"id": "plan", "role": "implementer", "onSuccess": "completed"},
                ],
                "terminalStates": ["completed"],
            },
        }
        errors = validate_workflow_semantics(wf, role_map)
        assert errors
        assert any("duplicate" in e for e in errors)

    def test_invalid_on_success_target_fails(self, role_map):
        wf = {
            "apiVersion": "agent-workflow/v1alpha1",
            "kind": "Workflow",
            "metadata": {"name": "test", "version": "0.1.0"},
            "spec": {
                "description": "test",
                "stages": [{"id": "plan", "role": "planner", "onSuccess": "nonexistent"}],
                "terminalStates": ["completed"],
            },
        }
        errors = validate_workflow_semantics(wf, role_map)
        assert errors
        assert any("onSuccess" in e for e in errors)


class TestRoleSemanticValidation:
    """Role-level semantic checks."""

    def test_all_roles_pass_semantic_validation(self):
        for role_file in sorted(ROLES_DIR.glob("*.yaml")):
            role = _load_yaml_file(role_file)
            errors = validate_role_semantics(role)
            assert not errors, f"{role_file.name} semantic errors: {errors}"

    def test_capability_forbidden_conflict_fails(self):
        role = {
            "apiVersion": "agent-workflow/v1alpha1",
            "kind": "Role",
            "metadata": {"name": "test", "version": "0.1.0"},
            "spec": {
                "description": "test",
                "responsibilities": ["test"],
                "capabilities": ["modify code", "run tests"],
                "forbiddenActions": ["modify code"],
            },
        }
        errors = validate_role_semantics(role)
        assert errors
        assert any("conflict" in e.lower() or "both" in e.lower() for e in errors)

    def test_no_conflict_when_disjoint(self):
        role = {
            "apiVersion": "agent-workflow/v1alpha1",
            "kind": "Role",
            "metadata": {"name": "test", "version": "0.1.0"},
            "spec": {
                "description": "test",
                "responsibilities": ["test"],
                "capabilities": ["run tests"],
                "forbiddenActions": ["modify code"],
            },
        }
        errors = validate_role_semantics(role)
        assert not errors
