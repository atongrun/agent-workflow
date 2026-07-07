# Architecture

## Three-Plane Separation

Agent Workflow is part of a three-project infrastructure. Each project owns one plane:

```
┌──────────────────────────────────────────────────────┐
│                  Control Plane                        │
│                (Agent Workflow)                       │
│                                                       │
│  Roles · Stages · State · Policy · Artifacts          │
│                                                       │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │ Runner  │  │ Event    │  │ Memory           │    │
│  │ Port    │  │ Bus Port │  │ Port             │    │
│  └────┬────┘  └────┬─────┘  └──────┬───────────┘    │
│       │            │               │                  │
└───────┼────────────┼───────────────┼──────────────────┘
        │            │               │
        ▼            ▼               ▼
┌───────────┐ ┌──────────┐ ┌──────────────┐
│ Runner    │ │ Agent    │ │ AI Memory    │
│ Adapters  │ │ Bus      │ │              │
│           │ │          │ │              │
│ Execution │ │ Event /  │ │ Context /    │
│ Plane     │ │ Transport│ │ Memory       │
└───────────┘ │ Plane    │ │ Plane        │
              └──────────┘ └──────────────┘
```

## Port and Adapter Pattern

The core defines abstract interfaces (Protocols) in `src/agent_workflow/ports/`. Each external system has a corresponding adapter in `src/agent_workflow/adapters/`.

| Port | Purpose | Local Adapter | Production Adapter |
|------|---------|---------------|--------------------|
| `RunnerPort` | Execute stages | `ShellRunner` | Phase 4 |
| `EventBusPort` | Publish/subscribe events | `LocalEventBus` | Phase 2 (agent-bus) |
| `MemoryPort` | Context retrieval, memory writes | `LocalMemory` | Phase 3 (ai-memory) |
| `ArtifactStorePort` | Store and retrieve artifacts | `FilesystemArtifactStore` | Built-in |

## Startup Guarantee

The core MUST be operational with only:

- Python 3.11+
- A filesystem
- `PyYAML` and `jsonschema` (pip-installable)

No external services, databases, or message brokers are required to run validation, inspection, or `awf` CLI commands.

## Data Flow

```
User/Task → Workflow Definition → Stage Sequence → Runner → Artifacts → Next Stage
                                    ↑                               │
                                    └─── Validation (schemas)       │
                                    ↑                               │
                              Binding Profile ←───────── Artifact Store
```

1. A Workflow Definition specifies stages and roles.
2. A Binding Profile maps roles to runners.
3. Before execution, all resources pass schema and semantic validation.
4. Each stage is dispatched to its runner with the required inputs.
5. The runner produces artifact files.
6. Artifacts are stored in the Artifact Store.
7. Downstream stages read artifacts as inputs.

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
- `createdBy` (role + runner) for accountability
- `sourceRefs` linking to upstream artifacts
- Structured `content` for machine consumption

## Design Principles

1. **Contract First**: Stabilize schemas and protocols before building engines.
2. **Portable Core**: The core runs anywhere Python runs — no special infrastructure.
3. **Optional Upgrades**: Agent Bus and AI Memory are value-adds, not requirements.
4. **No Model Lock-in**: Roles and workflows never reference specific models or agents.
5. **Auditable**: Every transition and artifact is traceable through files and events.
