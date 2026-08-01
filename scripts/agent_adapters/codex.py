"""Pure Codex invocation renderers."""

from __future__ import annotations


def render_reviewer_invocation(
    *,
    binary: str,
    workspace: str,
    base: str,
    model: str,
    review_report_path: str,
    prompt: str,
    review_report_template: str,
    card_text: str = "",
) -> tuple[list[str], str]:
    """Render Codex reviewer argv and stdin without reading files or starting a process."""
    argv = [
        binary,
        "exec",
        "-C",
        workspace,
        "--sandbox",
        "read-only",
        "--output-last-message",
        review_report_path,
    ]
    if model:
        argv += ["--model", model]
    argv += ["-"]

    stdin = prompt
    stdin += (
        f"\n\nReview the committed branch diff against the base ref `{base}`. "
        "Use Git read-only commands to inspect that exact comparison."
    )
    stdin += (
        "\n\nYour final response is persisted verbatim as the ReviewReport. "
        "Return the complete filled-in Markdown report itself; do not merely summarize "
        "the verdict or say that you wrote a file."
        f"\n\nReviewReport output path: {review_report_path}\n"
        "\n--- Required ReviewReport template ---\n\n" + review_report_template
    )
    if card_text:
        stdin += "\n\n--- TaskCard (acceptance criteria to verify) ---\n\n" + card_text
    return argv, stdin
