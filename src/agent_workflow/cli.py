"""CLI entry point for agent-workflow (awf)."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from agent_workflow import __version__, node
from agent_workflow.errors import ParseError
from agent_workflow.manifest import (
    ManifestError,
    compile_run_contract,
    default_compiled_report_path,
    default_manifest_path,
    derive_manifest,
    load_compiled_report,
    load_manifest,
    resolve_manifest_card,
    write_compiled_report,
    write_manifest,
)
from agent_workflow.resources import authority_manifest_path, operations_dir
from agent_workflow.state_root import resolve_state_root, state_root_binding
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


def cmd_node(args: argparse.Namespace) -> int:
    options = {
        "lines": getattr(args, "lines", 100),
        "run_id": getattr(args, "run", ""),
        "json_output": getattr(args, "json", False),
        "explain": getattr(args, "explain", False),
        "ttl_seconds": getattr(args, "ttl_seconds", 3600),
    }
    if getattr(args, "allow_session_bound", False):
        options["allow_session_bound"] = True
    return node.run(args.node_command, args.profile, **options)


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


def _resolve_card(card: str, repo: Path) -> Path:
    candidate = Path(card)
    if not candidate.is_absolute():
        candidate = repo / candidate
    if candidate.is_file():
        return candidate.resolve()
    for option in (repo / ".awf/cards" / card, repo / "docs" / card):
        if option.is_file():
            return option.resolve()
    raise ManifestError(f"TaskCard not found: {card}")


def _load_owner_manifest(repo: Path, card: Path, path: str = "") -> tuple[dict, Path]:
    """Load the one owner manifest and ensure it belongs to this TaskCard."""
    manifest_path = Path(path).expanduser() if path else default_manifest_path(repo)
    try:
        values = load_manifest(manifest_path)
    except ManifestError as exc:
        raise ManifestError(f"owner RunManifest unavailable: {exc}") from exc
    if resolve_manifest_card(values, repo) != card.resolve():
        raise ManifestError("owner RunManifest card does not match --card")
    return values, manifest_path.resolve()


def _manifest_value(values: dict, key: str, default: str = "") -> str:
    value = values.get(key, default)
    return str(value) if value is not None else default


def _ops_module():
    scripts = operations_dir()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import awf_control_plane

    return awf_control_plane


def _authority_manifest_for_repo(repo: Path) -> Path:
    """Preserve an explicit downstream manifest, otherwise use the packaged default."""
    downstream = repo / "scripts" / "authority-manifest.example.json"
    return downstream if downstream.is_file() else authority_manifest_path()


def _profile_arguments(values: list[str]) -> list[node.NodeProfile]:
    profiles: list[node.NodeProfile] = []
    for value in values:
        role, separator, path = value.partition("=")
        if not separator or role not in {"coder", "reviewer"} or not path:
            raise ManifestError("--profile must be coder=PATH or reviewer=PATH")
        profile = node.load_installed_profile(path) or node.load_profile(path)
        if profile.role != role:
            raise ManifestError(f"--profile role {role!r} contains {profile.role!r}")
        profiles.append(profile)
    return profiles


def _profile_reference_map(values: list[str]) -> dict[str, str]:
    references: dict[str, str] = {}
    for value in values:
        role, separator, path = value.partition("=")
        if not separator or role not in {"coder", "reviewer"} or not path:
            raise ManifestError("--profile must be coder=PATH or reviewer=PATH")
        if role in references:
            raise ManifestError(f"--profile contains duplicate role {role!r}")
        references[role] = path
    if set(references) != {"coder", "reviewer"}:
        raise ManifestError("--profile requires exactly one coder and one reviewer")
    return references


def _compiler_inputs(
    values: dict, state_root_value: str = "", profile_values: list[str] | None = None
) -> tuple[Path, list[str]]:
    manifest_state_root = str(values.get("state_root", ""))
    manifest_profiles = values.get("profiles", {})
    supplied_profiles = _profile_reference_map(profile_values) if profile_values else {}
    if state_root_value and manifest_state_root:
        if resolve_state_root(state_root_value) != resolve_state_root(manifest_state_root):
            raise ManifestError("--state-root conflicts with owner RunManifest")
    if supplied_profiles and manifest_profiles and supplied_profiles != manifest_profiles:
        raise ManifestError("--profile conflicts with owner RunManifest")
    selected_state_root = state_root_value or manifest_state_root
    selected_profiles = supplied_profiles or manifest_profiles
    if not selected_state_root or set(selected_profiles) != {"coder", "reviewer"}:
        raise ManifestError(
            "owner RunManifest has no compiled inputs; rerun awf setup with --state-root and "
            "coder/reviewer --profile bindings"
        )
    return resolve_state_root(selected_state_root), [
        f"{role}={selected_profiles[role]}" for role in ("coder", "reviewer")
    ]


def _compile_owner_contract(
    *,
    repo: Path,
    values: dict,
    manifest_path: Path,
    authority_manifest: str = "",
    state_root_value: str = "",
    profile_values: list[str] | None = None,
    run_id: str = "",
) -> dict:
    ops = _ops_module()
    try:
        scripts = operations_dir()
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import awf_artifact_contract

        card = resolve_manifest_card(values, repo)
        authority_path = (
            Path(authority_manifest).expanduser().resolve()
            if authority_manifest
            else _authority_manifest_for_repo(repo)
        )
        authority = ops.load_authority_manifest(authority_path)
        authority_binding = ops.authority_manifest_binding(authority)
        artifact = awf_artifact_contract.compile_run_artifact_contract(
            repo=repo,
            card_path=card,
            task_id=str(values["task_id"]),
            implementation_report_path=str(values["report_paths"]["implementation"]),
            review_report_path=str(values["report_paths"]["review"]),
        )
        state_root, profile_args = _compiler_inputs(values, state_root_value, profile_values)
        profiles = _profile_arguments(profile_args)
        taskcard_binding = {
            "format": "awf.taskcard-postflight.v1",
            "path": artifact.taskcard_path,
            "sha256": "sha256:" + hashlib.sha256(card.read_bytes()).hexdigest(),
            "allowed_paths_sha256": "sha256:"
            + hashlib.sha256(
                json.dumps(
                    artifact.allowed_paths,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "task_id": artifact.task_id,
            "implementation_report_path": artifact.implementation_report_path,
            "review_report_path": artifact.review_report_path,
            "mutable_by_model": False,
        }
        profile_bindings = [
            {
                "role": profile.role,
                "path": str(profile.path),
                "profile_source": "installed" if profile.source_path else "authoring",
                "sha256": profile.digest,
                "state_root": str(profile.state_root),
                "values": profile.values,
            }
            for profile in profiles
        ]
        selected_run_id = run_id or f"task-{str(values['branch']).rsplit('/', 1)[-1]}"
        return compile_run_contract(
            repo=repo,
            run_id=selected_run_id,
            run_manifest=values,
            run_manifest_path=manifest_path,
            authority_manifest=authority,
            authority_manifest_path=authority_path,
            authority_binding=authority_binding,
            taskcard_binding=taskcard_binding,
            state_root=state_root,
            state_root_sha256=state_root_binding(state_root),
            profiles=profile_bindings,
            compiler_version=__version__,
        )
    except (ops.ControlPlaneDenied, awf_artifact_contract.ArtifactContractError) as exc:
        raise ManifestError(str(exc)) from exc


def cmd_plan_check(args: argparse.Namespace) -> int:
    """Compile a local-only run contract report before any operational action."""
    try:
        repo = Path(args.repo).resolve()
        manifest_path = Path(args.run_manifest).expanduser().resolve()
        values = load_manifest(manifest_path)
        report = _compile_owner_contract(
            repo=repo,
            values=values,
            manifest_path=manifest_path,
            authority_manifest=args.authority_manifest,
            state_root_value=args.state_root,
            profile_values=args.profile,
            run_id=args.run,
        )
    except (ManifestError, OSError, node.NodeError) as exc:
        print(f"ERROR: plan check failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    try:
        if getattr(args, "manifest", ""):
            raise ManifestError("--manifest was replaced by --run-manifest for awf setup")
        repo = Path(args.repo).resolve()
        _profile_reference_map(args.profile)
        resolved_profiles = _profile_arguments(args.profile)
        profile_references = {
            profile.role: str(profile.path.resolve()) for profile in resolved_profiles
        }
        if not args.state_root:
            raise ManifestError("awf setup requires an explicit --state-root")
        state_root = resolve_state_root(args.state_root)
        values = derive_manifest(
            _resolve_card(args.card, repo),
            branch=args.branch,
            tool=args.tool,
            model=args.model,
            reviewer_tool=getattr(args, "reviewer_tool", ""),
            reviewer_model=getattr(args, "reviewer_model", ""),
            rework_budget=args.rework_budget,
            upstream_repo=args.upstream_repo,
            head_repo=args.head_repo,
            upstream_remote=args.upstream_remote,
            head_remote=args.head_remote,
            base_ref=args.base_ref,
            state_root=str(state_root),
            profiles=profile_references,
        )
        path = (
            Path(args.run_manifest).expanduser().resolve()
            if args.run_manifest
            else default_manifest_path(repo)
        )
        contract_path = (
            Path(args.run_contract).expanduser().resolve()
            if args.run_contract
            else default_compiled_report_path(repo)
        )
        if not args.replace and (path.exists() or contract_path.exists()):
            raise ManifestError(
                "owner RunManifest or compiled contract already exists; pass --replace"
            )
        report = _compile_owner_contract(
            repo=repo,
            values=values,
            manifest_path=path,
            authority_manifest=args.authority_manifest,
        )
        write_manifest(path, values)
        write_compiled_report(contract_path, report)
    except (ManifestError, OSError, node.NodeError) as exc:
        print(f"ERROR: setup failed: {exc}", file=sys.stderr)
        return 1
    print(f"configured RunManifest: {path.resolve()}")
    print(f"compiled run contract: {contract_path.resolve()} ({report['contract_sha256']})")
    print("secrets unchanged: configure dispatch.env separately; .envrc was not written")
    return 0


def _load_run(args: argparse.Namespace):
    ops = _ops_module()
    try:
        return ops, ops.RunLedger(Path(args.state_root), args.run).recover()
    except ops.ControlPlaneDenied as exc:
        raise ManifestError(str(exc)) from exc


def cmd_status(args: argparse.Namespace) -> int:
    try:
        _, (ledger, packet) = _load_run(args)
    except ManifestError as exc:
        print(f"ERROR: status unavailable: {exc}", file=sys.stderr)
        return 1
    failures = [
        item
        for item in ledger.get("decisions", [])
        if isinstance(item, dict) and item.get("status") == "rejected"
    ]
    health = packet.get("health") or ledger.get("health") or {}
    if not isinstance(health, dict):
        health = {}
    queue = packet.get("queue") or ledger.get("queue") or {}
    if not isinstance(queue, dict):
        queue = {}
    health_values = {
        name: str(health.get(name) or "not_recorded") for name in ("listener", "bus", "postflight")
    }
    pending = str(queue.get("pending") or "not_recorded")
    print(
        f"run={args.run} state={ledger.get('terminal_state') or 'running'} "
        f"stage={packet.get('stage', ledger.get('stage', ''))}"
    )
    checkpoint = packet.get("phase") or packet.get("transition") or "not_recorded"
    print(f"checkpoint={checkpoint}")
    print(
        "health: "
        f"listener={health_values['listener']} "
        f"bus={health_values['bus']} "
        f"postflight={health_values['postflight']}"
    )
    print(f"queue: pending={pending} attempts={ledger.get('attempts', 0)}")
    print(f"first_failure={failures[0].get('reason', '') if failures else 'none'}")
    print(f"next_legal_action={packet.get('next_action', 'stop')}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    try:
        _, (ledger, packet) = _load_run(args)
    except ManifestError as exc:
        print(f"ERROR: resume unavailable: {exc}", file=sys.stderr)
        return 1
    action = str(packet.get("next_action", "stop"))
    allowed = {
        "clean_checkout",
        "listener_lease",
        "dispatch",
        "trusted_postflight",
        "verify_pr_ci",
        "ledger_finalize",
        "refresh_main",
        "stop",
    }
    if action not in allowed:
        print(
            f"ERROR: resume denied; next action '{action}' is not protocol-authorized",
            file=sys.stderr,
        )
        return 1
    if ledger.get("terminal_state"):
        print(f"run={args.run} terminal={ledger['terminal_state']}; no resume action is legal")
        return 0
    print(f"run={args.run} resume={action}")
    print("only this single next action is legal; model replay and requeue are forbidden")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ops = _ops_module()
    try:
        if getattr(args, "manifest", ""):
            raise ManifestError("--manifest was replaced by --run-manifest for awf run")
        repo = Path(args.repo).resolve()
        card = _resolve_card(args.card, repo)
        values, manifest_path = _load_owner_manifest(repo, card, args.run_manifest)
        supplied = {
            "branch": args.branch,
            "tool": args.tool,
            "model": args.model,
            "reviewer_tool": getattr(args, "reviewer_tool", ""),
            "reviewer_model": getattr(args, "reviewer_model", ""),
        }
        expected = {
            "branch": _manifest_value(values, "branch"),
            "tool": _manifest_value(values.get("models", {}), "tool"),
            "model": _manifest_value(values.get("models", {}), "model"),
            "reviewer_tool": _manifest_value(values.get("models", {}), "reviewer_tool"),
            "reviewer_model": _manifest_value(values.get("models", {}), "reviewer_model"),
        }
        if not expected["tool"]:
            raise ManifestError("owner RunManifest tool is empty; rerun awf setup --replace --tool")
        for field, value in expected.items():
            if supplied[field] and supplied[field] != value:
                raise ManifestError(f"--{field} conflicts with owner RunManifest")
        manifest_budget = values.get("rework_budget", 0)
        if (
            args.rework_budget is not None
            and args.rework_budget != 1
            and args.rework_budget != manifest_budget
        ):
            raise ManifestError("--rework-budget conflicts with owner RunManifest")
        canonical_run_id = f"task-{str(values['branch']).rsplit('/', 1)[-1]}"
        if args.run and args.run != canonical_run_id:
            raise ManifestError(
                f"--run must be {canonical_run_id!r} to match trusted listener recovery"
            )
        run_id = canonical_run_id
        state_root, _ = _compiler_inputs(values)
        if args.state_root and resolve_state_root(args.state_root) != state_root:
            raise ManifestError("--state-root conflicts with compiled owner RunManifest")
        contract_path = (
            Path(args.run_contract).expanduser().resolve()
            if args.run_contract
            else default_compiled_report_path(repo)
        )
        persisted_report = load_compiled_report(contract_path)
        authority_path = Path(
            str(persisted_report.get("bindings", {}).get("authority_manifest", {}).get("path", ""))
        )
        current_report = _compile_owner_contract(
            repo=repo,
            values=values,
            manifest_path=manifest_path,
            authority_manifest=str(authority_path),
            run_id=run_id,
        )
        if current_report != persisted_report:
            raise ManifestError(
                "compiled run contract drifted; rerun awf setup --replace before awf run"
            )
        authority = ops.authority_manifest_binding(ops.load_authority_manifest(authority_path))
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        packet = ops.build_context_packet(
            run_id=run_id,
            taskcard=str(card.relative_to(repo)),
            frozen_base=base,
            branch=values["branch"],
            authority_manifest=authority,
            next_action="clean_checkout",
            stage="implement",
            state_root_sha256=state_root_binding(state_root),
            run_contract_sha256=str(current_report["contract_sha256"]),
        )
        ops.RunLedger(state_root, run_id).initialize(
            packet,
            stage="implement",
            max_attempts=1,
            rework_budget=int(manifest_budget),
        )
    except (ManifestError, OSError, subprocess.CalledProcessError, ops.ControlPlaneDenied) as exc:
        print(f"ERROR: run failed: {exc}", file=sys.stderr)
        return 1
    print(f"run={run_id} stage=implement next=clean_checkout")
    print("serial runbook initialized; use awf status --run and awf resume --run")
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    scripts = operations_dir()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import awf_dispatch

        awf_dispatch.load_optional_config()
        awf_dispatch.dispatch(args)
    except RuntimeError as exc:
        print(f"ERROR: dispatch failed: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    """Run the packaged preflight CLI without requiring a source checkout."""
    if not args.preflight_args or args.preflight_args[0] != "resume-deep":
        print("ERROR: awf preflight supports only resume-deep", file=sys.stderr)
        return 2
    scripts = operations_dir()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import awf_preflight

    return awf_preflight.main(args.preflight_args)


def cmd_feedback(args: argparse.Namespace) -> int:
    """Run the packaged, business-independent feedback operations CLI."""
    scripts = operations_dir()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import awf_feedback

    forwarded = [args.feedback_command]
    if args.state_root is not None:
        forwarded += ["--state-root", str(args.state_root)]
    if args.feedback_command == "status" and args.json:
        forwarded.append("--json")
    elif args.feedback_command == "flush":
        if args.config is not None:
            forwarded += ["--config", str(args.config)]
        forwarded += ["--limit", str(args.limit)]
    elif args.feedback_command == "ingest":
        forwarded += ["--payload-json", args.payload_json]
    return awf_feedback.main(forwarded)


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

    setup_parser = subparsers.add_parser("setup", help="Create a credential-free owner RunManifest")
    setup_parser.add_argument("--repo", default=".")
    setup_parser.add_argument("--card", required=True)
    setup_parser.add_argument("--run-manifest", default="")
    setup_parser.add_argument("--manifest", default="", help=argparse.SUPPRESS)
    setup_parser.add_argument("--run-contract", default="")
    setup_parser.add_argument("--authority-manifest", default="")
    setup_parser.add_argument("--state-root", default="")
    setup_parser.add_argument("--profile", action="append", default=[])
    setup_parser.add_argument("--branch", default="")
    setup_parser.add_argument("--tool", required=True)
    setup_parser.add_argument("--model", default="")
    setup_parser.add_argument("--reviewer-tool", default="")
    setup_parser.add_argument("--reviewer-model", default="")
    setup_parser.add_argument("--rework-budget", type=int, default=1)
    setup_parser.add_argument("--upstream-repo", default="")
    setup_parser.add_argument("--head-repo", default="")
    setup_parser.add_argument("--upstream-remote", default="upstream")
    setup_parser.add_argument("--head-remote", default="fork")
    setup_parser.add_argument("--base-ref", default="main")
    setup_parser.add_argument("--replace", action="store_true")
    setup_parser.set_defaults(func=cmd_setup)

    plan_parser = subparsers.add_parser("plan", help="Compile or lint owner run intent")
    plan_commands = plan_parser.add_subparsers(dest="plan_command", required=True)
    plan_check_parser = plan_commands.add_parser(
        "check", help="Read and validate a complete local run contract"
    )
    plan_check_parser.add_argument("--repo", default=".")
    plan_check_parser.add_argument("--run-manifest", required=True)
    plan_check_parser.add_argument("--authority-manifest", default="")
    plan_check_parser.add_argument("--state-root", default="")
    plan_check_parser.add_argument("--run", default="")
    plan_check_parser.add_argument(
        "--profile",
        action="append",
        help="Bind one exact role profile as coder=PATH or reviewer=PATH",
    )
    plan_check_parser.set_defaults(func=cmd_plan_check)

    dispatch_parser = subparsers.add_parser(
        "dispatch", help="Dispatch a TaskCard from its manifest"
    )
    dispatch_parser.add_argument("--repo", default=".", type=Path)
    dispatch_parser.add_argument("--card", required=True)
    dispatch_parser.add_argument("--manifest", type=Path, default=None)
    dispatch_parser.add_argument("--branch", default="")
    dispatch_parser.add_argument("--to", default="coder")
    dispatch_parser.add_argument("--tool", default="")
    dispatch_parser.add_argument("--model", default="")
    dispatch_parser.add_argument("--reviewer-tool", default="")
    dispatch_parser.add_argument("--reviewer-model", default="")
    dispatch_parser.add_argument("--report", default="")
    dispatch_parser.add_argument("--review-report", default="")
    dispatch_parser.add_argument("--upstream-repo", default="")
    dispatch_parser.add_argument("--upstream-remote", default="")
    dispatch_parser.add_argument("--head-repo", default="")
    dispatch_parser.add_argument("--head-remote", default="")
    dispatch_parser.add_argument("--base-ref", default="")
    dispatch_parser.add_argument("--type", dest="event_type", default="task:awf-impl-v3")
    dispatch_parser.add_argument("--no-push", action="store_true")
    dispatch_parser.add_argument("--dry-run", action="store_true")
    dispatch_parser.set_defaults(func=cmd_dispatch)

    preflight_parser = subparsers.add_parser(
        "preflight", help="Recover one completed Deep result after caller timeout"
    )
    preflight_parser.add_argument("preflight_args", nargs=argparse.REMAINDER)
    preflight_parser.set_defaults(func=cmd_preflight)

    feedback_parser = subparsers.add_parser(
        "feedback", help="Operate the independent Dogfood Finding pipeline"
    )
    feedback_commands = feedback_parser.add_subparsers(dest="feedback_command", required=True)
    feedback_status_parser = feedback_commands.add_parser(
        "status", help="Inspect local Feedback Outbox state"
    )
    feedback_status_parser.add_argument("--state-root", type=Path, default=None)
    feedback_status_parser.add_argument("--json", action="store_true")
    feedback_status_parser.set_defaults(func=cmd_feedback)
    feedback_flush_parser = feedback_commands.add_parser(
        "flush", help="Send pending occurrences to Agent Bus"
    )
    feedback_flush_parser.add_argument("--state-root", type=Path, default=None)
    feedback_flush_parser.add_argument("--config", type=Path, default=None)
    feedback_flush_parser.add_argument("--limit", type=int, default=20)
    feedback_flush_parser.set_defaults(func=cmd_feedback)
    feedback_ingest_parser = feedback_commands.add_parser(
        "ingest", help="Durably ingest one occurrence before Bus ACK"
    )
    feedback_ingest_parser.add_argument("--state-root", type=Path, default=None)
    feedback_ingest_parser.add_argument("--payload-json", required=True)
    feedback_ingest_parser.set_defaults(func=cmd_feedback)

    run_parser = subparsers.add_parser("run", help="Initialize the bounded serial operator run")
    run_parser.add_argument("--repo", default=".")
    run_parser.add_argument("--card", required=True)
    run_parser.add_argument("--run-manifest", default="")
    run_parser.add_argument("--manifest", default="", help=argparse.SUPPRESS)
    run_parser.add_argument("--run-contract", default="")
    run_parser.add_argument("--run", default="")
    run_parser.add_argument("--branch", default="")
    run_parser.add_argument("--tool", default="")
    run_parser.add_argument("--model", default="")
    run_parser.add_argument("--reviewer-tool", default="")
    run_parser.add_argument("--reviewer-model", default="")
    run_parser.add_argument("--state-root", default="")
    run_parser.add_argument("--rework-budget", type=int, default=1)
    run_parser.set_defaults(func=cmd_run)

    for name, handler in (("status", cmd_status), ("resume", cmd_resume)):
        operator_parser = subparsers.add_parser(name, help=f"{name.title()} a bounded operator run")
        operator_parser.add_argument("--run", required=True)
        operator_parser.add_argument(
            "--state-root", default=str(Path.home() / ".local/state/agent-workflow")
        )
        operator_parser.set_defaults(func=handler)

    node_parser = subparsers.add_parser("node", help="Operate one local role listener")
    node_commands = node_parser.add_subparsers(dest="node_command", required=True)
    for name in (
        "doctor",
        "foreground",
        "reconcile",
        "install",
        "start",
        "status",
        "stop",
        "logs",
        "restart",
        "upgrade",
        "uninstall",
    ):
        command = node_commands.add_parser(name)
        command.add_argument("--profile", required=True)
        if name == "logs":
            command.add_argument("--lines", type=int, default=100)
        if name == "status":
            command.add_argument("--run", default="")
            command.add_argument("--json", action="store_true")
            command.add_argument("--explain", action="store_true")
        if name == "doctor":
            command.add_argument("--json", action="store_true")
            command.add_argument("--ttl-seconds", type=int, default=3600)
        if name == "start":
            command.add_argument("--allow-session-bound", action="store_true")
        command.set_defaults(func=cmd_node)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
