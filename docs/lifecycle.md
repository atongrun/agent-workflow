# Stage and Workflow Lifecycle

## Stage Lifecycle

Every stage in a Workflow Run progresses through a fixed lifecycle:

```
                  ┌──────────┐
                  │ pending  │
                  └────┬─────┘
                       │ conditions met
                  ┌────▼─────┐
                  │  ready   │
                  └────┬─────┘
                       │ runner starts
                  ┌────▼─────┐
                  │ running  │
                  └────┬─────┘
           ┌───────────┼───────────┐
           │           │           │
    ┌──────▼──┐ ┌──────▼──┐ ┌──────▼──┐
    │ waiting │ │ blocked │ │completed│
    └────┬────┘ └────┬────┘ └─────────┘
         │           │
         └─────┬─────┘
               │
         ┌─────▼─────┐
         │  failed   │
         └───────────┘
```

| State | Meaning |
|-------|---------|
| `pending` | Stage is defined but dependencies not yet met |
| `ready` | All inputs available, awaiting runner |
| `running` | Runner is executing the stage |
| `waiting` | Runner is waiting for external input (e.g., human approval) |
| `blocked` | Stage cannot proceed — resource missing, permission denied |
| `completed` | Stage finished successfully |
| `failed` | Stage encountered an unrecoverable error |
| `cancelled` | Stage was explicitly cancelled |

---

## Workflow Run Lifecycle

A Workflow Run is a single execution of a workflow definition:

```
                  ┌──────────┐
                  │ created  │
                  └────┬─────┘
                       │
                  ┌────▼─────┐
                  │ running  │
                  └────┬─────┘
           ┌───────────┼───────────┐
           │           │           │
    ┌──────▼──┐ ┌──────▼──┐ ┌──────▼──┐
    │ waiting │ │ blocked │ │completed│
    └────┬────┘ └────┬────┘ └─────────┘
         │           │
         └─────┬─────┘
               │
         ┌─────▼─────┐
         │  failed   │
         └───────────┘
```

| State | Meaning |
|-------|---------|
| `created` | Run initialized, first stage pending |
| `running` | At least one stage is in progress |
| `waiting` | All active stages are waiting (manual gate, external signal) |
| `blocked` | At least one stage is blocked with no alternative path |
| `completed` | Terminal state reached: `completed`, `rejected`, `cancelled` |
| `failed` | Unrecoverable error in any stage with no failure transition |

---

## Rework Loops

When a stage fails, the workflow can route back to an earlier stage:

```
test (failed) ──→ implement (rework)
review (request_changes) ──→ implement (rework)
decide (request_changes) ──→ implement (rework)
```

Rework loops are defined in `onFailure` transitions. The system does NOT implement automatic retry in Phase 0 — retry policy is deferred to Phase 1.

---

## Terminal States

Every workflow must declare its terminal states:

```yaml
spec:
  terminalStates:
    - completed
    - rejected
    - cancelled
    - failed
```

When a stage transitions to a terminal state (via `onSuccess` or `onFailure`), the Workflow Run ends.

---

## Stage Inputs and Outputs

Each stage declares its expected inputs and produced outputs:

```yaml
- id: implement
  inputs: [TaskCard]
  outputs: [ImplementationReport]
```

The workflow engine (Phase 1+) resolves inputs from upstream artifacts and passes them to the runner. In Phase 0, this is validated structurally but not executed.

---

## Memory Integration Points

Memory reads and writes hook into the stage lifecycle:

- **Before stage starts**: If `memory.read.enabled`, the engine requests context from AI Memory.
- **After stage completes**: If `memory.write.enabled`, the runner can generate `MemoryWriteCandidate` artifacts.

These are defined but not active in Phase 0. See `docs/integration/ai-memory.md`.
