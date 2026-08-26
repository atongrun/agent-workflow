# RC.2 Phase 2B — Architect Continuation Provider Boundary

## Task ID

RC2-P2B-ARCHITECT-CONTINUATION

## Goal

Extend the Phase 2A binding-driven Architect provider boundary through milestone-next and terminal
decision handling, preserving exact no-replay and trusted TaskCard/Decision authority.

## Scope

- Render Pi/OpenCode/Codex according to the frozen Architect binding for initial, milestone-next,
  and terminal-decision invocation paths.
- For any next TaskCard, validate the common seven-field semantic JSON and assemble trusted facts
  before existing persistence/dispatch.
- Retain the existing closed Decision output for terminal decisions.
- Add deterministic binding, semantic-output, no-replay and continuation conformance.

## Exclusions

- Real provider smokes, provider-session resume, MCP/status, generic registry, Git/PR/merge/ACK
  changes, topology E2E, README support claims and release work.

## Acceptance

- [ ] Every Architect provider is selected from the frozen binding on each invocation path.
- [ ] Next TaskCard semantic JSON receives trusted assembly before persistence.
- [ ] Decision output remains closed and provider failure/ambiguity remains no-replay.
- [ ] Existing latest-main, CompletedCardFact and dispatch authority boundaries remain unchanged.

## Verification

```bash
python -m pytest -q tests/test_awf_plan.py tests/test_plan_loop.py tests/test_runtime_architect.py tests/test_runtime_provider_renderers.py
ruff check src/agent_workflow/operations/awf_plan.py src/agent_workflow/runtime tests/test_awf_plan.py tests/test_plan_loop.py tests/test_runtime_architect.py tests/test_runtime_provider_renderers.py
ruff format --check src/agent_workflow/operations/awf_plan.py src/agent_workflow/runtime tests/test_awf_plan.py tests/test_plan_loop.py tests/test_runtime_architect.py tests/test_runtime_provider_renderers.py
git diff --check
```
