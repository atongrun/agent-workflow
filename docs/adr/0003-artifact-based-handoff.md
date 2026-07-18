# ADR-0003: Artifact-Based Handoff

**Status:** Accepted; amended 2026-07-18
**Date:** 2026-07-07

## Context

Free-form chat does not provide a durable, auditable link between task scope, implementation,
verification, Review verdict, and final decision. A fresh client or machine must be able to resume
without hidden conversation history.

## Decision

Formal Stage handoffs use structured, versioned Artifacts. The Artifact chain in Repository Truth,
together with explicit Run Context, is the recoverable source of Workflow evidence.

Every published Artifact identifies its type, creator role, upstream references, and structured
content. A TaskCard must be self-contained for execution. ReviewReport and Decision remain distinct:
the first-line Reviewer returns `PASS`, `REQUEST_CHANGES`, or `BLOCKED`; the Decider records
`approve`, `request_changes`, `reject`, or `escalate`.

## Chat, Memory, and Artifacts

| Need | Source |
|---|---|
| Formal task/Stage handoff | Versioned Artifact |
| Current Stage/branch/retry/escalation | Run Context |
| Real-time debugging | Transient chat/logs |
| Long-term/private background | AI Memory |
| Final task/Phase decision | Decision Artifact |

AI Memory may help a Planner create a TaskCard, but it does not replace the Artifact or act as a
mandatory Executor dependency. There is no core-owned Artifact Store service or port.

## Consequences

- Every formal Stage produces the required Artifact.
- Downstream roles read the Artifact, not upstream chat history.
- Published Artifacts are treated as stable evidence; corrections create an explicit revision or
  successor rather than silently rewriting history.
- Transport may carry Artifact references or bounded content, but transport success alone does not
  mean the Workflow transition is valid.
