# ADR-0007: VNext Bounded Serial Orchestrator

**Status:** Accepted
**Date:** 2026-09-01
**Frozen legacy baseline:** `533a8950e0c675986319b810e7191793ef578871`
**Implementation plan:** [VNext implementation plan](../plans/vnext-implementation-plan.md)

## Context

The RC.2 and legacy Runtime route accumulated more operational machinery than the personal coding
workflow justified. The owner therefore ended RC.2 release closeout and authorized one bounded
VNext viability experiment. The frozen legacy baseline remains a behavioral oracle, failure
evidence, regression reference and rollback reference; it is not the implementation base for more
RC.2 campaigns or a future generic Runtime.

## Decision

VNext is one personal, strictly serial, Plan-driven coding workflow Orchestrator:

```text
AUTHOR -> IMPLEMENT -> REVIEW -> DECIDE -> MERGE -> AUTHOR(next or complete)
```

Each Run has exactly one Coordinator. Architect, Coder and Reviewer are peer workflow Roles; Role,
Provider and Target are separate. The initial and only supported topology is local Pi Architect,
OpenCode Coder on one SSH target, and local Codex Reviewer. Remote hosts run the on-demand
`awf-agent` command and never another Coordinator or background AWF service.

Providers return canonical typed Results. Markdown and natural-language verdict parsing are not a
protocol. One mutable `RunAuthority` is the only workflow authority; immutable `TaskCompletion` and
remote `JobReceipt` are the only other persistent state families. Operations bind an operation ID,
input digest and expected sequence, and accept only one exact matching Result through compare-and-
swap semantics.

Git transports code between hosts. A trusted HostRunner may validate, commit and push only the
frozen current Task branch. The Coordinator alone accepts Results and owns PR creation/reuse, CI,
merge, base-branch observation and Task progression. Reviewer rework remains the same Run, Task,
branch and PR and starts from the exact reviewed head.

The initial execution boundary is `LocalExecutor` and `SSHExecutor`, each exposing only `execute`
and `inspect`. Agent Bus remains an independent asset outside the Golden Path. VNext adds no
listener, service, queue, lease, scheduler, cross-machine state replication, artifact transfer,
credential/IAM subsystem, provider matrix, arbitrary DAG or generic framework.

## Delivery and kill gate

Implementation order is fixed:

```text
Phase 0 -> VNX-01 -> VNX-02 -> mandatory Kill Gate
  -> only on CONTINUE: VNX-03 -> VNX-04 -> VNX-05 -> VNX-06
```

The Kill Gate terminates AWF if the first real Task requires any prohibited infrastructure or if
the slice exceeds the governance limits: five stages, four primary abstractions, at most three
persistent state families, at most six long-lived new core modules, and a hard stop above 2,000
VNext production lines before the vertical slice completes. The gate also asks whether VNext has a
meaningful benefit over SSH, Git Task branches and manual PR operation. There is no third
architecture redesign after a TERMINATE decision.

## Consequences

- PR #189's RC.2 release-ready narrative is closed without merge.
- No `v0.4.0-rc.2` tag or Release is created.
- Legacy cannot create new Runs after cutover and is deleted immediately after VNX-05, leaving one
  production Runtime.
- Reliability is proven primarily with scripted components and one 100-Task soak. There is exactly
  one real-model vertical-slice Run identity for Initial VNext.
- Bus execution, more providers/topologies, same-repository work, UI, multiple reviewers,
  Coordinator failover and credentials remain outside MVP until normal personal use demonstrates a
  need.

