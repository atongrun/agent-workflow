from __future__ import annotations

import itertools

import pytest

from agent_workflow.operations.agent_adapters.codex import (
    _FINDING_INSTRUCTIONS as CODEX_FINDING_INSTRUCTIONS,
)
from agent_workflow.operations.agent_adapters.codex import render_reviewer_invocation
from agent_workflow.operations.agent_adapters.opencode import (
    _FINDING_INSTRUCTIONS as OPENCODE_FINDING_INSTRUCTIONS,
)
from agent_workflow.operations.agent_adapters.opencode import (
    render_executor_argv,
    render_reviewer_argv,
)
from agent_workflow.operations.agent_adapters.pi import (
    _FINDING_INSTRUCTIONS as PI_FINDING_INSTRUCTIONS,
)
from agent_workflow.operations.agent_adapters.pi import (
    render_reviewer_argv as render_pi_reviewer_argv,
)


@pytest.mark.parametrize(
    ("model", "normalized_feedback"),
    list(itertools.product(("", "provider/model"), ("", '{"verdict": "REQUEST_CHANGES"}'))),
)
def test_render_opencode_executor_argv_is_exact(model, normalized_feedback):
    report_path = ".awf/artifacts/impl-report-task.md"
    argv = render_executor_argv(
        binary="opencode-test",
        workspace="/workspace",
        card_file="/workspace/task.md",
        model=model,
        prompt="executor instructions",
        implementation_report_path=report_path,
        normalized_review_feedback=normalized_feedback,
    )

    expected = [
        "opencode-test",
        "run",
        "--dir",
        "/workspace",
        "-f",
        "/workspace/task.md",
    ]
    if model:
        expected += ["-m", model]
    instructions = (
        "executor instructions"
        f"\n\nWrite the complete ImplementationReport to exactly: {report_path}\n"
    )
    if normalized_feedback:
        instructions += (
            "\n\n--- Structured reviewer feedback to correct ---\n\n" + normalized_feedback
        )
    expected += ["--", instructions]

    assert argv == expected


def test_render_opencode_executor_preserves_windows_workspace_and_report_path():
    workspace = r"C:\Agent Workspaces\task one"
    report_path = ".awf/artifacts/impl-report-task-one.md"

    argv = render_executor_argv(
        binary=r"C:\Program Files\OpenCode\opencode.exe",
        workspace=workspace,
        card_file=workspace + r"\docs\task.md",
        model="provider/model",
        prompt="executor instructions",
        implementation_report_path=report_path,
    )

    assert argv[0] == r"C:\Program Files\OpenCode\opencode.exe"
    assert argv[argv.index("--dir") + 1] == workspace
    assert len(argv) == 10
    assert argv[-2] == "--"
    assert f"Write the complete ImplementationReport to exactly: {report_path}\n" in argv[-1]
    assert "<!-- awf-dogfood-finding-v1" not in argv[-1]
    assert " " in argv[0] and " " in argv[argv.index("--dir") + 1]


@pytest.mark.parametrize(
    ("model", "card_file"),
    list(itertools.product(("", "provider/model"), ("", "/workspace/task.md"))),
)
def test_render_opencode_reviewer_argv_is_exact(model, card_file):
    argv = render_reviewer_argv(
        binary="opencode-test",
        workspace="/workspace",
        card_file=card_file,
        model=model,
        prompt="review instructions",
        review_report_path=".awf/review.md",
    )

    expected = ["opencode-test", "run", "--dir", "/workspace"]
    if card_file:
        expected += ["-f", card_file]
    if model:
        expected += ["-m", model]
    expected += [
        "--",
        "review instructions\n\nWrite the complete ReviewReport to exactly: .awf/review.md\n",
    ]

    assert argv == expected


@pytest.mark.parametrize(
    ("model", "card_text"),
    list(itertools.product(("", "provider/model"), ("", "# TaskCard\n"))),
)
def test_render_codex_reviewer_invocation_is_exact(model, card_text):
    argv, stdin = render_reviewer_invocation(
        binary="codex-test",
        workspace="/workspace",
        base="main",
        model=model,
        review_report_path=".awf/review.md",
        prompt="review instructions",
        review_report_template="# ReviewReport template\n",
        card_text=card_text,
    )

    expected_argv = [
        "codex-test",
        "exec",
        "-C",
        "/workspace",
        "--sandbox",
        "read-only",
        "--output-last-message",
        ".awf/review.md",
    ]
    if model:
        expected_argv += ["--model", model]
    expected_argv += ["-"]
    expected_stdin = (
        "review instructions"
        "\n\nReview the committed branch diff against the base ref `main`. "
        "Use Git read-only commands to inspect that exact comparison."
        "\n\nYour final response is persisted verbatim as the ReviewReport. "
        "Return the complete filled-in Markdown report itself; do not merely summarize "
        "the verdict or say that you wrote a file."
        "\n\nReviewReport output path: .awf/review.md\n"
        "\n--- Required ReviewReport template ---\n\n# ReviewReport template\n"
    )
    if card_text:
        expected_stdin += "\n\n--- TaskCard (acceptance criteria to verify) ---\n\n" + card_text

    assert argv == expected_argv
    assert stdin == expected_stdin


@pytest.mark.parametrize("model", ["", "provider/model"])
def test_render_pi_reviewer_argv_is_exact(model):
    argv = render_pi_reviewer_argv(
        binary="pi-test",
        base="main",
        model=model,
        review_report_path=".awf/review.md",
        context_file="/state/pi-review-context.md",
    )

    message = (
        "Review the attached trusted context against base ref `main`. "
        "Use only read-only repository inspection tools. "
        "Return the complete filled-in Markdown ReviewReport as stdout. "
        "The trusted runner will persist stdout to the exact ReviewReport path; do not "
        "claim you wrote a file. ReviewReport output path: .awf/review.md"
    )
    expected = [
        "pi-test",
        "--print",
        "--mode",
        "text",
        "--no-session",
        "--no-approve",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
        "--tools",
        "read,grep,find,ls",
    ]
    if model:
        expected += ["--model", model]
    expected += ["@/state/pi-review-context.md", message]

    assert argv == expected


def test_finding_prompt_is_available_only_with_explicit_maintainer_opt_in():
    opencode = render_executor_argv(
        binary="opencode",
        workspace="/workspace",
        card_file="/workspace/task.md",
        model="",
        prompt="implement",
        implementation_report_path=".awf/impl.md",
        finding_enabled=True,
    )
    codex_argv, codex_stdin = render_reviewer_invocation(
        binary="codex",
        workspace="/workspace",
        base="main",
        model="",
        review_report_path=".awf/review.md",
        prompt="review",
        review_report_template="# Review\n",
        finding_enabled=True,
    )
    pi = render_pi_reviewer_argv(
        binary="pi",
        base="main",
        model="",
        review_report_path=".awf/review.md",
        context_file="/workspace/context.md",
        finding_enabled=True,
    )

    assert OPENCODE_FINDING_INSTRUCTIONS in opencode[-1]
    assert codex_argv[0] == "codex"
    assert CODEX_FINDING_INSTRUCTIONS in codex_stdin
    assert any(PI_FINDING_INSTRUCTIONS in token for token in pi)
