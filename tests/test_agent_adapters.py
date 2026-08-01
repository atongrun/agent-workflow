from __future__ import annotations

import itertools

import pytest

from scripts.agent_adapters.codex import render_reviewer_invocation
from scripts.agent_adapters.opencode import render_executor_argv, render_reviewer_argv


@pytest.mark.parametrize(
    ("model", "normalized_feedback"),
    list(itertools.product(("", "provider/model"), ("", '{"verdict": "REQUEST_CHANGES"}'))),
)
def test_render_opencode_executor_argv_is_exact(model, normalized_feedback):
    argv = render_executor_argv(
        binary="opencode-test",
        workspace="/workspace",
        card_file="/workspace/task.md",
        model=model,
        prompt="executor instructions",
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
    instructions = "executor instructions"
    if normalized_feedback:
        instructions += (
            "\n\n--- Structured reviewer feedback to correct ---\n\n" + normalized_feedback
        )
    expected += ["--", instructions]

    assert argv == expected


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
