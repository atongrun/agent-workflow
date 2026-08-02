"""Pure OpenCode argv renderers."""

from __future__ import annotations


def render_executor_argv(
    *,
    binary: str,
    workspace: str,
    card_file: str,
    model: str,
    prompt: str,
    implementation_report_path: str,
    normalized_review_feedback: str = "",
) -> list[str]:
    """Render the OpenCode executor argv without reading files or starting a process."""
    argv = [binary, "run", "--dir", workspace, "-f", card_file]
    if model:
        argv += ["-m", model]
    instructions = prompt
    instructions += (
        f"\n\nWrite the complete ImplementationReport to exactly: {implementation_report_path}\n"
    )
    if normalized_review_feedback:
        instructions += "\n\n--- Structured reviewer feedback to correct ---\n\n"
        instructions += normalized_review_feedback
    argv += ["--", instructions]
    return argv


def render_reviewer_argv(
    *,
    binary: str,
    workspace: str,
    card_file: str,
    model: str,
    prompt: str,
    review_report_path: str,
) -> list[str]:
    """Render the OpenCode reviewer argv without reading files or starting a process."""
    argv = [binary, "run", "--dir", workspace]
    if card_file:
        argv += ["-f", card_file]
    if model:
        argv += ["-m", model]
    instructions = prompt
    instructions += f"\n\nWrite the complete ReviewReport to exactly: {review_report_path}\n"
    argv += ["--", instructions]
    return argv
