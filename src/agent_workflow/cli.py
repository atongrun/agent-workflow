"""CLI entry point for agent-workflow (awf)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_workflow import __version__
from agent_workflow.errors import ParseError
from agent_workflow.validation import (
    load_role_map_from_files,
    parse_all_resources,
    parse_resource_documents,
    resource_files,
    validate_resource_document,
    validate_role_semantics,
    validate_workflow_semantics,
)

ROLE_MAP_UNAVAILABLE_WARNING = (
    "role existence checks skipped: no named Role resources found in the validation target "
    "or project roles/"
)


def _find_project_root() -> Path:
    """Find the project root by looking for schemas/ directory."""
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        if (p / "schemas").is_dir():
            return p
    return cwd


def cmd_version(args: argparse.Namespace) -> int:
    print(f"awf {__version__}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"ERROR: path not found: {target}", file=sys.stderr)
        return 1

    if not target.is_file() and not target.is_dir():
        print(f"ERROR: not a file or directory: {target}", file=sys.stderr)
        return 1

    files = resource_files(target)
    if target.is_dir() and not files:
        print(f"No resources found in {args.target}")
        return 0

    results, documents_by_path, schema_valid_documents = _validate_resource_files(files)
    warnings = _add_semantic_validation(target, results, documents_by_path, schema_valid_documents)
    return _print_validation_results(target, results, warnings)


def _validate_resource_files(
    files: list[Path],
) -> tuple[dict[Path, list[str]], dict[Path, list[dict]], dict[Path, set[int]]]:
    """Parse files once and retain which individual documents pass schema validation."""
    results: dict[Path, list[str]] = {}
    documents_by_path: dict[Path, list[dict]] = {}
    schema_valid_documents: dict[Path, set[int]] = {}

    for path in files:
        try:
            documents = parse_resource_documents(path)
        except ParseError as error:
            results[path] = [error.message]
            continue

        documents_by_path[path] = documents
        schema_valid_documents[path] = set()
        errors: list[str] = []
        for index, document in enumerate(documents):
            document_errors = validate_resource_document(document)
            errors.extend(document_errors)
            if not document_errors:
                schema_valid_documents[path].add(index)
        results[path] = errors

    return results, documents_by_path, schema_valid_documents


def _add_semantic_validation(
    target: Path,
    results: dict[Path, list[str]],
    documents_by_path: dict[Path, list[dict]],
    schema_valid_documents: dict[Path, set[int]],
) -> dict[Path, list[str]]:
    """Append semantic errors for all Roles and schema-valid Workflows."""
    target_role_files = [
        path
        for path, documents in documents_by_path.items()
        if any(
            isinstance(document, dict) and document.get("kind") == "Role" for document in documents
        )
    ]
    project_roles_dir = _find_project_root() / "roles"
    project_role_files = resource_files(project_roles_dir)
    role_map = load_role_map_from_files([*project_role_files, *target_role_files])
    role_map_for_semantics = role_map or None

    warnings: dict[Path, list[str]] = {}
    for path, documents in documents_by_path.items():
        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                continue
            kind = document.get("kind")
            if kind == "Role":
                results[path].extend(validate_role_semantics(document))
            elif kind == "Workflow" and index in schema_valid_documents[path]:
                results[path].extend(validate_workflow_semantics(document, role_map_for_semantics))
                if role_map_for_semantics is None:
                    warnings.setdefault(path, []).append(ROLE_MAP_UNAVAILABLE_WARNING)
    return warnings


def _print_validation_results(
    target: Path,
    results: dict[Path, list[str]],
    warnings: dict[Path, list[str]],
) -> int:
    """Print validation results and return a process exit code."""
    passed = 0
    failed = 0
    for path, errors in results.items():
        display_path = str(path) if target.is_file() else str(path.relative_to(target))
        for warning in warnings.get(path, []):
            print(f"WARN {display_path}: {warning}")
        if errors:
            for error in errors:
                print(f"FAIL {display_path}: {error}")
            failed += 1
        else:
            print(f"PASS {display_path}")
            passed += 1

    if target.is_dir():
        total = passed + failed
        print(f"\n{passed}/{total} passed" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


def cmd_inspect(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"ERROR: path not found: {target}", file=sys.stderr)
        return 1
    if target.is_dir():
        print(f"ERROR: cannot inspect a directory: {target}", file=sys.stderr)
        return 1

    try:
        resources = parse_all_resources(target)
    except (OSError, ParseError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    for i, resource in enumerate(resources):
        if i > 0:
            print("---")
        _print_resource(resource)

    return 0


def _print_resource(resource) -> None:
    meta = resource.metadata
    print(f"apiVersion: {resource.apiVersion}")
    print(f"kind: {resource.kind}")
    print(f"name: {meta.get('name', '(none)')}")
    print(f"version: {meta.get('version', '(none)')}")
    if meta.get("description"):
        print(f"description: {meta['description']}")

    spec = resource.spec

    if resource.kind == "Workflow":
        stages = spec.get("stages", [])
        print(f"stages: {len(stages)}")
        for stage in stages:
            sid = stage.get("id", "")
            role = stage.get("role", "")
            on_success = stage.get("onSuccess", "")
            on_failure = stage.get("onFailure", "")
            transitions = []
            if on_success:
                transitions.append(f"onSuccess: {on_success}")
            if on_failure:
                transitions.append(f"onFailure: {on_failure}")
            trans_str = f" ({', '.join(transitions)})" if transitions else ""
            print(f"  - {sid} [{role}]{trans_str}")

    elif resource.kind == "Role":
        capabilities = spec.get("capabilities", [])
        forbidden = spec.get("forbiddenActions", [])
        produced = spec.get("producedArtifacts", [])
        if capabilities:
            print(f"capabilities ({len(capabilities)}):")
            for c in capabilities:
                print(f"  - {c}")
        if forbidden:
            print(f"forbiddenActions ({len(forbidden)}):")
            for f in forbidden:
                print(f"  - {f}")
        if produced:
            print(f"producedArtifacts ({len(produced)}):")
            for a in produced:
                print(f"  - {a}")

    else:
        # Generic: print spec keys
        if isinstance(spec, dict):
            print(f"spec keys: {', '.join(sorted(spec.keys()))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="awf",
        description="Agent Workflow — a portable personal development method: "
        "role, workflow, and artifact contracts for AI coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # version
    version_parser = subparsers.add_parser("version", help="Print version")
    version_parser.set_defaults(func=cmd_version)

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate resource files")
    validate_parser.add_argument("target", help="File or directory to validate")
    validate_parser.set_defaults(func=cmd_validate)

    # inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a resource file")
    inspect_parser.add_argument("target", help="File to inspect")
    inspect_parser.set_defaults(func=cmd_inspect)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
