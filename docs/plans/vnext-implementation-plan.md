# Agent Workflow VNext Implementation Plan

Status: **Frozen for implementation**

Authority date: 2026-09-01

Frozen legacy baseline: `main@533a8950e0c675986319b810e7191793ef578871`

This plan operationalizes the owner-approved VNext authority. It does not reopen architecture and
does not authorize scope beyond the gates below.

## Frozen product contract

- Exactly five stages: `AUTHOR`, `IMPLEMENT`, `REVIEW`, `DECIDE`, `MERGE`.
- Run status: `ACTIVE`, `WAITING`, `TERMINAL`.
- Waiting reasons: `PROVIDER`, `SSH`, `EXTERNAL_READ`, `HUMAN`,
  `EFFECT_RECONCILIATION`, `BUDGET_EXHAUSTED`.
- Terminal outcomes: `COMPLETED`, `BLOCKED`, `STOPPED`.
- Primary abstractions: Run, Task, Role and Result. Auxiliary concepts are limited to Executor,
  PendingOperation and Provenance.
- Exactly one Coordinator/writer and one base-branch authority per Run.
- Roles are peer Architect, Coder and Reviewer bindings of Provider plus Target.
- Initial topology only: local Pi Architect, OpenCode Coder on `windows-coder` over SSH, local Codex
  Reviewer, and local Pi terminal Decision.
- Typed provider Results only. Prefer native structured output, then native result file, then one
  unambiguous JSON object. No Markdown parsing, inference, repair, candidate selection or critical
  field filling.
- Git is cross-machine code transport. The current HostRunner publishes only the derived frozen Task
  branch; the Coordinator owns PR, CI, merge, fresh base and progression.
- Reviewer `request_changes` returns the same Task to `IMPLEMENT`, from the exact reviewed head,
  using the same branch and PR.
- Initial executors expose only `execute(job)` and `inspect(job_id)`. SSH invokes one fixed
  `awf-agent` command with JobSpec on stdin, machine result on stdout and diagnostics on stderr.
- No required Agent Bus, background service, custom file transport, distributed authority,
  credential subsystem or generic framework.

## Phase 0 — RC.2 freeze

- Freeze the legacy behavioral oracle at the exact baseline above.
- Close PR #189 without merge; do not create the RC.2 tag or Release.
- Record only this Plan, ADR-0007 and the current HANDOFF update.

Exit: live main and PR state are observed, and repository truth records the pivot.

## VNX-01 — Minimal typed authority

Implement `RunAuthority`, `TaskSpec`, Role bindings, typed Results, pending-operation identity,
compare-and-swap acceptance and the five-stage serial reducer. Support only the initial topology.

Exit: focused pure-state tests prove valid transitions, writer/sequence/result identity,
idempotent duplicate handling, conflicting/late Result denial, retry budgets and terminal rules.
Production code has no Markdown parser, Agent Bus dependency or credential subsystem.

## VNX-02 — One real vertical slice

Implement narrow Local/SSH executors, on-demand `awf-agent`, remote `JobReceipt`, retained workspace
safety, exact Task-branch publication, and Coordinator Git/GitHub effects for PR, CI and merge.
Immediately run the one authorized real-model vertical-slice Run.

Exit: zero background AWF services and Agent Bus dependencies; one Coordinator and base authority;
three or fewer persistent state families; six or fewer long-lived new core modules; VNext target at
or below 1,500 production lines and hard stop above 2,000 before the slice completes; no credential
or cross-machine artifact subsystem.

## Mandatory Kill Gate

Return exactly `CONTINUE` or `TERMINATE AWF`. Default to termination if the slice needs a listener,
Agent Bus, multiple authorities, replicated state, delivery lineage, exact-close machinery,
Markdown parsing, remote base/merge ownership, queue/lease/scheduler, provider framework, more than
three state families, more than six new core modules, more than 2,000 VNext production lines, an
artifact/credential subsystem, or provides no meaningful benefit over SSH + Git + manual PR.

Do not redesign after termination.

## VNX-03 — Reliability (only after CONTINUE)

Add bounded compute retries, SSH inspection, reconcile-only handling for push/PR/merge ambiguity,
WAITING semantics and one scripted fault matrix. Run the one 100-Task deterministic soak. Do not
use real models or add architecture.

Default total attempts: Author/Review/Decision 2, Implementation 3, request-changes cycles 3, and
read-only Git/GitHub 3 quick retries. Budget exhaustion becomes `WAITING/BUDGET_EXHAUSTED`; a Human
may authorize only one new small budget at a time.

## VNX-04 — Full serial loop

Complete multi-Task AUTHOR progression, exact-head same-Task rework, resume, stop, read-only status
and immutable TaskCompletion facts. Reuse the VNX-03 harness without a second soak campaign.

## VNX-05 — Cutover

Make `awf init`, `awf plan start`, `awf status`, `awf resume` and `awf stop` VNext-only. Init stores
only role/provider/target configuration. Remote setup is package install plus normal provider and
GitHub login. Legacy paths must not create new Runs.

## VNX-06 — Legacy deletion

Immediately remove unconsumed legacy orchestration, Markdown protocols/parsers, mandatory Bus and
listener defaults, lineage/exact-close/state explosion and removed-problem tests. Retain narrow
workspace, execution and Git observation utilities plus historical evidence. End with one active
production Runtime.

## MVP stop rule

Stop development when the approved slice, fault soak, serial loop, cutover, legacy deletion,
complexity budget and no-P0/P1 review gate all pass. Do not immediately build BusExecutor, other
providers/topologies, multi-review, UI, Coordinator failover, credential management or real-model
soaks. Further work must come from normal personal usage evidence.

