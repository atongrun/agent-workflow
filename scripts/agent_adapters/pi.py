"""Pure Pi argv renderers."""

from __future__ import annotations


def render_reviewer_argv(
    *,
    binary: str,
    base: str,
    model: str,
    review_report_path: str,
    context_file: str,
) -> list[str]:
    """Render the Pi reviewer argv without reading files or starting a process."""
    message = (
        f"Review the attached trusted context against base ref `{base}`. "
        "Use only read-only repository inspection tools. "
        "Return the complete filled-in Markdown ReviewReport as stdout. "
        "The trusted runner will persist stdout to the exact ReviewReport path; do not "
        f"claim you wrote a file. ReviewReport output path: {review_report_path}"
    )

    argv = [
        binary,
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
        argv += ["--model", model]
    argv += [f"@{context_file}", message]
    return argv
