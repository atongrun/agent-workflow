# TaskCard: Phase 5-02 Architect-Produced One-Card Closure

Status: Frozen from the owner-authorized Phase 5-02/5-03 product closure on 2026-08-23.

## Task ID

phase5-02-architect-one-card-closure

## Goal

Close one real downstream card from an exact committed Plan without a Human-authored TaskCard:

```text
committed Plan + explicit awf plan start + Pi Architect binding
  -> durable Architect start delivery
  -> fresh Pi TaskCard
  -> existing trusted TaskCard commit/dispatch
  -> existing Windows OpenCode Coder
  -> existing trusted import/commit/push/PR
  -> existing exact-head Reviewer and bounded rework
  -> fresh Pi terminal Decision
  -> exact CI + trusted merge
  -> CompletedCardFact
  -> stop after one card
```

Product closure takes precedence over Runtime v2 representation cleanup. This card must reuse the
v0.3.0 production operations path and must not adopt the Runtime v2 Store as the default.

## Integrated basis

- `main@8f13b80b2fadba63a4a3e0d464220629c8e9b858`, merging Phase 5-01.
- Agent Bus `v0.3.1`, annotated tag object `821c7095...`, peeled commit `c9626894...`, carrying
  `agent-bus.listen.on-argv.v1`.
- Phase 5-01 Pi Architect RoleBinding/renderer and trusted create-only TaskCard persistence.
- Existing production `awf_dispatch.py` and `awf_role.py` coder/reviewer/rework/Git/PR/ACK path.
- Frozen Runtime semantic contract and ADR-0006 external-truth/ambiguity boundaries.

## Required product behavior

1. `awf plan start --plan <tracked-path> --one-card` is the narrow Agent-facing start capability.
   It binds a tracked Plan path, exact commit, Git blob hash, repository identity, freshly observed
   upstream main, and the exact configured Pi Architect profile/tool/model/workspace facts.
2. Start persists one minimal `PlanRun` before sending one structured Architect event. A successful
   Agent Bus send is the durable handoff; the initiating process/chat is not required afterward.
3. Normal `awf init` validates and persists the complete local role plan, then installs/reconciles
   and starts one managed listener per selected RoleBinding. It registers the existing Fast/Deep
   handlers and prints Ready only after exact process/profile/lease plus Agent Bus connected facts
   pass for every selected local role. Init manages no remote machine and never runs Deep. If one
   listener fails, valid configuration remains; only newly started exact listeners may be stopped.
   The Plan start handler then runs existing Fast with taskcard-authoring intent before Pi; failure
   denies before a model call.
4. The managed Architect listener validates the exact start payload against its local RoleBinding,
   composes bounded `ArchitectContext` from durable Plan/main facts, and invokes Pi fresh with
   read-only tools and no session.
5. Pi returns a complete TaskCard. The trusted Phase 5-01 helper validates and creates it; the
   trusted runner additionally binds the exact fresh base and frozen coder/reviewer selection.
6. Immediately before the first business dispatch, AWF automatically runs existing Fast with
   remote-dispatch intent. It reuses a Deep proof only when the existing fingerprint/MAC/TTL rules
   accept it; otherwise it automatically runs the existing no-model Deep request/result proof and
   continues only with `allow_remote_dispatch=true` and zero-queue/handler-success evidence.
7. The existing dispatcher and production role handlers own Coder, trusted import/commit/push/PR,
   Reviewer and existing bounded deterministic rework. No second worker, journal, workspace-result
   adoption path, Git pipeline or command/result routing is added.
8. Reviewer `PASS` or `BLOCKED` reaches the existing Architect terminal handler. It invokes fresh
   Pi for a closed Decision. Only `approve` after Reviewer `PASS` may enter merge. Every other
   Decision persists evidence and stops without merge or Architect-requested same-card rework.
9. Trusted merge persists intent before `gh pr merge --match-head-commit`, never retries an
   ambiguous mutation, and records completion only after exact PR/head/green-CI/merge observation.
10. `CompletedCardFact` binds Plan, Architect, TaskCard, base/head/PR, reports, Decision, CI and merge.
   One-card mode then becomes complete without invoking Architect again.
11. `awf status` remains read-only and projects PlanRun/card/completion plus latest Fast/Deep facts
    without triggering either gate and without requiring a `.awf/active-run.json` authority
    pointer. Finding remains off.

## Acceptance

- [ ] Exact PlanFact rejects untracked/dirty/foreign Plan bytes or unavailable/mismatched main.
- [ ] Start payload and listener RoleBinding drift deny before Pi or TaskCard creation.
- [ ] Normal init starts distinct exact managed listeners for every selected local RoleBinding,
      including two listeners when Coder and Reviewer share one OpenCode installation/model; Ready
      is withheld on install/start/lease/Bus readiness failure without remote supervision.
- [ ] No business model call occurs before authoring Fast passes; no business dispatch occurs before
      remote Fast and any required existing Deep proof pass with `allow_remote_dispatch=true`.
- [ ] Pi TaskCard is fresh, exact-base bound, create-only, postflight-valid and contains exact
      OpenCode Coder/Reviewer selection; Human creates/edits/submits no TaskCard.
- [ ] Existing Coder/Reviewer/rework recovery tests remain green; no new `runtime/worker.py`,
      FreshStageCoordinator, AgentBusClient, execution journal or trusted-import/Git pipeline exists.
- [ ] Terminal `approve` is single-use and merge-eligible only after Reviewer PASS; non-approve and
      BLOCKED never merge.
- [ ] CI/merge intent/effect/observation and ambiguity/no-retry rows are deterministic and tested.
- [ ] CompletedCardFact and PlanRun form one exact join and status is mutation-free.
- [ ] Focused/full/Ruff/format/resource/installed-wheel checks pass.
- [ ] A real one-card downstream dogfood completes with Pi-created TaskCard, Windows OpenCode,
      exact Reviewer, green CI, AWF merge, queue zero, no manual low-level operation and Finding off.
- [ ] One targeted Phase 5-02 review returns PASS or receives only bounded functional repair.
- [ ] Phase 5-02 closes before any multi-card behavior is enabled.

## Explicit exclusions

- Runtime v2 Store default cutover or migration; legacy deletion or dual write.
- `runtime/worker.py`, a second Coder/Reviewer worker, FreshStageCoordinator or source-side
  AgentBusClient.
- A second execution journal, readiness protocol, command/result Bus family, workspace/result
  adoption, trusted import or Git/PR pipeline.
- TaskCard queue, scheduler, Host, Coordinator service, GUI/MCP/plugin framework or concurrent run.
- A second readiness protocol, runtime-v2 readiness tags, AgentBusClient, remote supervisor or
  weakened Fast fingerprint/Deep cache validation.
- Human-authored normal-path TaskCard, public `awf run <TaskCard>` UX, full recovery/resume,
  provider session restoration or Architect-requested same-card rework.
- Phase 5-03 next-card/MILESTONE_COMPLETE behavior before Phase 5-02 closeout.

## Allowed implementation paths

- `docs/tasks/phase5-02-architect-one-card-closure.md`
- `src/agent_workflow/cli.py`
- `src/agent_workflow/facade.py`
- `src/agent_workflow/node.py`
- `src/agent_workflow/status.py`
- `src/agent_workflow/plan_loop.py`
- `src/agent_workflow/runtime/architect.py`
- `src/agent_workflow/runtime/renderers.py`
- `schemas/node-profile.schema.json`
- `scripts/awf_dispatch.py`
- `scripts/awf_listen.py`
- `scripts/awf_plan.py`
- `scripts/awf_role.py`
- `tests/test_cli.py`
- `tests/test_facade.py`
- `tests/test_node.py`
- `tests/test_status.py`
- `tests/test_plan_loop.py`
- `tests/test_awf_listen.py`
- `tests/test_awf_plan.py`
- `tests/test_awf_role.py`
- `tests/test_runtime_architect.py`
- `tests/test_runtime_provider_renderers.py`
- `tests/verify_installed_wheel.py`
- `.awf/artifacts/impl-report-phase5-02-architect-one-card-closure.md`
- `.awf/artifacts/review-report-phase5-02-architect-one-card-closure.md`

Closeout may also update `README.md`, `HANDOFF.md`, `ROADMAP.md`, `CHANGELOG.md`,
`docs/plans/runtime-v2-development-plan.md` and the Phase 5-02 closeout report.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/cli.py",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/node.py",
    "src/agent_workflow/status.py",
    "src/agent_workflow/plan_loop.py",
    "src/agent_workflow/runtime/architect.py",
    "src/agent_workflow/runtime/renderers.py",
    "schemas/node-profile.schema.json",
    "scripts/awf_dispatch.py",
    "scripts/awf_listen.py",
    "scripts/awf_plan.py",
    "scripts/awf_role.py",
    "tests/test_cli.py",
    "tests/test_facade.py",
    "tests/test_node.py",
    "tests/test_status.py",
    "tests/test_plan_loop.py",
    "tests/test_awf_listen.py",
    "tests/test_awf_plan.py",
    "tests/test_awf_role.py",
    "tests/test_runtime_architect.py",
    "tests/test_runtime_provider_renderers.py",
    "tests/verify_installed_wheel.py",
    ".awf/artifacts/impl-report-phase5-02-architect-one-card-closure.md",
    ".awf/artifacts/review-report-phase5-02-architect-one-card-closure.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_plan_loop.py", "tests/test_awf_plan.py", "tests/test_awf_role.py"],
    ["ruff", "check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
