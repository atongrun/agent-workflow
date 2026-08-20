from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from agent_workflow.runtime import ProcessResult, RenderedInvocation


def _review_markdown(verdict: str) -> bytes:
    failures: list[dict[str, object]] = []
    blocked_reason = ""
    if verdict == "REQUEST_CHANGES":
        failures = [
            {
                "evidence": {"kind": "criterion", "criterion": "local-runtime-fixture"},
                "required_correction": "apply the exact bounded rework",
            }
        ]
    elif verdict == "BLOCKED":
        blocked_reason = "the scripted external prerequisite is unavailable"
    payload = {
        "verdict": verdict,
        "deterministic_failures": failures,
        "blocked_reason": blocked_reason,
    }
    return (
        "# ReviewReport\n\n<!-- awf-review-report\n"
        + json.dumps(payload, sort_keys=True)
        + "\n-->\n"
    ).encode()


@dataclass
class _ScriptedHandle:
    process_identity_sha256: str
    result: ProcessResult

    def wait(self) -> ProcessResult:
        return self.result


class ScriptedProviderLauncher:
    """Deterministic local provider with no Store or transport access."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self, invocation: RenderedInvocation) -> _ScriptedHandle:
        workspace = Path(invocation.cwd)
        if invocation.file_inputs:
            raw = invocation.file_inputs[0].content
        elif invocation.stdin is not None:
            raw = invocation.stdin
        else:
            raw = invocation.argv[-1].encode()
        request = json.loads(raw.decode())
        invocation_id = str(request.get("invocation_id", ""))
        if not invocation_id and "-f" in invocation.argv:
            input_name = Path(invocation.argv[invocation.argv.index("-f") + 1]).stem
            invocation_id = input_name.removeprefix("runtime-input-")
        self.calls.append(invocation_id)
        mode = str(request.get("mode", "success"))
        stdout = b""
        if str(request.get("stage")) == "review":
            stdout = _review_markdown(str(request.get("verdict", "PASS")))
        else:
            change = workspace / str(request.get("change_path", "result.txt"))
            change.parent.mkdir(parents=True, exist_ok=True)
            change.write_text(
                str(request.get("change_text", invocation_id + "\n")), encoding="utf-8"
            )
            if mode != "missing_artifact":
                report_name = request.get("implementation_report")
                reports = sorted(workspace.glob(".awf/artifacts/impl-report-*.md"))
                report = workspace / str(report_name) if report_name else reports[0]
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(
                    "# ImplementationReport\n\nscripted local provider completed\n",
                    encoding="utf-8",
                )
        return_code = 17 if mode == "provider_error" else 0
        identity = hashlib.sha256(
            f"scripted-provider\0{invocation.sha256}\0{len(self.calls)}".encode()
        ).hexdigest()
        return _ScriptedHandle(identity, ProcessResult(return_code, stdout, b""))
