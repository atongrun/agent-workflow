from __future__ import annotations

import pytest

from agent_workflow.operations.awf_taskcard import (
    TaskCardContractError,
    reviewer_selection_contract,
)


def selection_block(coder_tool="opencode", coder_model="coder/model") -> str:
    return f"""<!-- awf-reviewer-selection
{{
  "coder": {{"tool": "{coder_tool}", "model": "{coder_model}"}},
  "reviewer": {{"tool": "pi", "model": "reviewer/model"}}
}}
-->"""


def test_taskcard_binds_distinct_coder_and_reviewer_selection():
    contract = reviewer_selection_contract(
        selection_block(),
        fallback_tool="opencode",
        fallback_model="legacy/model",
    )

    assert (contract.coder.tool, contract.coder.model) == ("opencode", "coder/model")
    assert (contract.reviewer.tool, contract.reviewer.model) == ("pi", "reviewer/model")


def test_legacy_taskcard_keeps_same_tool_and_model_for_both_roles():
    contract = reviewer_selection_contract(
        "# Legacy card\n",
        fallback_tool="opencode",
        fallback_model="legacy/model",
    )

    assert contract.coder == contract.reviewer
    assert (contract.coder.tool, contract.coder.model) == ("opencode", "legacy/model")


@pytest.mark.parametrize(
    "text",
    [
        "<!-- awf-reviewer-selection\n{}\n-->",
        selection_block(coder_tool="pi"),
        selection_block() + "\n" + selection_block(),
    ],
)
def test_invalid_or_ambiguous_selection_block_fails_closed(text):
    with pytest.raises(TaskCardContractError):
        reviewer_selection_contract(
            text,
            fallback_tool="opencode",
            fallback_model="legacy/model",
        )
