from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

from agent_workflow import runtime
from agent_workflow.runtime import (
    DecisionOutcome,
    InvocationJournal,
    InvocationSpec,
    ProviderRenderer,
    RenderedInvocation,
    RunStore,
    StatusReader,
)

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "agent_workflow" / "runtime"

ALLOWED_ABSOLUTE_IMPORTS = {
    "__future__",
    "collections",
    "contextlib",
    "copy",
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "os",
    "pathlib",
    "re",
    "secrets",
    "shutil",
    "stat",
    "subprocess",
    "tempfile",
    "typing",
}
FORBIDDEN_SOURCE_TERMS = {
    "sys.path",
    "agent_workflow.operations",
    "import scripts",
    "from scripts",
    "import awf_",
    "from awf_",
    "subprocess",
    "socket",
    "requests",
    "urllib",
}


def public_protocol_methods(protocol: type[object]) -> set[str]:
    return {
        name
        for name, value in protocol.__dict__.items()
        if not name.startswith("_") and inspect.isfunction(value)
    }


def test_runtime_package_has_one_way_standard_library_dependency_boundary() -> None:
    for path in sorted(PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for term in FORBIDDEN_SOURCE_TERMS:
            if term == "subprocess" and path.name in {"application.py", "workspace.py"}:
                continue
            assert term not in source, (path, term)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".", 1)[0] in ALLOWED_ABSOLUTE_IMPORTS, (
                        path,
                        alias.name,
                    )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module is not None
                assert node.module.split(".", 1)[0] in ALLOWED_ABSOLUTE_IMPORTS, (
                    path,
                    node.module,
                )


def test_runtime_package_exports_only_contracts_and_ports() -> None:
    assert set(runtime.__all__) == {
        "INVOCATION_SPEC_FORMAT",
        "RUN_SPEC_FORMAT",
        "AUTHORITY_FORMAT",
        "ATTACH_INPUT",
        "ApplicationError",
        "ArtifactError",
        "ArtifactFact",
        "AtomicInvocationJournal",
        "AtomicRunStore",
        "AtomicStatusReader",
        "AuthorizationCommand",
        "ContractError",
        "CODEX_FINDING_INSTRUCTIONS",
        "CodexReviewerRenderer",
        "DecisionOutcome",
        "HandoffCommand",
        "InvocationJournal",
        "InvocationSpec",
        "JournalAuthorization",
        "JournalSnapshot",
        "LaunchIntent",
        "LocalRuntimeApplication",
        "LocalStageRequest",
        "NormalizedReviewReport",
        "ProcessObservation",
        "ProcessResult",
        "PostflightContract",
        "PostflightObservation",
        "PostflightResult",
        "PreparedWorkspace",
        "OPENCODE_FINDING_INSTRUCTIONS",
        "OpenCodeRenderer",
        "PI_FINDING_INSTRUCTIONS",
        "PiReviewerRenderer",
        "ProviderRenderer",
        "ProviderLauncher",
        "ProviderResult",
        "ProviderSelection",
        "RenderedInputFile",
        "RenderedInvocation",
        "RunDecision",
        "RunArtifactContract",
        "RunSnapshot",
        "RunSpec",
        "RunStore",
        "StatusReader",
        "StartedProvider",
        "StageArtifactContract",
        "StopCommand",
        "StoreError",
        "SubprocessProviderLauncher",
        "TerminalCommand",
        "TerminalOutcome",
        "ValidationEffect",
        "ValidatedReviewArtifact",
        "WorkspaceDelta",
        "WorkspaceError",
        "WorkspaceSpec",
        "WorkflowStage",
        "WriterBusy",
        "assert_frozen_workspace",
        "assert_workspace_state",
        "artifact_fact",
        "bind_environment",
        "compile_implementation_report_path",
        "compile_review_report_path",
        "compile_run_artifact_contract",
        "compile_stage_artifact_contract",
        "freeze_workspace",
        "import_workspace_delta",
        "normalize_rework_feedback",
        "normalize_review_envelope",
        "parse_postflight_contract",
        "parse_review_report",
        "path_is_denied",
        "postflight_result",
        "prepare_workspace",
        "render_provider_invocation",
        "resolve_repo_file",
        "resolve_review_report_path",
        "restore_workspace_manifest",
        "serialize_workspace_delta",
        "scan_secret_text",
        "validate_embedded_review_report",
        "validate_implementation_report",
        "validate_postflight_paths",
        "validate_secret_observation",
        "validate_stage_artifact_contract",
        "workspace_control_sha256",
        "workspace_manifest",
        "workspace_manifest_sha256",
    }


def test_ports_expose_no_arbitrary_phase_or_repair_escape_hatch() -> None:
    assert public_protocol_methods(RunStore) == {
        "initialize",
        "authorize",
        "journal",
        "pending_handoff",
        "record_handoff",
        "record_stop",
        "record_terminal",
    }
    assert public_protocol_methods(InvocationJournal) == {
        "record_launch_intent",
        "record_process_observation",
        "record_result",
        "snapshot",
    }
    assert public_protocol_methods(StatusReader) == {"snapshot"}
    assert public_protocol_methods(ProviderRenderer) == {"render"}
    all_methods = set().union(
        public_protocol_methods(RunStore),
        public_protocol_methods(InvocationJournal),
        public_protocol_methods(StatusReader),
        public_protocol_methods(ProviderRenderer),
    )
    assert not any(
        name.startswith(("set_", "update_", "repair_", "recover_", "delete_"))
        for name in all_methods
    )


def test_renderer_surface_has_no_workflow_or_state_mutation_fields() -> None:
    invocation_fields = {field.name for field in dataclasses.fields(InvocationSpec)}
    rendered_fields = {field.name for field in dataclasses.fields(RenderedInvocation)}

    assert not invocation_fields & {
        "stage",
        "attempt",
        "rework_budget",
        "run_store",
        "journal",
        "state_root",
        "transport",
        "credentials",
    }
    assert rendered_fields == {
        "executable",
        "argv",
        "cwd",
        "stdin",
        "environment",
        "file_inputs",
    }
    assert "shell" not in rendered_fields


def test_decision_outcomes_exactly_match_frozen_contract() -> None:
    assert {outcome.value for outcome in DecisionOutcome} == {
        "SAFE_CONTINUE",
        "SAFE_IDEMPOTENT_REPLAY",
        "SAFE_STABLE_RESEND",
        "DENY_BEFORE_PROVIDER",
        "AMBIGUOUS_NO_REPLAY",
        "DENY_BEFORE_MUTATION",
        "HANDLER_FAILURE_NO_ACK",
        "TERMINAL_IDEMPOTENT",
        "TERMINAL_CONFLICT",
        "OWNER_DECISION_REQUIRED",
        "EXTERNAL_OBSERVATION_UNKNOWN",
    }


def test_package_exports_only_explicit_runtime_values_ports_and_store() -> None:
    exported = [getattr(runtime, name) for name in runtime.__all__]
    protocols = {
        RunStore,
        InvocationJournal,
        StatusReader,
        ProviderRenderer,
        runtime.ProviderLauncher,
        runtime.StartedProvider,
    }
    concrete = {
        runtime.AtomicInvocationJournal,
        runtime.AtomicRunStore,
        runtime.AtomicStatusReader,
        runtime.ApplicationError,
        runtime.CodexReviewerRenderer,
        runtime.ArtifactError,
        runtime.LocalRuntimeApplication,
        runtime.OpenCodeRenderer,
        runtime.PiReviewerRenderer,
        runtime.StoreError,
        runtime.SubprocessProviderLauncher,
        runtime.WorkspaceError,
        runtime.WriterBusy,
    }
    for value in exported:
        if inspect.isclass(value) and value not in protocols | concrete:
            assert dataclasses.is_dataclass(value) or issubclass(value, (str, ValueError))
    assert not any(path.name in {"journal.py", "executor.py"} for path in PACKAGE.iterdir())
