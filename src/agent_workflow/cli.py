"""CLI entry point for agent-workflow (awf)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_workflow import __version__
from agent_workflow.errors import ParseError
from agent_workflow.validation import (
    parse_all_resources,
    validate_directory,
    validate_file,
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

    if target.is_file():
        errors = validate_file(target)
        if errors:
            for e in errors:
                print(f"FAIL {target}: {e}")
            return 1
        else:
            print(f"PASS {target}")
            return 0
    elif target.is_dir():
        results = validate_directory(target)
        if not results:
            # No YAML/JSON files found
            print(f"No resources found in {args.target}")
            return 0

        passed = 0
        failed = 0

        # Collect all processed files
        for file_path, errs in results.items():
            if errs:
                for e in errs:
                    print(f"FAIL {file_path}: {e}")
                failed += 1
            else:
                print(f"PASS {file_path}")
                passed += 1

        total = passed + failed
        print(f"\n{passed}/{total} passed" + (f", {failed} failed" if failed else ""))
        return 1 if failed else 0
    else:
        print(f"ERROR: not a file or directory: {target}", file=sys.stderr)
        return 1


def cmd_inspect(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"ERROR: path not found: {target}", file=sys.stderr)
        return 1

    try:
        resources = parse_all_resources(target)
    except ParseError as e:
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
