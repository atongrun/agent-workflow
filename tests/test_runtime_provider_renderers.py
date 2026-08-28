from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from agent_workflow.operations.agent_adapters.codex import (
    render_reviewer_invocation as legacy_codex_review,
)
from agent_workflow.operations.agent_adapters.opencode import (
    render_executor_argv as legacy_opencode_coder,
)
from agent_workflow.operations.agent_adapters.opencode import (
    render_reviewer_argv as legacy_opencode_review,
)
from agent_workflow.operations.agent_adapters.pi import render_reviewer_argv as legacy_pi_review
from agent_workflow.runtime import (
    ATTACH_INPUT,
    ContractError,
    InvocationSpec,
    RenderedInputFile,
    render_provider_invocation,
)

ROOT = Path(__file__).parents[1]
RENDERERS = ROOT / "src" / "agent_workflow" / "runtime" / "renderers.py"
SHA = "a" * 64
ENVIRONMENT = (("GIT_CONFIG_COUNT", "1"), ("GIT_CONFIG_VALUE_0", ""), ("LANG", "C.UTF-8"))


def invocation_spec(
    workspace: Path,
    *,
    role: str,
    provider: str,
    model: str,
    executable: str,
    input_path: Path,
    input_text: str,
    report_path: Path,
    provider_args: tuple[str, ...] = (),
) -> InvocationSpec:
    return InvocationSpec(
        invocation_id="invoke-example",
        run_id="task-example",
        task_id="example",
        authorization_sha256=SHA,
        role=role,
        provider=provider,
        model=model,
        executable=executable,
        workspace=str(workspace),
        input_path=str(input_path),
        input_text=input_text,
        report_path=str(report_path),
        provider_args=provider_args,
        environment=ENVIRONMENT,
    )


@pytest.mark.parametrize("model", ["", "provider/model"])
def test_opencode_coder_matches_legacy_same_fixture(tmp_path: Path, model: str) -> None:
    card = tmp_path / "task.md"
    report = tmp_path / ".awf" / "impl.md"
    legacy = legacy_opencode_coder(
        binary="opencode-test",
        workspace=str(tmp_path),
        card_file=str(card),
        model=model,
        prompt="implement exactly",
        implementation_report_path=str(report),
        normalized_review_feedback="bounded feedback",
    )
    spec = invocation_spec(
        tmp_path,
        role="coder",
        provider="opencode",
        model=model,
        executable="opencode-test",
        input_path=card,
        input_text=legacy[-1],
        report_path=report,
        provider_args=(ATTACH_INPUT,),
    )

    rendered = render_provider_invocation(spec)

    assert [rendered.executable, *rendered.argv] == legacy
    assert rendered.cwd == str(tmp_path)
    assert rendered.environment == ENVIRONMENT
    assert rendered.stdin is None
    assert rendered.file_inputs == ()


@pytest.mark.parametrize("card_attached", [False, True])
def test_opencode_reviewer_matches_legacy_same_fixture(tmp_path: Path, card_attached: bool) -> None:
    card = tmp_path / "task.md"
    report = tmp_path / ".awf" / "review.md"
    legacy = legacy_opencode_review(
        binary="opencode-test",
        workspace=str(tmp_path),
        card_file=str(card) if card_attached else "",
        model="provider/model",
        prompt="review exactly",
        review_report_path=str(report),
    )
    spec = invocation_spec(
        tmp_path,
        role="reviewer",
        provider="opencode",
        model="provider/model",
        executable="opencode-test",
        input_path=card if card_attached else report,
        input_text=legacy[-1],
        report_path=report,
        provider_args=(ATTACH_INPUT,) if card_attached else (),
    )

    rendered = render_provider_invocation(spec)

    assert [rendered.executable, *rendered.argv] == legacy
    assert rendered.stdin is None
    assert rendered.file_inputs == ()


@pytest.mark.parametrize("mode", [("milestone-next",), ("terminal-decision",)])
def test_opencode_architect_closed_modes_materialize_trusted_context(
    tmp_path: Path, mode: tuple[str, ...]
) -> None:
    context_path = tmp_path / ".awf" / "architect-context.md"
    context = "trusted Architect facts\n"
    rendered = render_provider_invocation(
        invocation_spec(
            tmp_path,
            role="architect",
            provider="opencode",
            model="provider/model",
            executable="opencode-test",
            input_path=context_path,
            input_text=context,
            report_path=tmp_path / ".awf" / "architect-result.md",
            provider_args=mode,
        )
    )

    assert rendered.argv[rendered.argv.index("-f") + 1] == str(context_path)
    assert rendered.file_inputs == (RenderedInputFile(str(context_path), context.encode("utf-8")),)


def test_codex_reviewer_matches_legacy_argv_and_stdin(tmp_path: Path) -> None:
    card = tmp_path / "task.md"
    report = tmp_path / ".awf" / "review.md"
    legacy_argv, legacy_stdin = legacy_codex_review(
        binary="codex-test",
        workspace=str(tmp_path),
        base="base-sha",
        model="provider/model",
        review_report_path=str(report),
        prompt="review exactly",
        review_report_template="# ReviewReport\n",
        card_text="# TaskCard\n",
    )
    spec = invocation_spec(
        tmp_path,
        role="reviewer",
        provider="codex",
        model="provider/model",
        executable="codex-test",
        input_path=card,
        input_text=legacy_stdin,
        report_path=report,
    )

    rendered = render_provider_invocation(spec)

    assert [rendered.executable, *rendered.argv] == legacy_argv
    assert rendered.stdin == legacy_stdin.encode("utf-8")
    assert rendered.file_inputs == ()


def test_pi_reviewer_matches_legacy_with_frozen_workspace_path_substitution(
    tmp_path: Path,
) -> None:
    context_path = tmp_path / ".awf" / "pi-review-context.md"
    report = tmp_path / ".awf" / "review.md"
    legacy = legacy_pi_review(
        binary="pi-test",
        base="base-sha",
        model="provider/model",
        review_report_path=str(report),
        context_file=str(context_path),
    )
    context = "trusted UTF-8 context\n"
    spec = invocation_spec(
        tmp_path,
        role="reviewer",
        provider="pi",
        model="provider/model",
        executable="pi-test",
        input_path=context_path,
        input_text=context,
        report_path=report,
        provider_args=("base-sha",),
    )

    rendered = render_provider_invocation(spec)

    assert [rendered.executable, *rendered.argv] == legacy
    assert rendered.stdin is None
    assert len(rendered.file_inputs) == 1
    assert rendered.file_inputs[0].path == str(context_path)
    assert rendered.file_inputs[0].content == context.encode("utf-8")
    default_rendered = render_provider_invocation(dataclasses.replace(spec, model=""))
    assert "--model" not in default_rendered.argv


def test_pi_reviewer_finding_prompt_requires_explicit_bound_environment(tmp_path: Path) -> None:
    context_path = tmp_path / ".awf" / "pi-review-context.md"
    report = tmp_path / ".awf" / "review.md"
    spec = invocation_spec(
        tmp_path,
        role="reviewer",
        provider="pi",
        model="",
        executable="pi-test",
        input_path=context_path,
        input_text="trusted context\n",
        report_path=report,
        provider_args=("base-sha",),
    )

    default_rendered = render_provider_invocation(spec)
    enabled_rendered = render_provider_invocation(
        dataclasses.replace(
            spec,
            environment=tuple(sorted((*ENVIRONMENT, ("AWF_FINDING_ENABLED", "1")))),
        )
    )

    assert all("awf-dogfood-finding" not in token for token in default_rendered.argv)
    assert any("awf-dogfood-finding" in token for token in enabled_rendered.argv)


def test_pi_architect_is_a_real_read_only_renderer(tmp_path: Path) -> None:
    context_path = tmp_path / ".awf" / "pi-architect-context.md"
    taskcard_path = tmp_path / "docs" / "tasks" / "planned-task.md"
    context = "trusted project and milestone context\n"
    spec = invocation_spec(
        tmp_path,
        role="architect",
        provider="pi",
        model="provider/model",
        executable="pi-test",
        input_path=context_path,
        input_text=context,
        report_path=taskcard_path,
    )

    rendered = render_provider_invocation(spec)

    assert rendered.executable == "pi-test"
    assert rendered.cwd == str(tmp_path)
    assert "read,grep,find,ls" in rendered.argv
    assert "--no-approve" in rendered.argv
    assert "--model" in rendered.argv
    assert all("awf-dogfood-finding" not in token for token in rendered.argv)
    assert rendered.file_inputs[0].path == str(context_path)
    assert rendered.file_inputs[0].content == context.encode("utf-8")
    default_rendered = render_provider_invocation(dataclasses.replace(spec, model=""))
    assert "--model" not in default_rendered.argv


def test_pi_architect_terminal_decision_is_fresh_read_only_closed_mode(tmp_path: Path) -> None:
    context_path = tmp_path / ".awf" / "terminal-context.md"
    report = tmp_path / ".awf" / "decision.md"
    spec = invocation_spec(
        tmp_path,
        role="architect",
        provider="pi",
        model="",
        executable="pi-test",
        input_path=context_path,
        input_text="trusted terminal facts\n",
        report_path=report,
        provider_args=("terminal-decision",),
    )

    rendered = render_provider_invocation(spec)

    assert "--no-session" in rendered.argv
    assert "--no-approve" in rendered.argv
    assert any("exactly one closed verdict" in token for token in rendered.argv)
    assert all("TaskCard Markdown" not in token for token in rendered.argv)


def test_pi_architect_milestone_next_is_fresh_read_only_closed_mode(tmp_path: Path) -> None:
    context_path = tmp_path / ".awf" / "next-context.md"
    report = tmp_path / ".awf" / "next.md"
    spec = invocation_spec(
        tmp_path,
        role="architect",
        provider="pi",
        model="provider/model",
        executable="pi-test",
        input_path=context_path,
        input_text="trusted next facts\n",
        report_path=report,
        provider_args=("milestone-next",),
    )

    rendered = render_provider_invocation(spec)

    assert "--no-session" in rendered.argv
    assert "--no-approve" in rendered.argv
    assert any("MILESTONE_COMPLETE" in token for token in rendered.argv)
    assert any("reason silently" in token for token in rendered.argv)
    assert any("task_id, objective, scope, change_paths" in token for token in rendered.argv)
    assert not any("raw Markdown" in token for token in rendered.argv)
    assert any("pre-generate later cards" in token for token in rendered.argv)
    assert all("terminal decision" not in token.lower() for token in rendered.argv)


def test_invocation_and_rendered_identity_drift_with_every_process_input(tmp_path: Path) -> None:
    context = tmp_path / ".awf" / "pi-review-context.md"
    report = tmp_path / ".awf" / "review.md"
    spec = invocation_spec(
        tmp_path,
        role="reviewer",
        provider="pi",
        model="provider/model",
        executable="pi-test",
        input_path=context,
        input_text="trusted context\n",
        report_path=report,
        provider_args=("base-sha",),
    )
    rendered = render_provider_invocation(spec)

    spec_drifts = (
        dataclasses.replace(spec, invocation_id="invoke-other"),
        dataclasses.replace(spec, run_id="task-other"),
        dataclasses.replace(spec, task_id="other"),
        dataclasses.replace(spec, authorization_sha256="b" * 64),
        dataclasses.replace(spec, provider="opencode"),
        dataclasses.replace(spec, executable="pi-other"),
        dataclasses.replace(spec, model="other/model"),
        dataclasses.replace(spec, input_path=str(tmp_path / ".awf" / "other.md")),
        dataclasses.replace(spec, input_text="different context\n"),
        dataclasses.replace(spec, report_path=str(tmp_path / ".awf" / "other-report.md")),
        dataclasses.replace(spec, provider_args=("other-base",)),
        dataclasses.replace(spec, environment=(("LANG", "en_US.UTF-8"),)),
    )
    assert all(changed.sha256 != spec.sha256 for changed in spec_drifts)

    content_drift = render_provider_invocation(
        dataclasses.replace(spec, input_text="different context\n")
    )
    path_drift = render_provider_invocation(
        dataclasses.replace(spec, input_path=str(tmp_path / ".awf" / "other.md"))
    )
    assert content_drift.sha256 != rendered.sha256
    assert path_drift.sha256 != rendered.sha256
    for index, token in enumerate(rendered.argv):
        changed_argv = list(rendered.argv)
        changed_argv[index] = token + "-drift"
        assert dataclasses.replace(rendered, argv=tuple(changed_argv)).sha256 != rendered.sha256


def test_closed_dispatch_rejects_unsupported_selection_or_options(tmp_path: Path) -> None:
    report = tmp_path / ".awf" / "report.md"
    common = {
        "model": "",
        "executable": "provider",
        "input_path": report,
        "input_text": "bounded input",
        "report_path": report,
    }
    coder = render_provider_invocation(
        invocation_spec(tmp_path, role="coder", provider="codex", **common)
    )
    assert "workspace-write" in coder.argv
    architect = render_provider_invocation(
        invocation_spec(tmp_path, role="architect", provider="opencode", **common)
    )
    assert "task_id" in architect.argv[-1]
    with pytest.raises(ContractError, match="options are invalid"):
        render_provider_invocation(
            invocation_spec(
                tmp_path,
                role="reviewer",
                provider="opencode",
                provider_args=("unexpected",),
                **common,
            )
        )
    with pytest.raises(ContractError, match="one exact base ref"):
        render_provider_invocation(
            invocation_spec(tmp_path, role="reviewer", provider="pi", **common)
        )
    with pytest.raises(ContractError, match="environment must be explicitly bound"):
        render_provider_invocation(
            dataclasses.replace(
                invocation_spec(
                    tmp_path,
                    role="reviewer",
                    provider="codex",
                    **common,
                ),
                environment=(),
            )
        )


@pytest.mark.parametrize(
    ("provider", "role", "provider_args", "expected"),
    [
        ("opencode", "architect", (), "task_id"),
        ("opencode", "coder", (ATTACH_INPUT,), "run"),
        ("opencode", "reviewer", (), "run"),
        ("codex", "architect", (), "task_id"),
        ("codex", "coder", (), "workspace-write"),
        ("codex", "reviewer", (), "read-only"),
        ("pi", "architect", (), "task_id"),
        ("pi", "coder", (), "read,grep,find,ls,edit,write"),
        ("pi", "reviewer", ("base-sha",), "read,grep,find,ls"),
    ],
)
def test_all_provider_role_cells_have_closed_renderer(
    tmp_path: Path,
    provider: str,
    role: str,
    provider_args: tuple[str, ...],
    expected: str,
) -> None:
    report = tmp_path / ".awf" / "report.md"
    rendered = render_provider_invocation(
        invocation_spec(
            tmp_path,
            role=role,
            provider=provider,
            model="provider/model",
            executable=f"{provider}-test",
            input_path=tmp_path / "task.md",
            input_text="trusted input",
            report_path=report,
            provider_args=provider_args,
        )
    )

    assert rendered.environment == ENVIRONMENT
    rendered_text = " ".join(rendered.argv)
    if rendered.stdin:
        rendered_text += " " + rendered.stdin.decode("utf-8")
    assert expected in rendered_text


@pytest.mark.parametrize("provider", ["pi", "opencode", "codex"])
@pytest.mark.parametrize("provider_args", [(), ("milestone-next",)])
def test_all_architect_renderers_request_closed_semantic_json(
    tmp_path: Path, provider: str, provider_args: tuple[str, ...]
) -> None:
    report = tmp_path / ".awf" / "architect.json"
    rendered = render_provider_invocation(
        invocation_spec(
            tmp_path,
            role="architect",
            provider=provider,
            model="",
            executable=f"{provider}-test",
            input_path=tmp_path / "context.md",
            input_text="trusted context",
            report_path=report,
            provider_args=provider_args,
        )
    )
    prompt = rendered.stdin.decode("utf-8") if rendered.stdin else rendered.argv[-1]

    assert "task_id, objective, scope, change_paths, constraints, acceptance_criteria" in prompt
    assert "complete self-contained TaskCard" not in prompt


def test_renderer_module_is_pure_and_has_no_dynamic_registry() -> None:
    source = RENDERERS.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RENDERERS))
    forbidden_imports = {"os", "subprocess", "socket", "urllib", "requests"}
    forbidden_calls = {
        "open",
        "spawn",
        "run",
        "Popen",
        "send_event",
        "getenv",
        "environ",
        "entry_points",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".", 1)[0] not in forbidden_imports for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".", 1)[0] not in forbidden_imports
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls

    assert "registry" not in source.casefold()
    assert "plugin" not in source.casefold()
