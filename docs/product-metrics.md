# Product Metrics

This document defines the observable metrics for Agent Workflow. It separates the product into two distinct measurement modes:

- infrastructure-development mode, when we are building Agent Workflow and its adjacent infrastructure;
- downstream-operation mode, when Agent Workflow is used to develop other projects.

The metrics here are intentionally based on facts we can actually observe in the repo, artifacts, and workflow run records. Do not invent precise token, price, or provider-quota APIs that the system does not already expose.

## Metric Principles

1. Measure what the workflow can prove.
2. Prefer counts, roles, reason codes, artifact IDs, and task identifiers over estimated economics.
3. Separate build-time success from downstream product value.
4. Treat a single high-value model call as meaningful only when its role and reason are known.
5. Keep the metric set small enough to compute from TaskCards, reports, and run context.

## Infrastructure-Development Metrics

These metrics describe whether the Agent Workflow product itself is converging safely.

| Metric | What it tells us | Source |
|---|---|---|
| Repository truth consistency | Whether docs, artifacts, and implementation agree | README, ADRs, TaskCards, reports, tests |
| Fail-closed behavior | Whether invalid states stop instead of silently routing | validation results, tests |
| Artifact integrity | Whether required handoff artifacts exist and are well formed | TaskCards, reports, decisions |
| Rework determinism | Whether local failures close through deterministic rework | implementation and review outcomes |
| Recovery evidence | Whether interrupted or resumed work can be proven from files | run context, logs, checkpoints |
| Cross-machine evidence | Whether dogfood proves the intended runner/listener boundaries | operations artifacts, PR evidence |
| Test coverage of contracts | Whether the contract surface is protected by regression tests | test suite |
| Human intervention points | Where a human still had to step in | task notes, review notes, decision packets |
| Documentation alignment | Whether docs match current repository facts | docs review and repo checks |

For this mode, the question is not “did we use fewer high-value model calls?” The question is “did we build the method safely and prove the boundaries in real work?”

## Downstream-Operation Metrics

These metrics describe whether Agent Workflow is reducing downstream dependence on scarce high-value capacity.

| Metric | What to record |
|---|---|
| Completed TaskCards | Count of TaskCards that reached completion |
| High-value model invocations | Total count of high-value model calls |
| High-value model invocations per completed TaskCard | Ratio of high-value model calls to completed TaskCards |
| High-value-model-free TaskCard rate | Share of completed TaskCards that required no high-value model call |
| High-value model role distribution | Which roles triggered high-value model usage |
| Lower-cost model invocations | Total count of lower-cost model calls |
| Escalation count | Count of upgrades to high-value models |
| Escalation reason code | Coded reason for each escalation |
| Deterministic rework count | Count of non-escalating local rework loops |
| Human intervention count | Count of times a human had to resolve the run |
| Phase or milestone high-value calls | High-value model calls attributed to phase or milestone boundaries |
| TaskCard references | The specific TaskCard or TaskCards associated with each high-value model call |
| Path classification | Whether the call happened on the normal path or the upgrade path |

### Required fields for each recorded high-value model call

When a high-value model is used, record:

- project and workflow/run identifier;
- role;
- reason code;
- TaskCard ID or TaskCard path;
- phase or milestone association, if any;
- whether the call happened on the normal path or an upgrade path;
- whether the call resolved the issue or merely informed the next step.

Avoid recording exact token or cost numbers unless the runtime already exposes them reliably. If the data is unavailable, leave it absent and note the gap instead of approximating.

## Reason Codes

Use stable reason codes to make the data comparable across runs.

Suggested downstream reason codes:

- `architecture_planning`
- `architecture_reopen`
- `blocked_review`
- `milestone_acceptance`
- `high_risk_change`
- `insufficient_evidence`
- `goal_changed`
- `deterministic_rework_exhausted`

These codes are descriptive labels, not a generic policy engine.

## First Dogfood Suggestion

The first formal dogfood should use a small, adjustable target rather than a permanent quota.

Suggested starting shape:

- at least 3 real TaskCards;
- at least 2 TaskCards that use no high-value model;
- normal `PASS` and `REQUEST_CHANGES` paths should stay on lower-cost models when evidence is sufficient;
- `BLOCKED`, architecture reopening, and milestone acceptance may use a high-value model;
- every high-value model call must have a role and a reason code.

Treat this as a first-round suggestion, not a fixed product contract. If the project discovers a better threshold, update the suggestion rather than forcing the workflow to fit the number.

## Non-Goals

- Do not create a universal token accounting layer.
- Do not require exact cost data from every provider.
- Do not require provider-specific quota APIs.
- Do not turn metrics into an optimization target that overrides product correctness.
- Do not hide the difference between infrastructure-development mode and downstream-operation mode.

## Risks

- If metrics are too coarse, the product may claim value it has not demonstrated.
- If metrics are too exact, they may depend on data that some runtimes cannot provide.
- If the same metric is used in both modes without context, it can create false conclusions.
- If upgrade reasons are left free-form, later comparisons will be noisy.

## Reporting Shape

The minimum useful downstream report should be able to answer:

1. How many TaskCards completed?
2. How many high-value model calls happened?
3. Why did each one happen?
4. Which role triggered it?
5. Did the run stay on the normal path or move to an upgrade path?
6. How much deterministic rework closed without escalation?

That is enough to compare the current method against the older “high-value model everywhere” baseline without pretending that precise token economics are always available.
