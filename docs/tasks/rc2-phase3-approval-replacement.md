# TaskCard: RC2-P3-002 — exact approval continuation gate

## Goal

Complete the approval-continuation portion of Phase 3: project an exact
`WAITING_FOR_HUMAN_APPROVAL` state and continue only after re-observing the
same PR/base/head/CI/approval tuple.

## Scope

- Extend the existing PlanRun/application/MCP boundary; keep MCP stateless.
- Persist only credential-free, exact approval/replacement facts already required
  by the frozen Plan contract.
- Add pure projection and fail-closed tests for drift, missing approval, and
  unknown mergeability.

## Out of Scope

- Provider replay, ACK/requeue/resend, automatic merge, approval bypass, Plan hot
  update, session recovery, replacement delivery, or any real business delivery.

## Constraints

- A Human approval applies only to the recorded PR head; any tuple drift blocks.
- Unknown facts project only inspect/doctor/stop. No credential or raw GitHub
  response is persisted or exposed.

## Verification

```bash
python -m pytest -q tests/test_application.py tests/test_mcp.py tests/test_awf_plan.py tests/test_plan_loop.py
ruff check src/agent_workflow tests
ruff format --check src/agent_workflow tests
git diff --check
python -m pytest -q
```

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/application.py",
    "src/agent_workflow/mcp.py",
    "src/agent_workflow/operations/awf_plan.py",
    "src/agent_workflow/plan_loop.py",
    "tests/test_application.py",
    "tests/test_mcp.py",
    "tests/test_awf_plan.py",
    "tests/test_plan_loop.py",
    "docs/tasks/rc2-phase3-approval-replacement.md",
    "docs/tasks/rc2-phase3-approval-replacement-report.md",
    "README.md",
    "HANDOFF.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["python", "-m", "pytest", "-q", "tests/test_application.py", "tests/test_mcp.py", "tests/test_awf_plan.py", "tests/test_plan_loop.py"],
    ["ruff", "check", "src/agent_workflow", "tests"]
  ]
}
-->
