"""Pure OpenCode argv renderers."""

from __future__ import annotations


_FINDING_INSTRUCTIONS = """

Optional Dogfood Finding: after the complete Report, you may append at most one exact EOF block:
<!-- awf-dogfood-finding-v1
{"kind":"reliability","component":"recovery","summary":"...","observed":"...","expected":"..."}
-->
Use strict JSON with exactly those five keys. kind is bug, reliability, diagnostic, or
usability. component is adapter, artifact, configuration, control_plane, dispatch, node,
postflight, preflight, recovery, routing, or transport. Keep every text value short and
single-line. Never include credentials, URLs, local paths, prompts, environment values,
logs, diffs, or source code. Omit the whole block when there is no safe concrete finding.
"""


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
    instructions += _FINDING_INSTRUCTIONS
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
    instructions += _FINDING_INSTRUCTIONS
    argv += ["--", instructions]
    return argv
