"""Minimal stdio MCP adapter over the installed application boundary."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_workflow import application


def tool_definitions() -> tuple[dict[str, object], ...]:
    shared_run = {"repo": {"type": "string"}, "run_id": {"type": "string"}}
    intent = {"human_intent": {"type": "string"}}
    return (
        {
            "name": "start_plan",
            "description": "Start one approved committed Plan through existing AWF authority.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "plan": {"type": "string"},
                    "mode": {"enum": ["one-card", "milestone"]},
                    **intent,
                },
                "required": ["repo", "plan", "mode", "human_intent"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_status",
            "description": "Read the conservative current PlanRun projection without mutation.",
            "inputSchema": {
                "type": "object",
                "properties": shared_run,
                "required": ["repo", "run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "doctor",
            "description": "Read exact local role readiness without mutating Workflow state.",
            "inputSchema": {
                "type": "object",
                "properties": {"repo": {"type": "string"}, "role": {"type": "string"}},
                "required": ["repo"],
                "additionalProperties": False,
            },
        },
        *(
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": {**shared_run, **intent},
                    "required": ["repo", "run_id", "human_intent"],
                    "additionalProperties": False,
                },
            }
            for name, description in (
                ("stop", "Stop exact local profiles only when it is currently safe."),
                ("deinit", "Deinitialize exact local profiles only when it is currently safe."),
                (
                    "continue_after_approval",
                    "Continue only after exact branch-protection approval re-observation.",
                ),
                (
                    "authorize_replacement",
                    "Authorize one exact replacement only after no-replay conditions are proven.",
                ),
            )
        ),
    )


def _tool_names() -> set[str]:
    return {str(tool["name"]) for tool in tool_definitions()}


def _arguments(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise application.ApplicationError("MCP tool arguments must be an object")
    return value


def _string(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise application.ApplicationError(f"MCP tool argument {name} must be a string")
    return value


def call_tool(name: str, arguments: object) -> object:
    args = _arguments(arguments)
    repo = Path(_string(args, "repo"))
    if name == "start_plan":
        return application.start_plan(
            repo,
            plan=_string(args, "plan"),
            mode=_string(args, "mode"),
            human_intent=_string(args, "human_intent"),
        )
    if name == "get_status":
        return application.status(repo, run_id=_string(args, "run_id"))
    if name == "doctor":
        return {"exit_code": application.doctor(repo, role=str(args.get("role", "")))}
    if name in {"stop", "deinit", "continue_after_approval", "authorize_replacement"}:
        operation: Callable[..., Any] = getattr(application, name)
        result = operation(
            repo,
            run_id=_string(args, "run_id"),
            human_intent=_string(args, "human_intent"),
        )
        return {"exit_code": result} if isinstance(result, int) else {"status": "accepted"}
    raise application.ApplicationError("MCP tool is not part of the AWF product surface")


def _message(identifier: object, *, result: object | None = None, error: str = "") -> str:
    value: dict[str, object] = {"jsonrpc": "2.0", "id": identifier}
    if error:
        value["error"] = {"code": -32000, "message": error}
    else:
        value["result"] = result
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def serve(stdin: object = sys.stdin, stdout: object = sys.stdout) -> int:
    for line in stdin:
        identifier = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise application.ApplicationError("MCP request must be an object")
            identifier = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            if method == "notifications/initialized":
                continue
            if method == "initialize":
                result: object = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "agent-workflow", "version": "0.4.0rc1"},
                }
            elif method == "tools/list":
                result = {"tools": list(tool_definitions())}
            elif method == "tools/call":
                if not isinstance(params, Mapping):
                    raise application.ApplicationError("MCP tools/call params must be an object")
                name = str(params.get("name", ""))
                if name not in _tool_names():
                    raise application.ApplicationError(
                        "MCP tool is not part of the AWF product surface"
                    )
                try:
                    payload = call_tool(name, params.get("arguments", {}))
                except application.ApplicationError as exc:
                    result = {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    }
                else:
                    result = {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                            }
                        ],
                        "structuredContent": payload if isinstance(payload, dict) else {},
                        "isError": False,
                    }
            else:
                raise application.ApplicationError("MCP method is unsupported")
            if identifier is not None:
                stdout.write(_message(identifier, result=result) + "\n")
                stdout.flush()
        except (json.JSONDecodeError, application.ApplicationError) as exc:
            if identifier is not None:
                stdout.write(_message(identifier, error=str(exc)) + "\n")
                stdout.flush()
    return 0


def main() -> int:
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
