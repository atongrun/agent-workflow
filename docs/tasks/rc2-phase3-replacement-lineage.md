# TaskCard: RC2-P3-003 — Human-authorized replacement lineage

## Goal

Allow one Human-authorized replacement delivery for a truthfully ambiguous,
nonterminal provider outcome only after AWF proves the old exact effect is stopped,
has no unexplained Git/PR/merge/outbox effect, and retains immutable evidence.

## Scope

- Add a credential-free, fail-closed replacement eligibility projection over the
  existing delivery checkpoint, outbox, provenance, and PlanRun facts.
- Require a fresh replacement delivery/invocation identity with explicit old-to-new
  lineage, frozen role/tool/model/TaskCard/base/workspace facts, and no reset of
  capacity facts.
- Add deterministic eligibility/denial tests only; real replacement acceptance is
  a fresh later Phase 5 identity.

## Out of Scope

- ACK/requeue/resend/replay of the old delivery, session restoration, automatic
  provider retry, state editing, arbitrary GitHub effects, or any real business
  dispatch during implementation.

## Constraints

- Unknown old process, checkpoint, outbox, Git, PR, or merge facts deny.
- The new delivery is never the old delivery and never reuses an invocation ID.
- Human intent is action-specific and does not waive any frozen authority join.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/application.py",
    "src/agent_workflow/mcp.py",
    "src/agent_workflow/operations/awf_plan.py",
    "src/agent_workflow/operations/awf_role.py",
    "src/agent_workflow/plan_loop.py",
    "tests/test_application.py",
    "tests/test_awf_plan.py",
    "tests/test_plan_loop.py",
    "docs/tasks/rc2-phase3-replacement-lineage.md",
    "docs/tasks/rc2-phase3-replacement-lineage-report.md",
    "README.md",
    "HANDOFF.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["python", "-m", "pytest", "-q", "tests/test_application.py", "tests/test_awf_plan.py", "tests/test_plan_loop.py"],
    ["ruff", "check", "src/agent_workflow", "tests"]
  ]
}
-->
