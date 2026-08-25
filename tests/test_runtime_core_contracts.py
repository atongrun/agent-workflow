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
    ProviderResult,
    ProviderSelection,
    RenderedInputFile,
    RenderedInvocation,
    RunSpec,
    StopCommand,
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
        "executable": "opencode",
        "workspace": str(workspace),
        "input_path": str(workspace / "input.md"),
        "input_text": "bounded provider input\n",
        "report_path": str(workspace / "impl.md"),
        "provider_args": ["attach-input"],
        "environment": {
            "GIT_CONFIG_VALUE_0": "",
            "LANG": "C.UTF-8",
            "PATH": "/usr/bin",
            "ProgramFiles(x86)": "C:\\Program Files (x86)",
        },
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

    assert spec.provider_args == ("attach-input",)
    assert spec.environment == (
        ("GIT_CONFIG_VALUE_0", ""),
        ("LANG", "C.UTF-8"),
        ("PATH", "/usr/bin"),
        ("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    )
    assert spec.to_mapping() == mapping
    assert len(spec.sha256) == 64
    assert not ({"stage", "attempt", "rework_budget", "run_store", "journal"} & set(mapping))
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.provider = "codex"  # type: ignore[misc]

    relative_report = InvocationSpec.from_mapping({**mapping, "report_path": ".awf/impl.md"})
    assert relative_report.report_path == ".awf/impl.md"


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

    mapping = invocation_mapping(tmp_path)
    mapping["environment"] = {"LANG": "bad\0value"}
    with pytest.raises(ContractError, match="NUL"):
        InvocationSpec.from_mapping(mapping)

    mapping = invocation_mapping(tmp_path)
    mapping["environment"] = {f"VALUE_{index}": "x" for index in range(257)}
    with pytest.raises(ContractError, match="too many"):
        InvocationSpec.from_mapping(mapping)

    mapping = invocation_mapping(tmp_path)
    mapping["input_text"] = " \n\t"
    with pytest.raises(ContractError, match="nonblank"):
        InvocationSpec.from_mapping(mapping)

    mapping = invocation_mapping(tmp_path)
    mapping["input_text"] = "x" * (256 * 1024 + 1)
    with pytest.raises(ContractError, match="input bound"):
        InvocationSpec.from_mapping(mapping)


def test_invocation_spec_rejects_provider_role_drift_and_mutable_direct_values(
    tmp_path: Path,
) -> None:
    mapping = invocation_mapping(tmp_path)
    mapping["provider"] = "unknown"
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
    input_file = RenderedInputFile(str(tmp_path / "input.md"), b"file input")
    rendered = RenderedInvocation(
        executable="opencode",
        argv=("run", "--model", "coder/model"),
        cwd=str(tmp_path),
        stdin=b"bounded input",
        environment=(("LANG", "C.UTF-8"),),
        file_inputs=(input_file,),
    )

    assert rendered.argv[0] == "run"
    assert rendered == dataclasses.replace(rendered)
    assert rendered.canonical_bytes == dataclasses.replace(rendered).canonical_bytes
    assert rendered.sha256 == dataclasses.replace(rendered).sha256
    assert len(rendered.sha256) == 64
    for changed in (
        dataclasses.replace(rendered, executable="codex"),
        dataclasses.replace(rendered, argv=("run", "--quiet")),
        dataclasses.replace(
            rendered,
            cwd=str(tmp_path / "other"),
            file_inputs=(RenderedInputFile(str(tmp_path / "other" / "input.md"), b"file input"),),
        ),
        dataclasses.replace(rendered, stdin=b"different input"),
        dataclasses.replace(rendered, environment=(("LANG", "en_US.UTF-8"),)),
        dataclasses.replace(
            rendered,
            file_inputs=(RenderedInputFile(str(tmp_path / "input.md"), b"different input"),),
        ),
        dataclasses.replace(
            rendered,
            file_inputs=(RenderedInputFile(str(tmp_path / "different.md"), b"file input"),),
        ),
    ):
        assert changed.sha256 != rendered.sha256
    assert rendered.to_mapping()["stdin"] == {
        "sha256": "901e6053aa8c678a9ea555c0225237affac98329538280b6917544b9f61b07c6",
        "length": 13,
    }
    assert rendered.to_mapping()["file_inputs"] == [
        {
            "path": str(tmp_path / "input.md"),
            "sha256": "a281bfde713d0dc4f126ba63e7702ab573609fe8dabcc08fd5e3ec6cff4a32d8",
            "length": 10,
        }
    ]
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
    multiline = RenderedInvocation(
        executable="opencode",
        argv=("bounded\nprovider input",),
        cwd=str(tmp_path),
    )
    assert multiline.argv == ("bounded\nprovider input",)
    with pytest.raises(ContractError, match="control"):
        RenderedInvocation(executable="opencode", argv=("bad\0arg",), cwd=str(tmp_path))
    with pytest.raises(ContractError, match="immutable tuple"):
        RenderedInvocation(
            executable="opencode",
            argv=["run"],  # type: ignore[arg-type]
            cwd=str(tmp_path),
        )
    with pytest.raises(ContractError, match="inside cwd"):
        RenderedInvocation(
            executable="opencode",
            argv=("run",),
            cwd=str(tmp_path),
            file_inputs=(RenderedInputFile(str(tmp_path.parent / "outside.md"), b"input"),),
        )
    with pytest.raises(ContractError, match="bounded immutable bytes"):
        RenderedInvocation(
            executable="codex",
            argv=("exec",),
            cwd=str(tmp_path),
            stdin=b"x" * (256 * 1024 + 1),
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

    stop = StopCommand(SHA_A, "run-example", 7)
    assert stop.expected_sequence == 7
    with pytest.raises(ContractError):
        StopCommand(SHA_A, "run-example", -1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        authorization.attempt = 2  # type: ignore[misc]
    with pytest.raises((ContractError, ValueError)):
        dataclasses.replace(authorization, attempt=0)


def test_journal_facts_are_separate_frozen_and_exactly_bound() -> None:
    rendered = RenderedInvocation(
        executable="opencode",
        argv=("run",),
        cwd=str(Path.cwd()),
        stdin=b"bounded input",
    )
    authorization = JournalAuthorization(
        run_spec_sha256=SHA_A,
        invocation_id="invoke-example-coder",
        authorization_sha256=SHA_B,
        invocation_spec_sha256=SHA_C,
    )
    launch = LaunchIntent(
        authorization_sha256=SHA_B,
        rendered_invocation_sha256=rendered.sha256,
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
        workspace_manifest_sha256=authorization.workspace_manifest_sha256,
        launch_intent=launch,
        process_observation=process,
        result=result,
        validation_effect=effect,
    )

    assert launch.rendered_invocation_sha256 == rendered.sha256
    assert process.process_identity_sha256 == result.process_identity_sha256
    assert snapshot.validation_effect == effect
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.launch_intent = None  # type: ignore[misc]
    with pytest.raises(ContractError, match="return_code"):
        dataclasses.replace(result, return_code=True)
