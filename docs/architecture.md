# Architecture

Agent Workflow is a **development method and handoff protocol** — portable contract templates plus
a thin validation CLI. It describes *what* to do, *who* is responsible, *what goes in and out*, and
*when to converge, rework, escalate, or stop*. The core never executes, schedules, or orchestrates.
Agents, models, transport, memory, and runtimes live outside the core.

The method contract is captured in a single file at the repository root: [`constitution.md`](../constitution.md). Read that first for the normative rules; this document explains how the pieces fit together.

## Startup Guarantee

The core MUST be usable with only:

- Python 3.11+
- A filesystem
- `PyYAML` and `jsonschema` (pip-installable)

No external services, databases, message brokers, or agent runtimes are required to run validation or inspection. If it needs local files and Python, it runs.

## Artifact-Based Handoff

Agents communicate through structured artifacts, not chat history.

```
Stage A (planner)      Stage B (implementer)
    │                        │
    ├── TaskCard ───────────►│ reads TaskCard
    │                        ├── ImplementationReport ──► Stage C (tester)
    │                        │                            reads ImplementationReport
```

Every artifact carries:
- A unique `artifactId`
- `workflowRunId` and `stageRunId` for traceability
- `createdBy` (role) for accountability
- `sourceRefs` linking to upstream artifacts
- Structured `content` for machine consumption

This is the heart of the protocol: a downstream stage takes an upstream stage's artifact as its
input. Repository Truth holds the versioned Artifact chain; separate, inspectable Run Context says
which Stage and Artifact are current. AI Memory may inform planning but is neither the Artifact
source of truth nor a required Executor dependency.

## Design Principles

1. **Use First, Abstract Second**: stabilize only transition-critical contracts demonstrated by
   real project use.
2. **Portable Core**: The core runs anywhere Python runs — no special infrastructure, no runtime.
3. **No Model Lock-in**: Roles and workflows never reference specific models or agents.
4. **Auditable**: Every handoff and artifact is traceable through files.
5. **Capacity Isolation**: downstream normal work stays in the lower-cost execution chain; named
   high-value-model escalation is recorded and exceptional.
