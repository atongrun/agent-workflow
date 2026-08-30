from __future__ import annotations

import io
import json

from agent_workflow import mcp


def test_mcp_exposes_only_the_frozen_product_tools():
    tools = mcp.tool_definitions()
    names = {str(tool["name"]) for tool in tools}

    assert names == {
        "start_plan",
        "get_status",
        "doctor",
        "stop",
        "deinit",
        "continue_after_approval",
        "authorize_replacement",
    }
    for tool in tools:
        schema = tool["inputSchema"]
        assert isinstance(schema, dict)
        assert set(schema["properties"]).isdisjoint(
            {"ack", "requeue", "replay", "checkpoint", "agent_bus", "merge"}
        )


def test_mcp_get_status_delegates_to_application(monkeypatch):
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        mcp.application,
        "status",
        lambda repo, *, run_id: observed.update(repo=repo, run_id=run_id) or {"state": "safe"},
    )

    result = mcp.call_tool("get_status", {"repo": ".", "run_id": "plan-123"})

    assert result == {"state": "safe"}
    assert observed["run_id"] == "plan-123"


def test_mcp_stdio_lists_tools_and_returns_structured_tool_result(monkeypatch):
    def noisy_call_tool(_name, _arguments):
        print("application stdout must not enter MCP protocol")
        return {"current_state": "card_active"}

    monkeypatch.setattr(mcp, "call_tool", noisy_call_tool)
    source = io.StringIO(
        "\n".join(
            (
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "get_status", "arguments": {"repo": ".", "run_id": "x"}},
                    }
                ),
            )
        )
        + "\n"
    )
    destination = io.StringIO()

    assert mcp.serve(source, destination) == 0

    replies = [json.loads(line) for line in destination.getvalue().splitlines()]
    assert replies[0]["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert len(replies[1]["result"]["tools"]) == 7
    assert json.loads(replies[2]["result"]["content"][0]["text"]) == {
        "current_state": "card_active"
    }
    assert replies[2]["result"]["isError"] is False


def test_mcp_returns_tool_refusal_as_visible_tool_error(monkeypatch):
    monkeypatch.setattr(
        mcp,
        "call_tool",
        lambda _name, _arguments: (_ for _ in ()).throw(
            mcp.application.ApplicationError("exact authority denied")
        ),
    )
    source = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_status", "arguments": {"repo": ".", "run_id": "x"}},
            }
        )
        + "\n"
    )
    destination = io.StringIO()

    assert mcp.serve(source, destination) == 0

    reply = json.loads(destination.getvalue())
    assert reply["result"]["isError"] is True
    assert reply["result"]["content"] == [{"type": "text", "text": "exact authority denied"}]


def test_mcp_parse_error_never_reuses_a_prior_request_identifier():
    source = io.StringIO(
        "\n".join(
            (
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
                "not json",
            )
        )
        + "\n"
    )
    destination = io.StringIO()

    assert mcp.serve(source, destination) == 0

    assert len(destination.getvalue().splitlines()) == 1
