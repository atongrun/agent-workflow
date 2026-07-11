# Architecture

Agent Workflow is a **handoff protocol** — a layer of portable markdown contract templates plus a thin validation CLI. It describes *what* to do, *who* is responsible, *what goes in and out*, and *when to stop*. The core never executes, schedules, or orchestrates anything. Agents, models, and runtimes live entirely outside this project.

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

This is the heart of the protocol: a downstream stage takes an upstream stage's artifact as its input. The handoff is a file with a stable shape, so anyone — any model, any tool, any human — can produce or consume it.

## Design Principles

1. **Contract First**: Stabilize schemas and templates before anything else. The contract is the product.
2. **Portable Core**: The core runs anywhere Python runs — no special infrastructure, no runtime.
3. **No Model Lock-in**: Roles and workflows never reference specific models or agents.
4. **Auditable**: Every handoff and artifact is traceable through files.
