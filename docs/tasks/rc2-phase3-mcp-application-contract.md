# TaskCard: RC2-P3-001 — shared application projection and MCP entry

## Background

RC.2 makes an initiating Agent's MCP call the normal entry for a Human-approved,
committed Markdown Plan. Current `awf plan start` and the beginner facade provide
useful operations but expose CLI-shaped parameters and do not share one conservative
PlanRun projection. The fresh Phase 5 r2 provider failure remains terminal,
unacknowledged evidence; it is not input to this TaskCard and must not be replayed.

## Goal

Add one installed, stateless application boundary that projects one PlanRun's safe
state and exposes the bounded RC.2 MCP tool surface without creating a second
workflow, transport, or mutation authority.

## Scope

- Add a pure application status/action projection over existing `PlanRunStore`,
  facade/node status, and exact plan facts.
- Add a thin stdio MCP adapter for `start_plan`, `get_status`, `doctor`, `stop`,
  `deinit`, `continue_after_approval`, and `authorize_replacement`.
- Route supported CLI product commands through the same application semantics where
  this can be done without deleting compatibility commands.
- Deny unsafe/unknown/conflicting facts with inspect/stop-only actions, and prove
  the adapter cannot expose ACK, requeue, replay, checkpoint editing, raw Agent Bus,
  or arbitrary merge operations.

## Out of Scope

- A dashboard, TUI, workflow engine, generic MCP framework, Agent Bus transport
  commands, provider replay/session resume, or a Plan schema change.
- Branch-protection bypass, automatic merge, arbitrary GitHub approval, any real
  delivery, or use of the terminal r2 identity.
- Phase 4 TaskCard parser consolidation and Phase 5 topology acceptance.

## Working Context

- **Repository:** `atongrun/agent-workflow`
- **Base:** `main` at `a852c73`
- **Task branch:** `codex/rc2-phase3-mcp-contract`
- **Entry points:** `src/agent_workflow/facade.py`, `src/agent_workflow/status.py`,
  `src/agent_workflow/operations/awf_plan.py`, `src/agent_workflow/cli.py`, and
  `src/agent_workflow/plan_loop.py`.
- **Existing invariants:** PlanRuns/TaskCards remain authoritative; status is
  read-only; handler success precedes ACK; all ambiguous provider effects are
  no-replay; local lifecycle uses exact profile identity only.

## Constraints

- MCP must be a stateless adapter over the application boundary and must not own
  persisted Workflow/TaskCard/Agent Bus state.
- A mutating MCP call requires explicit caller-provided Human intent and current
  allowed-action validation. Never treat an MCP connection/session as authority.
- Preserve credential isolation and never place secrets in tool schemas, responses,
  logs, argv, fixtures, or docs.
- Unknown or conflicting authority collapses to only inspect/stop; it may not
  advertise continue, replacement, merge, or dispatch.

## Acceptance Criteria

- [ ] The projection contains `current_state`, `current_card`, `last_completion`,
  `roles`, `blocker`, `next_safe_action`, and `allowed_actions`; it is pure and
  stable for repeated reads.
- [ ] Every required MCP tool delegates to the same application semantics, and its
  schema contains no transport/replay/merge escape hatch.
- [ ] Start and mutating lifecycle calls require explicit Human intent and reject
  stale/unknown/conflicting action facts before side effects.
- [ ] Approval/replacement calls fail closed until their exact existing authority
  conditions are satisfied; no automatic provider replay is introduced.
- [ ] Focused application/MCP/CLI tests pass, Ruff and diff checks pass, and a
  final candidate suite is run once before review.

## Verification

```bash
python -m pytest -q tests/test_application.py tests/test_mcp.py tests/test_cli.py
ruff check src/agent_workflow tests
ruff format --check src/agent_workflow tests
git diff --check
python -m pytest -q
```

## Risks

| Risk | Mitigation |
| --- | --- |
| Projection overclaims authority | Derive only from exact durable facts; unknown/conflict yields inspect/stop. |
| MCP becomes a second workflow path | Adapter delegates to one application service; tests assert no direct transport APIs. |
| Lifecycle action is too broad | Reuse existing exact profile/facade gates only. |

## Required output

- Implementation report with exact focused/full-suite and independent review evidence.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/application.py",
    "src/agent_workflow/mcp.py",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/cli.py",
    "pyproject.toml",
    "tests/test_application.py",
    "tests/test_mcp.py",
    "tests/test_cli.py",
    "docs/tasks/rc2-phase3-mcp-application-contract.md",
    "docs/tasks/rc2-phase3-mcp-application-contract-report.md",
    "README.md",
    "HANDOFF.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["python", "-m", "pytest", "-q", "tests/test_application.py", "tests/test_mcp.py", "tests/test_cli.py"],
    ["ruff", "check", "src/agent_workflow", "tests"],
    ["ruff", "format", "--check", "src/agent_workflow", "tests"]
  ]
}
-->
