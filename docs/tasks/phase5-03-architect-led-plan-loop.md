# TaskCard: Phase 5-03 Architect-Led Plan Loop

Status: Frozen from the owner-authorized Phase 5-03 product closure on 2026-08-23.

## Task ID

phase5-03-architect-led-plan-loop

## Goal

Extend the closed Phase 5-02 single-card primitive into one strictly serial Architect-led milestone:

```text
CompletedCardFact
  -> freshly fetch and observe exact upstream main
  -> existing Fast authoring gate
  -> fresh Pi Architect
  -> NextTaskCard | MILESTONE_COMPLETE | BLOCKED
  -> reuse the Phase 5-02 single-card primitive
  -> repeat
```

No new Coder/Reviewer worker, execution/Git pipeline, scheduler, TaskCard queue, readiness protocol
or recovery/resume mechanism is authorized.

## Integrated basis

- Phase 5-02 closed candidate `79cb76fc26cd1b01da72945fc12a8442be4418d3`.
- Real Phase 5-02 PlanRun `plan-6d33b101abdaa25380ba529f` and downstream merge
  `41239ebda5d6d577e59f26e0c98f79a32c2071b5`.
- Existing Fast/Deep handlers/cache and Phase 5-02 TaskCard/dispatch/Reviewer/Decision/merge path.
- Agent Bus formal release `v0.3.1`; Agent Bus remains transport-only.

## Required behavior

1. The Agent-facing Plan start accepts a closed `milestone` mode in addition to one-card mode. The
   initiating Agent may exit after durable start; no Human TaskCard or pre-generated queue exists.
2. After every trusted merge, persist the exact CompletedCardFact, clear the active card, then
   freshly fetch and observe exact upstream main before any next Architect invocation.
3. The next Architect context contains only the exact committed Plan/PlanFact, fresh main, exact
   last CompletedCardFact and minimal frozen execution/completion facts. It does not rely on the
   initiating chat or a provider session.
4. Before every next-card Architect invocation, rerun existing Fast with TaskCard-authoring intent.
   Before every business dispatch, rerun existing Fast with remote-dispatch intent and use the
   existing Deep cache only when its exact fingerprint/MAC/TTL rules permit it.
5. Invoke the configured Pi Architect fresh and accept exactly one closed outcome:
   - a complete NextTaskCard whose frozen base is the freshly observed main and whose selections
     match the PlanRun;
   - exact `MILESTONE_COMPLETE`; or
   - `BLOCKED` followed by a non-empty durable reason.
6. A NextTaskCard is trusted-persisted and dispatched through the unchanged Phase 5-02 primitive.
   One card must be fully merged and completed before another card can be created.
7. `MILESTONE_COMPLETE` is accepted only with no active card and the exact original Plan and
   Architect binding. `BLOCKED` never dispatches or merges.
8. Retain one immutable CompletedCardFact per completed card under the PlanRun while projecting only
   current card, last completion, status and minimal completion identities in normal status.
9. `awf status` stays read-only and reports milestone completion/first blocker. No automatic
   partial-execution recovery is added.

## Acceptance

- [ ] Unit tests close one-card, NextTaskCard, MILESTONE_COMPLETE, BLOCKED, fresh-main binding,
      repeated Fast/Deep, no-active-card and ambiguous-invocation rows.
- [ ] Existing Phase 5-02 and v0.3.0 Coder/Reviewer/rework/recovery tests remain green.
- [ ] A real two-card downstream milestone starts from one committed Plan and returns after durable
      start; Pi dynamically creates both cards with no Human TaskCard and no pre-generated queue.
- [ ] Card 1 completes through Windows OpenCode, trusted PR, exact-head Reviewer, fresh terminal Pi,
      green CI, trusted merge and CompletedCardFact 1.
- [ ] Card 2 is created only after a fresh upstream-main observation containing Card 1; its frozen
      base equals that exact main. It completes through a second independent PR/merge and
      CompletedCardFact 2.
- [ ] Fresh Pi then returns exact MILESTONE_COMPLETE; status shows completion, durable facts form one
      exact join and all relevant Agent Bus queues return to zero.
- [ ] No manual low-level dispatch/ACK/requeue/resume/merge occurs; Finding remains off.
- [ ] One targeted Phase 5-03 review returns PASS or receives only bounded functional repair.

## Explicit exclusions

- Human stop/resume, active Architect recovery, partial Coder workspace takeover or provider
  session restoration.
- Process-crash auto-resume, side-effect/ACK ambiguity reconciliation or automatic merge ambiguity
  recovery.
- Plan hot update, Architect hot swap, concurrent milestones, retained-state migration, Runtime v2
  default cutover or final compatibility CLI deletion.
- Runtime worker, second journal/readiness/transport/Git pipeline, TaskCard queue, generic scheduler,
  Host, physical Coordinator, GUI/MCP/plugin framework or remote supervisor.

## Allowed paths

- `docs/tasks/phase5-03-architect-led-plan-loop.md`
- `src/agent_workflow/cli.py`
- `src/agent_workflow/plan_loop.py`
- `src/agent_workflow/runtime/renderers.py`
- `scripts/awf_plan.py`
- `tests/test_cli.py`
- `tests/test_plan_loop.py`
- `tests/test_runtime_provider_renderers.py`
- `tests/verify_installed_wheel.py`
- `tests/test_awf_plan.py`
- `.awf/artifacts/impl-report-phase5-03-architect-led-plan-loop.md`
- `.awf/artifacts/review-report-phase5-03-architect-led-plan-loop.md`

Closeout may also update `README.md`, `HANDOFF.md`, `ROADMAP.md`, `CHANGELOG.md`, version metadata,
`docs/plans/runtime-v2-development-plan.md`, release notes and the Phase 5-03 closeout report.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/cli.py",
    "src/agent_workflow/plan_loop.py",
    "src/agent_workflow/runtime/renderers.py",
    "scripts/awf_plan.py",
    "tests/test_cli.py",
    "tests/test_plan_loop.py",
    "tests/test_runtime_provider_renderers.py",
    "tests/verify_installed_wheel.py",
    "tests/test_awf_plan.py",
    ".awf/artifacts/impl-report-phase5-03-architect-led-plan-loop.md",
    ".awf/artifacts/review-report-phase5-03-architect-led-plan-loop.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_plan_loop.py", "tests/test_awf_plan.py", "tests/test_awf_role.py"],
    ["ruff", "check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
