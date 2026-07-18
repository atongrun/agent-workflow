"""Validation logic: schema validation and semantic checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from agent_workflow.errors import ParseError
from agent_workflow.models import VALID_KINDS, Resource

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"

KIND_TO_SCHEMA: dict[str, str] = {
    "Role": "role.schema.json",
    "Workflow": "workflow.schema.json",
    "Artifact": "artifact.schema.json",
}

_schema_cache: dict[str, dict[str, Any]] = {}


def _load_schema(kind: str) -> dict[str, Any]:
    if kind in _schema_cache:
        return _schema_cache[kind]
    filename = KIND_TO_SCHEMA.get(kind)
    if not filename:
        raise ValueError(f"Unknown kind: {kind}")
    path = SCHEMA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    _schema_cache[kind] = schema
    return schema


def _parse_yaml_or_json(path: Path) -> list[dict[str, Any]]:
    """Parse a YAML or JSON file, supporting multi-document YAML."""
    with open(path, encoding="utf-8") as f:
        content = f.read()

    if path.suffix in (".yaml", ".yml"):
        try:
            docs = list(yaml.safe_load_all(content))
            return [d for d in docs if d is not None]
        except yaml.YAMLError as e:
            raise ParseError(str(path), f"YAML parse error: {e}") from e
    elif path.suffix == ".json":
        try:
            doc = json.loads(content)
            return [doc]
        except json.JSONDecodeError as e:
            raise ParseError(str(path), f"JSON parse error: {e}") from e
    else:
        raise ParseError(str(path), f"Unsupported file extension: {path.suffix}")
    return []


def validate_file(path: Path) -> list[str]:
    """Validate a single file against its JSON Schema. Returns list of error messages."""
    errors: list[str] = []
    try:
        docs = _parse_yaml_or_json(path)
    except ParseError as e:
        return [str(e)]

    for doc in docs:
        kind = doc.get("kind")
        if not kind:
            errors.append("missing 'kind' field")
            continue
        if kind not in VALID_KINDS:
            errors.append(f"unknown kind '{kind}'. valid kinds: {', '.join(sorted(VALID_KINDS))}")
            continue

        try:
            schema = _load_schema(kind)
            jsonschema.validate(instance=doc, schema=schema)
        except FileNotFoundError as e:
            errors.append(str(e))
        except jsonschema.ValidationError as e:
            field_path = "/".join(str(p) for p in e.absolute_path)
            if field_path:
                prefix = "" if field_path.startswith("/") else "/"
                errors.append(f"spec{prefix}{field_path}: {e.message}")
            else:
                errors.append(e.message)
        except Exception as e:
            errors.append(f"unexpected validation error: {e}")

    return errors


def validate_directory(directory: Path) -> dict[str, list[str]]:
    """Recursively validate all YAML/JSON files in a directory."""
    directory = directory.resolve()
    results: dict[str, list[str]] = {}
    for root, _, files in os.walk(str(directory)):
        for fname in sorted(files):
            if fname.endswith((".yaml", ".yml", ".json")):
                fpath = Path(root) / fname
                rel = str(fpath.relative_to(directory))
                errs = validate_file(fpath)
                results[rel] = errs
    return results


def parse_resource(path: Path) -> Resource:
    """Parse a single-document file into a Resource."""
    docs = _parse_yaml_or_json(path)
    if not docs:
        raise ParseError(str(path), "empty document")
    if len(docs) > 1:
        raise ParseError(str(path), "multi-document files not supported for single resource parse")
    doc = docs[0]
    return Resource(
        apiVersion=doc.get("apiVersion", ""),
        kind=doc.get("kind", ""),
        metadata=doc.get("metadata", {}),
        spec=doc.get("spec", {}),
    )


def parse_all_resources(path: Path) -> list[Resource]:
    """Parse multi-document YAML file into a list of Resources."""
    docs = _parse_yaml_or_json(path)
    resources = []
    for doc in docs:
        resources.append(
            Resource(
                apiVersion=doc.get("apiVersion", ""),
                kind=doc.get("kind", ""),
                metadata=doc.get("metadata", {}),
                spec=doc.get("spec", {}),
            )
        )
    return resources


def load_role_map(roles_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all Role resources from a directory, keyed by name."""
    role_map: dict[str, dict[str, Any]] = {}
    if not roles_dir.is_dir():
        return role_map
    for fname in sorted(os.listdir(roles_dir)):
        if fname.endswith((".yaml", ".yml", ".json")):
            fpath = roles_dir / fname
            try:
                docs = _parse_yaml_or_json(fpath)
            except ParseError:
                continue
            for doc in docs:
                if doc.get("kind") == "Role":
                    name = doc.get("metadata", {}).get("name", "")
                    if name:
                        role_map[name] = doc
    return role_map


def validate_workflow_semantics(
    workflow: dict[str, Any],
    role_map: dict[str, dict[str, Any]],
) -> list[str]:
    """Semantic validation for a workflow definition. Returns list of error messages."""
    errors: list[str] = []
    stages = workflow.get("spec", {}).get("stages", [])
    wf_name = workflow.get("metadata", {}).get("name", "unknown")

    if not stages:
        errors.append(f"workflow '{wf_name}' has no stages")
        return errors

    stage_ids = set()
    on_success_targets = set()
    on_failure_targets = set()

    for stage in stages:
        sid = stage.get("id", "")
        role_name = stage.get("role", "")

        # Duplicate stage IDs
        if sid in stage_ids:
            errors.append(f"workflow '{wf_name}': duplicate stage id '{sid}'")
        stage_ids.add(sid)

        # Role existence
        if role_name and role_name not in role_map:
            errors.append(f"workflow '{wf_name}', stage '{sid}': role '{role_name}' not found")

        # Collect transitions
        on_success = stage.get("onSuccess", "")
        on_failure = stage.get("onFailure", "")
        if on_success:
            on_success_targets.add(on_success)
        if on_failure:
            on_failure_targets.add(on_failure)

    # Terminal states are valid targets
    terminal_states = set(workflow.get("spec", {}).get("terminalStates", []))
    valid_targets = stage_ids | terminal_states

    # Check onSuccess targets
    for target in on_success_targets:
        if target not in valid_targets and target not in terminal_states:
            msg = (
                f"workflow '{wf_name}': onSuccess target '{target}'"
                " is not a valid stage or terminal state"
            )
            errors.append(msg)

    # Check onFailure targets
    for target in on_failure_targets:
        if target not in valid_targets and target not in terminal_states:
            msg = (
                f"workflow '{wf_name}': onFailure target '{target}'"
                " is not a valid stage or terminal state"
            )
            errors.append(msg)

    return errors


def validate_role_semantics(role: dict[str, Any]) -> list[str]:
    """Semantic validation for a single role. Returns list of error messages."""
    errors: list[str] = []
    role_name = role.get("metadata", {}).get("name", "unknown")
    spec = role.get("spec", {})
    capabilities = set(spec.get("capabilities", []))
    forbidden = set(spec.get("forbiddenActions", []))

    # Check for conflicts: same action in both capabilities and forbidden
    conflicts = capabilities & forbidden
    for c in conflicts:
        msg = f"role '{role_name}': action '{c}' appears in both capabilities and forbiddenActions"
        errors.append(msg)

    return errors
