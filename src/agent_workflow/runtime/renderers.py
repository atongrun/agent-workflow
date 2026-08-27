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


def _architect_instruction(mode: tuple[str, ...]) -> str:
    if mode == ():
        return (
            "Return stdout as exactly one JSON object with exactly these keys: task_id, objective, "
            "scope, change_paths, constraints, acceptance_criteria, verification_commands. "
            "task_id and objective are strings. scope, change_paths, constraints, and "
            "acceptance_criteria are non-empty arrays of strings. verification_commands is a "
            "non-empty array of non-empty argv string arrays. "
            "Return no Markdown fence, explanation, "
            "AWF metadata, branch, SHA, role selection, artifact path, or protocol comment."
        )
    if mode == ("terminal-decision",):
        return (
            "Return only the complete closed Architect Decision with verdict approve, "
            "request_changes, reject, or escalate. Do not edit, merge, or invent rework."
        )
    if mode == ("milestone-next",):
        return (
            "If Plan work remains, return the next task as exactly one JSON object with exactly "
            "these keys: task_id, objective, scope, change_paths, constraints, "
            "acceptance_criteria, verification_commands. task_id and objective are strings. "
            "scope, change_paths, constraints, and acceptance_criteria are non-empty arrays of "
            "strings. verification_commands is a non-empty array of non-empty argv string arrays. "
            "If the Plan is complete, return only MILESTONE_COMPLETE. If blocked, return BLOCKED "
            "on the first line and one non-empty reason on following lines. Do not edit, dispatch, "
            "merge, pre-generate later cards, or emit Markdown TaskCard authority facts."
        )
    raise ContractError("Architect mode is unsupported")


def _opencode_architect_instruction(mode: tuple[str, ...]) -> str:
    semantic = (
        "Return stdout as exactly one JSON object with exactly these keys: task_id, objective, "
        "scope, change_paths, constraints, acceptance_criteria, verification_commands. "
        "task_id and objective are strings. scope, change_paths, constraints, and "
        "acceptance_criteria are non-empty arrays of strings. verification_commands is a "
        "non-empty array of non-empty argv string arrays. Return no Markdown fence, explanation, "
        "AWF metadata, branch, SHA, role selection, artifact path, or protocol comment."
    )
    if mode == ():
        return semantic
    if mode == ("milestone-next",):
        return (
            "If Plan work remains, return the next task using this contract: "
            + semantic
            + " If the Plan is complete, return only MILESTONE_COMPLETE. If blocked, return "
            "BLOCKED on the first line and one non-empty reason on following lines."
        )
    if mode == ("terminal-decision",):
        return _architect_instruction(mode)
    raise ContractError("OpenCode architect mode is unsupported")


def _require(spec: InvocationSpec, provider: str, roles: set[str]) -> None:
    if spec.provider != provider or spec.role not in roles:
        raise ContractError(f"{provider} renderer does not own this provider/role selection")
    if not spec.environment:
        raise ContractError("provider environment must be explicitly bound")


class OpenCodeRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "opencode", {"architect", "coder", "reviewer"})
        if spec.role == "coder":
            allowed = {(ATTACH_INPUT,)}
        elif spec.role == "architect":
            allowed = {(), (ATTACH_INPUT,), ("milestone-next",), ("terminal-decision",)}
        else:
            allowed = {(), (ATTACH_INPUT,)}
        if spec.provider_args not in allowed:
            raise ContractError("OpenCode provider options are invalid")
        argv = ["run", "--pure", "--dir", spec.workspace]
        if spec.provider_args:
            argv += ["-f", spec.input_path]
        if spec.model:
            argv += ["-m", spec.model]
        prompt = spec.input_text
        if spec.role == "architect":
            prompt += "\n\n" + _opencode_architect_instruction(spec.provider_args)
        argv += ["--", prompt]
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


class CodexCoderRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "codex", {"coder"})
        if spec.provider_args:
            raise ContractError("Codex coder does not accept provider options")
        argv = ["exec", "-C", spec.workspace, "--sandbox", "workspace-write"]
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


class CodexArchitectRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "codex", {"architect"})
        instruction = _architect_instruction(spec.provider_args)
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
            stdin=(spec.input_text + "\n\n" + instruction).encode("utf-8"),
            environment=spec.environment,
        )


class PiReviewerRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "pi", {"reviewer"})
        if len(spec.provider_args) != 1:
            raise ContractError("Pi reviewer requires one exact base ref")
        base = spec.provider_args[0]
        finding = (
            PI_FINDING_INSTRUCTIONS
            if dict(spec.environment).get("AWF_FINDING_ENABLED") == "1"
            else ""
        )
        message = (
            f"Review the attached trusted context against base ref `{base}`. "
            "Use only read-only repository inspection tools. "
            "Return the complete filled-in Markdown ReviewReport as stdout. "
            "The trusted runner will persist stdout to the exact ReviewReport path; do not "
            f"claim you wrote a file. ReviewReport output path: {spec.report_path}" + finding
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


class PiArchitectRenderer:
    """Render one non-authorizing Pi planning invocation over trusted context."""

    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "pi", {"architect"})
        if spec.provider_args == ():
            message = (
                "Reason from the attached trusted project context as the Agent Workflow Architect. "
                "Use only read-only repository inspection tools. " + _architect_instruction(())
            )
        elif spec.provider_args == ("terminal-decision",):
            message = (
                "Make the final decision for this one exact reviewed TaskCard from the attached "
                "trusted facts. Use only read-only repository inspection tools. Return the "
                "complete Decision Markdown as stdout using exactly one closed verdict: "
                "approve, request_changes, reject, or escalate. Do not edit files, merge, or "
                "invent rework."
            )
        elif spec.provider_args == ("milestone-next",):
            message = (
                "Decide the next step for this exact Plan milestone from the attached durable "
                "facts and freshly observed repository main. Use only read-only repository "
                "inspection tools and reason silently. "
                + _architect_instruction(spec.provider_args)
            )
        else:
            raise ContractError("Pi architect mode is unsupported")
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


class PiCoderRenderer:
    def render(self, spec: InvocationSpec) -> RenderedInvocation:
        _require(spec, "pi", {"coder"})
        if spec.provider_args:
            raise ContractError("Pi coder provider options are invalid")
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
            "read,grep,find,ls,edit,write",
        ]
        if spec.model:
            argv += ["--model", spec.model]
        argv += [f"@{spec.input_path}", spec.input_text]
        return RenderedInvocation(
            spec.executable, tuple(argv), spec.workspace, environment=spec.environment
        )


def render_provider_invocation(spec: InvocationSpec) -> RenderedInvocation:
    if spec.provider == "pi" and spec.role == "architect":
        return PiArchitectRenderer().render(spec)
    if spec.provider == "opencode":
        return OpenCodeRenderer().render(spec)
    if spec.provider == "codex" and spec.role == "architect":
        return CodexArchitectRenderer().render(spec)
    if spec.provider == "codex" and spec.role == "coder":
        return CodexCoderRenderer().render(spec)
    if spec.provider == "codex" and spec.role == "reviewer":
        return CodexReviewerRenderer().render(spec)
    if spec.provider == "pi" and spec.role == "reviewer":
        return PiReviewerRenderer().render(spec)
    if spec.provider == "pi" and spec.role == "coder":
        return PiCoderRenderer().render(spec)
    raise ContractError("no installed renderer owns this provider/role selection")
