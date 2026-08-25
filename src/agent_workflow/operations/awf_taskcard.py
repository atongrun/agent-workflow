"""Machine-readable contracts embedded in frozen downstream TaskCards."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_REVIEWER_SELECTION_RE = re.compile(
    r"<!--\s*awf-reviewer-selection\s*\n(?P<body>.*?)\n\s*-->",
    re.DOTALL,
)
_CODER_TOOLS = frozenset({"codex", "opencode"})
_REVIEWER_TOOLS = frozenset({"codex", "opencode", "pi"})


class TaskCardContractError(ValueError):
    """A frozen TaskCard contract is malformed or inconsistent."""


@dataclass(frozen=True)
class RoleSelection:
    tool: str
    model: str


@dataclass(frozen=True)
class ReviewerSelectionContract:
    coder: RoleSelection
    reviewer: RoleSelection


def _selection(value: object, role: str, supported_tools: frozenset[str]) -> RoleSelection:
    if not isinstance(value, dict) or set(value) != {"tool", "model"}:
        raise TaskCardContractError(f"{role} selection must contain only tool and model")
    tool = value.get("tool")
    model = value.get("model")
    if tool not in supported_tools:
        raise TaskCardContractError(f"{role} tool is unsupported")
    if not isinstance(model, str) or len(model) > 200 or any(ord(char) < 0x20 for char in model):
        raise TaskCardContractError(f"{role} model is invalid")
    return RoleSelection(tool=tool, model=model)


def reviewer_selection_contract(
    text: str,
    *,
    fallback_tool: str,
    fallback_model: str,
) -> ReviewerSelectionContract:
    """Parse the optional exact-stage selection block, preserving legacy cards."""
    matches = list(_REVIEWER_SELECTION_RE.finditer(text))
    if not matches:
        fallback = RoleSelection(tool=fallback_tool, model=fallback_model)
        return ReviewerSelectionContract(coder=fallback, reviewer=fallback)
    if len(matches) != 1:
        raise TaskCardContractError("TaskCard must contain exactly one reviewer selection block")
    try:
        value = json.loads(matches[0].group("body"))
    except json.JSONDecodeError as exc:
        raise TaskCardContractError("reviewer selection block is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"coder", "reviewer"}:
        raise TaskCardContractError("reviewer selection block must contain coder and reviewer")
    return ReviewerSelectionContract(
        coder=_selection(value["coder"], "coder", _CODER_TOOLS),
        reviewer=_selection(value["reviewer"], "reviewer", _REVIEWER_TOOLS),
    )
