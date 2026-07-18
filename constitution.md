# Development Constitution

This file is the normative development method and handoff protocol for Agent Workflow. It defines
what happens, who is responsible, which Artifact proves a transition, and when work must converge,
rework, escalate, or stop. It does not run models, schedule agents, transport events, or manage an
agent client's internal reasoning loop.

## 1. Product Objective and Operating Modes

Agent Workflow optimizes a **downstream project's continuing dependence on high-value-model
capacity**, not total model calls or total tokens.

- A **high-value model** has stronger capability for the decision at hand but is expensive or
  capacity-limited.
- A **lower-cost model** is suitable for frequent, bounded work. An **execution model** is the model
  currently assigned to Executor, Tester, or first-line Reviewer duties.

These are vendor-neutral roles, not permanent labels. Projects record the actual model/runtime used
as run evidence without putting a vendor in the method contract.

Two modes must not be confused:

1. **Infrastructure development.** Critical infrastructure may use high-value models freely for
   architecture, implementation, safety, failure diagnosis, strong review, and real-environment
   validation. Reliability and evidence quality take precedence over reducing such use.
2. **Downstream operation.** High-value models concentrate on architecture, exceptional judgment,
   explicit escalation, and Phase/Milestone acceptance. Lower-cost models handle bounded planning,
   execution, testing, first-line review, deterministic rework, and Artifact preparation.

## 2. Project Mode

Every project declares one starting mode:

- **Greenfield** — capture goal and hard constraints, converge the architecture needed for the
  first milestone, create a coarse PhasePlan, detail the current phase, then issue a TaskCard.
- **Brownfield** — begin from a verified baseline. This is the default and primary target.

For brownfield work, record verified capabilities, accepted constraints, unfinished work, the next
milestone, blockers, and available test evidence. The default path is:

```text
Current Baseline → Next Milestone → Incremental Plan → Current TaskCard → Execute and Verify
```

Existing verified behavior is the baseline. Debt, optional optimization, and future extensions are
`Later`; they do not block the current milestone.

## 3. Architecture Convergence

- Single-architect mode uses one Architect plus a separate, limited self-challenge invocation.
- Dual-architect mode uses one primary Architect and one goal-bounded challenger; the primary owns
  convergence.
- By round three, the outcome must be `frozen`, `frozen_with_known_risk`, or `waiting_human`.
- Reopen a frozen decision only when it blocks the milestone, the core path cannot run, a
  predefined high-risk change requires it, or the project goal changed.

No Stage or Reviewer may reopen architecture merely for preference or optimization.

## 4. Progressive Planning

- Keep future phases coarse; detail only the current phase.
- A Phase advances only when every current-phase exit criterion has auditable evidence.
- A `TaskCard` is the smallest executable unit: background, one goal, scope, explicit exclusions,
  inputs, acceptance criteria, verification, risks, and required outputs.
- Planner/Architect decisions that affect execution must be compressed into versioned Artifacts.

## 5. TaskCard and Knowledge Boundary

A TaskCard is the self-contained execution context for one current task. A fresh-session Executor
must be able to start from:

- the TaskCard;
- the repository content and project `AGENTS.md`;
- explicitly listed inputs.

The Executor must not need the Planner's chat history or be forced to search AI Memory for required
facts. A Planner or Architect may read AI Memory and copy only the current, non-private facts needed
for success into the TaskCard. Do not copy the entire memory corpus.

Information belongs in one of three places:

| Layer | Required content |
|---|---|
| Repository Truth | Versioned code, project rules, ArchitectureRecord, PhasePlan, TaskCard, reports, decisions, tests, and PR evidence |
| Run Context | Current Stage, Artifact, role, branch/commit/PR, retry, failure, and escalation status |
| AI Memory | Long-term background, historical explanation, private environment facts, preferences, and cross-project knowledge |

Task success requirements belong in auditable Artifacts. AI Memory is a potential upstream source,
not an Executor runtime dependency and not the authority for the next Workflow transition.

Before delegation, the Planner verifies that the goal is singular, scope is explicit, acceptance
criteria are observable, commands are real, the context is sufficient for a fresh session, and the
task advances the current milestone. See [`templates/artifacts/task-card.md`](templates/artifacts/task-card.md).

## 6. Normal Path

The preferred downstream path is:

```text
Planner / task generator
→ Executor
→ deterministic verification
→ first-line Reviewer
→ PASS or deterministic rework
→ next TaskCard
```

An optional Tester may provide separate evidence. A Decider may initially be the Architect. Lower-
cost models should complete this normal path where task boundaries and evidence permit.

The longer project loop is:

```text
User goal → Architecture / Planning → PhasePlan → TaskCard → Dispatch → Execute → Test
→ Review → Decision → Merge or deterministic rework → Next TaskCard
→ continue until Phase or Milestone completion
```

## 7. Deterministic Rework

`REQUEST_CHANGES` returns to the lower-cost execution chain only for deterministic failures:

- compile or test failure;
- an unmet acceptance criterion;
- an allowed-path or explicit TaskCard violation;
- a missing required ImplementationReport, TestReport, ReviewReport, or other evidence;
- a secret/privacy violation in a versioned Artifact or change.

Deterministic rework is bounded by the current PhasePlan or TaskCard. Exceeding that bound escalates;
it does not create an infinite loop. Style preferences, optional improvements, and a Reviewer's
personal architecture preference are advisory and never consume rework or block completion.

## 8. Escalation

A high-value model may be invoked when—and only when—the run records a role and reason code for one
of these conditions:

- fundamental goal or requirement ambiguity;
- a TaskCard cannot be produced within frozen architecture;
- frozen architecture must be reopened;
- the Reviewer returns genuine `BLOCKED` with evidence;
- bounded deterministic rework is exhausted;
- a predefined high-risk scope is entered;
- a Phase or Milestone acceptance point is reached;
- the project goal changed;
- available evidence cannot support a reliable decision.

Ordinary test failure, missing evidence, allowed-path violation, normal `REQUEST_CHANGES`, style,
and non-blocking optimization do not escalate by default.

## 9. Reviewer and Decider Authority

The first-line Reviewer uses exactly these semantic verdicts:

- `PASS` — acceptance and evidence are sufficient for the next decision/merge gate.
- `REQUEST_CHANGES` — one or more deterministic failures must return to the Executor.
- `BLOCKED` — evidence shows the task cannot safely progress inside the current TaskCard and frozen
  architecture.

The Reviewer does not edit or merge code, approve its own work, reopen architecture, or block on
advisory findings. A final Decider uses `approve`, `request_changes`, `reject`, or `escalate` and owns
the project-level decision. Reviewer verdicts and Decider decisions are distinct contracts.

## 10. Required Artifacts

| Stage | Product role | Current schema role | Required Artifact |
|---|---|---|---|
| architecture / plan | Architect / Planner | `planner` | `ArchitectureRecord`, `PhasePlan`, then `TaskCard` |
| execute | Executor | `implementer` | `ImplementationReport` |
| test (optional) | Tester | `tester` | `TestReport` |
| first-line review | Reviewer | `reviewer` | `ReviewReport` |
| compress | Summarizer | `summarizer` | `DecisionPacket` |
| decide | Decider | `arbiter` | `Decision` |

The v1alpha1 Artifact schema recognizes `ArchitectureRecord` and `PhasePlan` while keeping their
content open during initial dogfood; their templates define the current minimum handoff shape. Each
formal handoff uses an Artifact, not a chat transcript.

## 11. External Boundaries

- Agent Workflow owns method semantics and Artifact contracts; it does not execute or transport.
- Agent Bus owns endpoint/agent identity, delivery, ACK, retry, and failure propagation. It does
  not interpret Workflow Stage, Review verdict, or completion semantics.
- AI Memory owns long-term and private context. It does not replace versioned Artifacts or select
  the next Stage.
- A future external runtime may compose these projects. Agent Workflow currently specifies no
  Agent Host integration, Plugin SDK, provider adapter, or generic runtime.

## 12. Privacy Discipline

Versioned Artifacts must contain no credentials, real private endpoints, SSH aliases, or absolute
personal paths. Use placeholders, repository-relative paths, and environment-variable names.
Private concrete values remain in the operator's private memory/environment. A leak is a
deterministic failure.

## 13. Completion

A Task completes only when required Artifacts and verification evidence exist, deterministic
failures are closed, and the authorized decision is recorded. A Phase/Milestone completes only when
its exit criteria have evidence and any required high-value acceptance is recorded. Technical event
delivery alone is never proof of Workflow completion or downstream product value.
