"""Pure Codex invocation renderers."""

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
    finding_enabled: bool = False,
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
    if finding_enabled:
        stdin += _FINDING_INSTRUCTIONS
    if card_text:
        stdin += "\n\n--- TaskCard (acceptance criteria to verify) ---\n\n" + card_text
    return argv, stdin
