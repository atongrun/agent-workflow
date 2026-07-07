# ADR-0003: Artifact-Based Handoff

**Status:** Accepted  
**Date:** 2026-07-07

## Context

Agent-to-agent communication today typically uses free-form chat messages. This is problematic:
- No structured state that can be validated.
- No audit trail linking decisions to evidence.
- No machine-readable format for downstream tooling.
- Ambiguous authority — who decided what?

## Decision

**Formal handoffs between stages use structured Artifacts, not chat logs.**

### Artifact Requirements

Every artifact must carry:
- `artifactId` — unique identifier
- `artifactType` — one of the defined types (TaskCard, ImplementationReport, etc.)
- `workflowRunId` and `stageRunId` — traceability
- `createdBy` — role and runner attribution
- `sourceRefs` — links to upstream artifacts
- `content` — structured payload

### Chat vs. Artifacts

| Use Case | Mechanism |
|----------|-----------|
| Formal stage handoff | Artifact |
| Real-time debugging | Chat (transient) |
| Final decisions | Artifact (Decision) |
| Workflow state | Artifact store |
| Human-readable summary | Artifact content is both machine and human readable |

### What Artifacts Are Not

- Chat logs are not the authoritative state of a workflow run.
- Artifacts do not replace real-time communication — they augment it with structure.
- Artifacts are not immutable (within a stage run) — but once published to downstream stages, they should be treated as stable.

## Consequences

- Every stage produces at least one artifact.
- Downstream stages read artifacts, not chat history.
- The Artifact Store is the source of truth for workflow state.
- Human-readable summaries live alongside machine-readable data in the same artifact.
