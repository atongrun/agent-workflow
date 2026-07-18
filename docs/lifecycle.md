# Stage and Workflow Handoff Semantics

> This file describes the **handoff contract semantics** — not an execution engine. Agent Workflow does not implement scheduling, dispatch, or a runtime. The transitions below define *what a valid handoff looks like*, and are left for whatever agent or human carries out the work to honor.

## Rework Loops

When a stage fails, the workflow can route back to an earlier stage:

```
test (failed) ──→ implement (rework)
review (REQUEST_CHANGES) ──→ implement (deterministic rework)
decide (request_changes) ──→ implement (rework)
```

Reviewer `REQUEST_CHANGES` is valid only for deterministic failure evidence. Reviewer `BLOCKED`
routes to Architect/Decider escalation, not automatic rework. Rework loops are bounded by the
TaskCard or PhasePlan. The contract records the handoff; it does not perform automatic retry.

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

When a stage transitions to a terminal state (via `onSuccess` or `onFailure`), the workflow ends.

---

## Stage Inputs and Outputs

Each stage declares its expected inputs and produced outputs:

```yaml
- id: implement
  inputs: [TaskCard]
  outputs: [ImplementationReport]
```

A downstream stage takes the upstream stage's artifacts as its inputs. This is a declaration of the handoff shape, validated structurally — not an executed data flow.
