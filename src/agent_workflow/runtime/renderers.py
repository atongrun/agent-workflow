"""Closed, pure renderers for the evidenced provider CLI surfaces."""

from __future__ import annotations

from .contracts import ContractError, InvocationSpec, RenderedInputFile, RenderedInvocation

CODEX_FINDING_INSTRUCTIONS = """

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

OPENCODE_FINDING_INSTRUCTIONS = CODEX_FINDING_INSTRUCTIONS

PI_FINDING_INSTRUCTIONS = """

Optionally append at most one exact EOF Dogfood Finding block after the complete Report:
<!-- awf-dogfood-finding-v1
{"kind":"reliability","component":"recovery","summary":"...","observed":"...","expected":"..."}
-->
Use exactly those keys and short single-line values. Never include credentials, URLs,
local paths, prompts, environment values, logs, diffs, or source code. kind is bug,
reliability, diagnostic, or usability. component is adapter, artifact, configuration,
control_plane, dispatch, node, postflight, preflight, recovery, routing, or transport.
Omit the block when there is no safe concrete finding.
"""

ATTACH_INPUT = "attach-input"


def _require(spec: InvocationSpec, provider: str, roles: set[str]) -> None:
    if spec.provider != provider or spec.role not in roles:
        raise ContractError(f"{provider} renderer does not own this provider/role selection")
    if not spec.environment:
        raise ContractError("provider environment must be explicitly bound")


class OpenCodeRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "opencode", {"coder", "reviewer"})
        allowed = {(ATTACH_INPUT,)} if spec.role == "coder" else {(), (ATTACH_INPUT,)}
        if spec.provider_args not in allowed:
            raise ContractError("OpenCode provider options are invalid")
        argv = ["run", "--dir", spec.workspace]
        if spec.provider_args:
            argv += ["-f", spec.input_path]
        if spec.model:
            argv += ["-m", spec.model]
        argv += ["--", spec.input_text]
        return RenderedInvocation(
            spec.executable,
            tuple(argv),
            spec.workspace,
            environment=spec.environment,
        )


class CodexReviewerRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "codex", {"reviewer"})
        if spec.provider_args:
            raise ContractError("Codex reviewer does not accept provider options")
        argv = [
            "exec",
            "-C",
            spec.workspace,
            "--sandbox",
            "read-only",
            "--output-last-message",
            spec.report_path,
        ]
        if spec.model:
            argv += ["--model", spec.model]
        argv += ["-"]
        return RenderedInvocation(
            spec.executable,
            tuple(argv),
            spec.workspace,
            stdin=spec.input_text.encode("utf-8"),
            environment=spec.environment,
        )


class PiReviewerRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "pi", {"reviewer"})
        if len(spec.provider_args) != 1:
            raise ContractError("Pi reviewer requires one exact base ref")
        base = spec.provider_args[0]
        message = (
            f"Review the attached trusted context against base ref `{base}`. "
            "Use only read-only repository inspection tools. "
            "Return the complete filled-in Markdown ReviewReport as stdout. "
            "The trusted runner will persist stdout to the exact ReviewReport path; do not "
            f"claim you wrote a file. ReviewReport output path: {spec.report_path}"
            + PI_FINDING_INSTRUCTIONS
        )
        argv = [
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
        if spec.model:
            argv += ["--model", spec.model]
        argv += [f"@{spec.input_path}", message]
        return RenderedInvocation(
            spec.executable,
            tuple(argv),
            spec.workspace,
            environment=spec.environment,
            file_inputs=(RenderedInputFile(spec.input_path, spec.input_text.encode("utf-8")),),
        )


def render_provider_invocation(spec: InvocationSpec) -> RenderedInvocation:
    if spec.provider == "opencode":
        return OpenCodeRenderer().render(spec)
    if spec.provider == "codex" and spec.role == "reviewer":
        return CodexReviewerRenderer().render(spec)
    if spec.provider == "pi" and spec.role == "reviewer":
        return PiReviewerRenderer().render(spec)
    raise ContractError("no installed renderer owns this provider/role selection")
