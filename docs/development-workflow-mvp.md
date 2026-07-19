# Development Workflow MVP

## Product Rule

The MVP is a usable, model-agnostic development method that makes high-value-model participation
explicit and exceptional in downstream operation. It does not minimize all model tokens, and it
does not constrain high-value-model use while critical infrastructure is being built.

The stable contract is:

- progressive planning and bounded architecture convergence;
- self-contained TaskCards and auditable handoffs;
- lower-cost execution, verification, first-line review, and deterministic rework by default;
- named escalation to a high-value model for difficult decisions and milestone acceptance;
- forced convergence and explicit completion evidence.

`awf` remains stateless and provider-neutral. It may validate or render inspectable Artifacts, but it
must not become a model runner, scheduler, private state machine, arbitrary DAG engine, transport,
or memory service.

## What “Usable” Means

A usable run can progress through:

```text
User goal → Architecture / Planning → PhasePlan → TaskCard → Dispatch → Execute → Test
→ Review → Decision → Merge or deterministic rework → Next TaskCard
→ Phase or Milestone completion
```

The current CLI only provides `validate`, `inspect`, and `version`; the run commands shown in older
examples are target ideas, not implemented behavior. MVP usability may first be proven through
manual, file-based handoff. A generic controller is not a prerequisite.

## Roles and Model Assignment

Initial product roles are Architect/Planner, Executor, Reviewer, optional Tester, and Decider. The
current resource names `implementer` and `arbiter` map to product-facing Executor and Decider.

- Infrastructure development may assign high-value models to any role when quality or safety
  warrants it.
- Downstream operation assigns lower-cost models to frequent bounded roles by default.
- A model assignment is run evidence, not part of Role or Workflow schema.

## Normal and Escalation Paths

Normal path:

```text
Planner / task generator → Executor → deterministic verification → first-line Reviewer
→ PASS or deterministic REQUEST_CHANGES → next TaskCard
```

The first-line Reviewer has no architecture veto. `REQUEST_CHANGES` requires deterministic evidence
such as a failing command, unmet acceptance criterion, missing Artifact, or exact TaskCard
violation. Optional advice remains non-blocking.

Escalation to a high-value model requires a recorded role and reason code. Allowed categories are
fundamental ambiguity, architecture reopen, genuine `BLOCKED`, exhausted bounded rework,
predefined high risk, changed project goal, insufficient evidence, or Phase/Milestone acceptance.

## Artifact and Context Contract

The minimum auditable chain is:

```text
ArchitectureRecord → PhasePlan → TaskCard → ImplementationReport → TestReport
→ ReviewReport → DecisionPacket → Decision
```

The TaskCard must let a fresh-session Executor start from the repository, project `AGENTS.md`, and
listed inputs. Planner/Architect may consult AI Memory, but required task facts must be compressed
into the TaskCard. Run Context records the current Stage, Artifact, branch/commit/PR, retries, and
escalation; it must remain inspectable and recoverable.

## First Formal Downstream Dogfood

The first product proof must use a real downstream software project rather than Agent Workflow,
Agent Bus, AI Memory, or another supporting infrastructure project. One architecture/phase plan
should drive multiple bounded TaskCards.

Suggested first-run evidence targets (adjustable, not permanent contracts):

- at least three completed real TaskCards;
- at least two completed without a high-value-model invocation;
- normal `PASS` and deterministic `REQUEST_CHANGES` chains remain high-value-model-free;
- each high-value invocation records project, TaskCard, role, reason code, and normal/escalation
  path;
- `BLOCKED`, architecture reopen, predefined high risk, insufficient evidence, and Milestone
  acceptance may invoke a high-value model;
- the result is compared with the project's earlier high-value-model-led baseline.

Record counts and roles first. Do not invent exact token, price, or quota data when providers do not
expose it. Full metric definitions are in [`product-metrics.md`](product-metrics.md).

## Agent Bus Operations Evidence

The repository's `scripts/` surface has already proven important engineering boundaries through
real Agent Bus dogfood: exact checkout, trusted process/postflight gates, commit/push and remote-SHA
proof, durable handler evidence, and a Windows handler-return/ACK gate. It remains outside the core.

The Reviewer now validates a structured ReviewReport and routes `PASS`, `REQUEST_CHANGES`, and
`BLOCKED` through fail-closed deterministic logic. That boundary is covered by tests, but it has
not yet been accepted as one fresh, uninterrupted cross-machine semantic loop. A live run must
still prove dispatch through verdict routing and record the merge or deterministic-rework and
next-TaskCard continuation evidence before the operations surface can claim a complete
cross-machine chain. See
[`tasks/reviewer-verdict-routing-implementation-report.md`](tasks/reviewer-verdict-routing-implementation-report.md).

## Acceptance Criteria

- Product docs consistently distinguish infrastructure development from downstream operation.
- Role and Artifact contracts are vendor-neutral.
- A fresh-session Executor does not require AI Memory or planner chat history.
- Ordinary deterministic failures close inside the lower-cost chain.
- Every high-value invocation has an auditable role and reason code.
- One plan drives multiple TaskCards and the suggested first-run capacity-isolation targets are
  measured against a baseline.
- No generic runtime, Agent Host integration, Plugin SDK, arbitrary DAG, provider billing adapter,
  or transport/memory protocol change is required.

## Later

Only evidence from repeated downstream runs may justify additional render/validation helpers,
operations productization, or external runtime composition. Agent Host remains deferred.
