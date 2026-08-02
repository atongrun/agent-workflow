"""Validation logic: schema validation and semantic checks."""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml

from agent_workflow.errors import ParseError
from agent_workflow.models import VALID_KINDS, Resource

SOURCE_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"
PACKAGE_SCHEMA_DIR = "schemas"

KIND_TO_SCHEMA: dict[str, str] = {
    "Role": "role.schema.json",
    "Workflow": "workflow.schema.json",
    "Artifact": "artifact.schema.json",
}

_schema_cache: dict[str, dict[str, Any]] = {}


def _read_schema(filename: str) -> str:
    package_resource = resources.files("agent_workflow").joinpath(PACKAGE_SCHEMA_DIR, filename)
    if package_resource.is_file():
        return package_resource.read_text(encoding="utf-8")

    source_path = SOURCE_SCHEMA_DIR / filename
    if source_path.is_file():
        return source_path.read_text(encoding="utf-8")

    raise FileNotFoundError(f"Schema not found in package resources or source checkout: {filename}")


def _load_schema(kind: str) -> dict[str, Any]:
    if kind in _schema_cache:
        return _schema_cache[kind]
    filename = KIND_TO_SCHEMA.get(kind)
    if not filename:
        raise ValueError(f"Unknown kind: {kind}")
    schema = json.loads(_read_schema(filename))
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


def validate_resource_document(document: Any) -> list[str]:
    """Validate one parsed resource document against its JSON Schema."""
    if not isinstance(document, dict):
        return ["resource document must be an object"]

    errors: list[str] = []
    kind = document.get("kind")
    if not kind:
        return ["missing 'kind' field"]
    if kind not in VALID_KINDS:
        return [f"unknown kind '{kind}'. valid kinds: {', '.join(sorted(VALID_KINDS))}"]

    try:
        schema = _load_schema(kind)
        jsonschema.validate(instance=document, schema=schema)
    except FileNotFoundError as e:
        errors.append(str(e))
    except jsonschema.ValidationError as e:
        field_path = "/".join(str(p) for p in e.absolute_path)
        if field_path:
            errors.append(f"{field_path}: {e.message}")
        else:
            errors.append(e.message)
    except Exception as e:
        errors.append(f"unexpected validation error: {e}")

    return errors


def validate_file(path: Path) -> list[str]:
    """Validate a single file against its JSON Schema. Returns list of error messages."""
    try:
        docs = _parse_yaml_or_json(path)
    except ParseError as e:
        return [e.message]

    errors: list[str] = []
    for document in docs:
        errors.extend(validate_resource_document(document))

    return errors


def resource_files(path: Path) -> list[Path]:
    """Return supported resource files contained by a validation target."""
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []

    files: list[Path] = []
    for root, _, filenames in os.walk(path):
        for filename in filenames:
            candidate = Path(root) / filename
            if candidate.suffix in (".yaml", ".yml", ".json"):
                files.append(candidate)
    return sorted(files)


def parse_resource_documents(path: Path) -> list[dict[str, Any]]:
    """Parse a resource file into raw documents for semantic validation."""
    return _parse_yaml_or_json(path)


def validate_directory(directory: Path) -> dict[str, list[str]]:
    """Recursively validate all YAML/JSON files in a directory."""
    directory = directory.resolve()
    results: dict[str, list[str]] = {}
    for fpath in resource_files(directory):
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
    """Load all parseable Role resources from a directory, keyed by name."""
    role_map: dict[str, dict[str, Any]] = {}
    if not roles_dir.is_dir():
        return role_map
    return load_role_map_from_files(resource_files(roles_dir))


def load_role_map_from_files(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    """Load all parseable Role resources from files, keyed by name."""
    role_map: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            docs = _parse_yaml_or_json(path)
        except ParseError:
            continue
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") == "Role":
                metadata = doc.get("metadata", {})
                if not isinstance(metadata, dict):
                    continue
                name = metadata.get("name", "")
                if name:
                    role_map[name] = doc
    return role_map


def validate_workflow_semantics(
    workflow: dict[str, Any],
    role_map: dict[str, dict[str, Any]] | None,
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
        if role_map is not None and role_name and role_name not in role_map:
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
    metadata = role.get("metadata", {})
    role_name = metadata.get("name", "unknown") if isinstance(metadata, dict) else "unknown"
    spec = role.get("spec", {})
    if not isinstance(spec, dict):
        return errors

    raw_capabilities = spec.get("capabilities", [])
    raw_forbidden = spec.get("forbiddenActions", [])
    capabilities = (
        {capability for capability in raw_capabilities if isinstance(capability, str)}
        if isinstance(raw_capabilities, list)
        else set()
    )
    forbidden = (
        {action for action in raw_forbidden if isinstance(action, str)}
        if isinstance(raw_forbidden, list)
        else set()
    )

    # Check for conflicts: same action in both capabilities and forbidden
    conflicts = capabilities & forbidden
    for c in conflicts:
        msg = f"role '{role_name}': action '{c}' appears in both capabilities and forbiddenActions"
        errors.append(msg)

    return errors
