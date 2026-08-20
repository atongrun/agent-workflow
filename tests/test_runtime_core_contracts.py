from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from agent_workflow.runtime import (
    INVOCATION_SPEC_FORMAT,
    RUN_SPEC_FORMAT,
    AuthorizationCommand,
    ContractError,
    HandoffCommand,
    InvocationSpec,
    JournalAuthorization,
    JournalSnapshot,
    LaunchIntent,
    ProcessObservation,
    ProviderSelection,
    ProviderResult,
    RenderedInvocation,
    RunSpec,
    TerminalCommand,
    TerminalOutcome,
    ValidationEffect,
    WorkflowStage,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
GIT_SHA = "d" * 40


def run_spec_mapping() -> dict[str, object]:
    return {
        "format": RUN_SPEC_FORMAT,
        "run_id": "task-example",
        "task_id": "example",
        "task_card": "docs/tasks/example.md",
        "task_card_sha256": SHA_C,
        "repository": "atongrun/example",
        "frozen_base": GIT_SHA,
        "task_branch": "codex/example",
        "state_root_sha256": SHA_A,
        "semantic_contract_sha256": SHA_B,
        "coder": {"provider": "opencode", "model": "coder/model"},
        "reviewer": {"provider": "pi", "model": "reviewer/model"},
        "implement_attempts": 1,
        "review_attempts": 2,
        "rework_budget": 1,
        "implement_route": "task:awf-impl-v3",
        "review_route": "task:awf-review-v3",
        "rework_route": "task:awf-rework-v3",
        "implementation_report": ".awf/artifacts/impl.md",
        "review_report": ".awf/artifacts/review.md",
    }


def invocation_mapping(workspace: Path) -> dict[str, object]:
    return {
        "format": INVOCATION_SPEC_FORMAT,
        "invocation_id": "invoke-example-coder",
        "run_id": "task-example",
        "task_id": "example",
        "authorization_sha256": SHA_C,
        "role": "coder",
        "provider": "opencode",
        "model": "coder/model",
        "workspace": str(workspace),
        "input_path": str(workspace / "input.md"),
        "report_path": str(workspace / "impl.md"),
        "provider_args": ["--model", "coder/model"],
        "environment": {"LANG": "C.UTF-8", "PATH": "/usr/bin"},
    }


def test_run_spec_is_strict_immutable_and_canonical() -> None:
    mapping = run_spec_mapping()
    spec = RunSpec.from_mapping(mapping)
    reordered = RunSpec.from_mapping(dict(reversed(tuple(mapping.items()))))

    assert spec == reordered
    assert spec.canonical_bytes == reordered.canonical_bytes
    assert spec.sha256 == reordered.sha256
    assert len(spec.sha256) == 64
    assert spec.to_mapping() == mapping
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.run_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("run_id",), ""),
        (("task_id",), " task"),
        (("task_card",), "../task.md"),
        (("task_card_sha256",), "a" * 63),
        (("repository",), "repo\nname"),
        (("frozen_base",), "A" * 40),
        (("state_root_sha256",), "f" * 63),
        (("coder", "provider"), "pi"),
        (("implement_attempts",), True),
        (("review_attempts",), 0),
        (("rework_budget",), -1),
        (("implement_route",), ""),
        (("implementation_report",), "/tmp/impl.md"),
        (("review_report",), "../review.md"),
    ],
)
def test_run_spec_rejects_malformed_identity(path: tuple[str, ...], value: object) -> None:
    mapping = run_spec_mapping()
    target: dict[str, object] = mapping
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment,index]
    target[path[-1]] = value
    with pytest.raises(ContractError):
        RunSpec.from_mapping(mapping)


def test_run_spec_rejects_unknown_or_duplicate_report_authority() -> None:
    mapping = run_spec_mapping()
    mapping["unexpected"] = True
    with pytest.raises(ContractError, match="keys mismatch"):
        RunSpec.from_mapping(mapping)

    mapping = run_spec_mapping()
    mapping["review_report"] = mapping["implementation_report"]
    with pytest.raises(ContractError, match="distinct"):
        RunSpec.from_mapping(mapping)

    mapping = run_spec_mapping()
    mapping["review_route"] = mapping["implement_route"]
    with pytest.raises(ContractError, match="routes must be distinct"):
        RunSpec.from_mapping(mapping)


def test_direct_run_spec_requires_typed_provider_selections() -> None:
    mapping = run_spec_mapping()
    spec = RunSpec.from_mapping(mapping)
    assert spec.coder == ProviderSelection("opencode", "coder/model")
    with pytest.raises(ContractError, match="ProviderSelection"):
        dataclasses.replace(
            spec,
            coder={"provider": "opencode", "model": "coder/model"},  # type: ignore[arg-type]
        )


def test_invocation_spec_is_bound_immutable_and_stage_free(tmp_path: Path) -> None:
    mapping = invocation_mapping(tmp_path)
    spec = InvocationSpec.from_mapping(mapping)

    assert spec.provider_args == ("--model", "coder/model")
    assert spec.environment == (("LANG", "C.UTF-8"), ("PATH", "/usr/bin"))
    assert spec.to_mapping() == mapping
    assert len(spec.sha256) == 64
    assert not ({"stage", "attempt", "rework_budget", "run_store", "journal"} & set(mapping))
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.provider = "codex"  # type: ignore[misc]


def test_invocation_spec_rejects_runtime_authority_or_unbound_paths(tmp_path: Path) -> None:
    mapping = invocation_mapping(tmp_path)
    mapping["stage"] = "implement"
    with pytest.raises(ContractError, match="keys mismatch"):
        InvocationSpec.from_mapping(mapping)

    mapping = invocation_mapping(tmp_path)
    mapping["report_path"] = str(tmp_path.parent / "outside.md")
    with pytest.raises(ContractError, match="inside workspace"):
        InvocationSpec.from_mapping(mapping)

    mapping = invocation_mapping(tmp_path)
    mapping["environment"] = {"PROVIDER_TOKEN": "forbidden"}
    with pytest.raises(ContractError, match="credential-bearing"):
        InvocationSpec.from_mapping(mapping)


def test_invocation_spec_rejects_provider_role_drift_and_mutable_direct_values(
    tmp_path: Path,
) -> None:
    mapping = invocation_mapping(tmp_path)
    mapping["provider"] = "pi"
    with pytest.raises(ContractError, match="unsupported for role"):
        InvocationSpec.from_mapping(mapping)

    spec = InvocationSpec.from_mapping(invocation_mapping(tmp_path))
    with pytest.raises(ContractError, match="immutable tuple"):
        dataclasses.replace(spec, provider_args=["--model", "changed"])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="credential-bearing provider argument"):
        dataclasses.replace(spec, provider_args=("--api-token", "forbidden"))
    with pytest.raises(ContractError, match="name/value pairs"):
        dataclasses.replace(spec, environment=(("LANG",),))  # type: ignore[arg-type]


def test_rendered_invocation_is_structured_and_immutable(tmp_path: Path) -> None:
    rendered = RenderedInvocation(
        executable="opencode",
        argv=("run", "--model", "coder/model"),
        cwd=str(tmp_path),
        stdin=b"bounded input",
        environment=(("LANG", "C.UTF-8"),),
    )

    assert rendered.argv[0] == "run"
    with pytest.raises(dataclasses.FrozenInstanceError):
        rendered.cwd = "/changed"  # type: ignore[misc]
    with pytest.raises(ContractError, match="structured token"):
        RenderedInvocation(executable="sh -c", argv=("echo",), cwd=str(tmp_path))
    with pytest.raises(ContractError, match="normalized"):
        RenderedInvocation(
            executable=str(tmp_path / "bin" / ".." / "opencode"),
            argv=("run",),
            cwd=str(tmp_path),
        )
    with pytest.raises(ContractError, match="control"):
        RenderedInvocation(executable="opencode", argv=("bad\narg",), cwd=str(tmp_path))
    with pytest.raises(ContractError, match="immutable tuple"):
        RenderedInvocation(
            executable="opencode",
            argv=["run"],  # type: ignore[arg-type]
            cwd=str(tmp_path),
        )


def test_transition_commands_are_frozen_and_exactly_bound() -> None:
    authorization = AuthorizationCommand(
        run_spec_sha256=SHA_A,
        invocation_id="invoke-example-coder",
        authorization_sha256=SHA_B,
        stage=WorkflowStage.IMPLEMENT,
        role="coder",
        attempt=1,
        delivery_id="delivery-example",
        payload_sha256=SHA_C,
    )
    handoff = HandoffCommand(
        run_spec_sha256=SHA_A,
        source_invocation_id=authorization.invocation_id,
        source_authorization_sha256=authorization.authorization_sha256,
        delivery_id="delivery-review",
        payload_sha256=SHA_C,
        route="task:awf-review-v3",
        target_role="reviewer",
    )
    terminal = TerminalCommand(
        run_spec_sha256=SHA_A,
        source_invocation_id="invoke-example-reviewer",
        source_authorization_sha256=SHA_B,
        delivery_id="delivery-ready",
        payload_sha256=SHA_A,
        outcome=TerminalOutcome.COMPLETED,
        evidence_sha256=SHA_C,
    )

    assert handoff.target_role == "reviewer"
    assert terminal.outcome is TerminalOutcome.COMPLETED
    with pytest.raises(dataclasses.FrozenInstanceError):
        authorization.attempt = 2  # type: ignore[misc]
    with pytest.raises((ContractError, ValueError)):
        dataclasses.replace(authorization, attempt=0)


def test_journal_facts_are_separate_frozen_and_exactly_bound() -> None:
    authorization = JournalAuthorization(
        run_spec_sha256=SHA_A,
        invocation_id="invoke-example-coder",
        authorization_sha256=SHA_B,
        invocation_spec_sha256=SHA_C,
    )
    launch = LaunchIntent(
        authorization_sha256=SHA_B,
        rendered_invocation_sha256=SHA_C,
    )
    process = ProcessObservation(
        authorization_sha256=SHA_B,
        process_identity_sha256=SHA_A,
    )
    result = ProviderResult(
        authorization_sha256=SHA_B,
        process_identity_sha256=SHA_A,
        return_code=0,
        result_sha256=SHA_C,
    )
    effect = ValidationEffect(
        authorization_sha256=SHA_B,
        result_sha256=SHA_C,
        artifact_sha256=SHA_A,
        effect_sha256=SHA_B,
    )
    snapshot = JournalSnapshot(
        run_spec_sha256=authorization.run_spec_sha256,
        invocation_id=authorization.invocation_id,
        authorization_sha256=authorization.authorization_sha256,
        invocation_spec_sha256=authorization.invocation_spec_sha256,
        launch_intent=True,
        process_observed=True,
        result_sha256=result.result_sha256,
        validation_effect_sha256=effect.effect_sha256,
    )

    assert launch.rendered_invocation_sha256 == SHA_C
    assert process.process_identity_sha256 == result.process_identity_sha256
    assert snapshot.validation_effect_sha256 == effect.effect_sha256
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.launch_intent = False  # type: ignore[misc]
    with pytest.raises(ContractError, match="return_code"):
        dataclasses.replace(result, return_code=True)
