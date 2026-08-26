# TaskCard: RC2-P3-004 — replacement dispatch and Phase 3 acceptance

## Goal

Finish Phase 3 as one product boundary: a Human-authorized, evidence-proven
replacement must create one fresh coder delivery from the same frozen TaskCard,
then a fresh disposable real acceptance proves the complete path.

## Scope

- Dispatch exactly one replacement only from the persisted eligible lineage.
- Bind the replacement to the old event as causal source while preserving the
  same role, tool, model, TaskCard, branch, source commit, and frozen base.
- Persist the fresh delivery identity before returning success and make any
  dispatch uncertainty terminal/no-retry.
- Run the official fresh replacement acceptance, then record a credential-free
  Phase 3 closeout report.

## Out of Scope

- ACK/requeue/replay/resend of the old delivery, provider-session recovery,
  TaskCard/base/tool/model changes, arbitrary dispatch, or a second workflow.

## Constraints

- The replacement delivery and provider invocation must differ from the old one.
- Old checkpoint/evidence remains immutable; old or new uncertainty blocks.
- The acceptance uses a fresh disposable identity and exact closeout only.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/application.py",
    "src/agent_workflow/operations/awf_dispatch.py",
    "src/agent_workflow/operations/awf_plan.py",
    "tests/test_application.py",
    "tests/test_awf_plan.py",
    "docs/tasks/rc2-phase3-replacement-acceptance.md",
    "docs/tasks/rc2-phase3-replacement-acceptance-report.md",
    "README.md",
    "HANDOFF.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["python", "-m", "pytest", "-q", "tests/test_application.py", "tests/test_awf_plan.py"],
    ["ruff", "check", "src/agent_workflow", "tests"]
  ]
}
-->
