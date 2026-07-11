# Development Workflow MVP

## Product Rule

Agent Workflow codifies one practical development method: establish the current truth, plan progressively, challenge architecture only when necessary, close deterministic failures locally, compress decisions, and force convergence.

**Use first, abstract second.** A requirement does not enter the core architecture until a real project demonstrates it. Generic runtimes, remote scheduling, UI, and plugin systems may reuse mature projects later.

**Stateless by design.** `awf` renders the next packet and validates submitted artifacts — it does **not** hold run state, execute models, or decide transitions. The human plus the chosen agent client drive progression. Any run scaffolding on disk (see below) is inspectable output the user owns, not a controller's private state machine. See the root [`constitution.md`](../constitution.md) for the full method rules.

## What “Usable” Means

The MVP is not usable until a user can start from a goal, receive the next actionable packet, submit an artifact, and continue through architecture, phase planning, TaskCard execution, review, and decision. `awf validate` and `awf inspect` alone do not satisfy this bar.

The commands below are the MVP usage contract. They are not implemented in the current Phase 0 CLI.

## Quick Start: Continue Agent Bus

Install Agent Workflow, then start a brownfield run:

```bash
pip install -e ".[dev]"

awf init \
  --project ../agent-bus \
  --goal examples/agent-bus-dogfood/goal.md \
  --mode dual \
  --executor manual \
  --reviewer manual \
  --decider manual
```

The user supplies only the goal and a few choices. Agent Workflow inspects the repository and generates its internal Workflow/Profile configuration under the run directory. YAML is inspectable output, not the primary interface.

`awf init` must create:

```text
../agent-bus/.awf/runs/<run-id>/
├── run.json
├── baseline.md
├── generated/workflow.yaml
├── generated/profile.yaml
├── inbox/next-stage.md
└── artifacts/
```

The shortest user path is:

| Step | System does automatically | Manual handoff allowed | Durable output |
|---|---|---|---|
| Initialize | Inspect the checkout, generate internal configuration, open the run | Confirm the goal and role choices | Baseline and run manifest |
| Architecture | Build role packets, enforce challenge scope and three-round convergence | Invoke architect(s) and submit responses | Frozen ArchitectureRecord or user decision request |
| Plan | Keep future phases coarse and detail only the current phase | Submit the planner response | PhasePlan and current TaskCard |
| Execute and review | Route packets, validate artifacts, allow only deterministic rework | Run the executor/tests/reviewer and import reports | Implementation, test, and review reports |
| Decide | Compress evidence and exclude full diffs by default | Final decider approves, rejects, or requests one bounded rework | DecisionPacket and Decision |
| Continue | Select the next task or phase-advance packet | Confirm phase evidence when requested | Next TaskCard or next PhasePlan |

Ask what happens next:

```bash
awf status --project ../agent-bus
awf next --project ../agent-bus
```

`awf next` prints the active role, required input, expected artifact, and packet path. In the MVP, model invocation may remain manual: give `next-stage.md` to the named architect, executor, reviewer, or decider; save the response as an artifact; then import it:

```bash
awf submit --project ../agent-bus --artifact /path/to/result.md
```

Repeat `awf next` and `awf submit`. `awf submit` validates the artifact's structure against its schema and writes the next packet based on the workflow definition. It does not run models or maintain a private state machine — progression is a function of which artifacts exist on disk, which the user can inspect and edit directly.

After architecture convergence, `awf status` must expose the frozen `ArchitectureRecord`, detailed current `PhasePlan`, and current `TaskCard`. After execution, local verification, and first-line review, it must expose the `ImplementationReport`, `TestReport`, `ReviewReport`, compressed `DecisionPacket`, and final `Decision`.

When a task completes, `awf next` selects the next TaskCard. When all current-phase exit criteria have evidence, it emits a phase-advance packet and then details only the next phase.

## Brownfield Default

For an existing project, initialization produces a short baseline before any architecture work:

- capabilities already implemented and actually verified;
- current constraints and accepted boundaries;
- unfinished work and the next explicit milestone;
- current blockers and available test evidence.

The default path is:

`Current Baseline → Next Milestone → Incremental Plan → Current TaskCard → Execute and Verify`

Existing working behavior is the baseline. Do not restart from whole-system architecture or propose broad refactors because a cleaner design exists. Reopen a local architecture decision only when the current architecture blocks the milestone, the core path cannot run, or the project goal changed. Historical debt, general optimization, and future extensions go to `Later` and cannot block the current task.

## Architecture and Review Limits

- Single mode uses a separate, limited self-challenge invocation.
- Dual mode uses one primary architect and one goal-bounded challenger. The primary owns convergence.
- By round three, architecture must be `frozen`, `frozen_with_known_risk`, or `waiting_human`.
- First-line review can return only deterministic failures: compile/test failure, failed acceptance criterion, missing required evidence, or clear TaskCard violation.
- Architecture tradeoffs, scope disputes, and non-blocking improvements go into the DecisionPacket. Optional improvements never block task or phase completion.

## First Real Proof

The first dogfood target is the bounded Agent Bus diagnostic slice in [the complete example](../examples/agent-bus-dogfood/README.md). The run must record manual handoffs, architecture rounds, deterministic rework, DecisionPacket size, and whether targeted context was requested.

Until that run completes, do not extend the UI, cross-machine automation, generic plugin system, complex runtime, or generalized orchestration contracts.
