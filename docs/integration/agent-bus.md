# Agent Bus Integration

This document defines how Agent Workflow integrates with [Agent Bus](https://github.com/atongrun/agent-bus) — the cross-machine durable event relay.

## Integration Model

```
Agent Workflow                    Agent Bus
┌──────────────┐                ┌──────────────┐
│ Workflow     │── publish ────►│ POST /events │
│ Engine       │                │              │
│              │◄── subscribe ──│ SSE stream   │
└──────────────┘                └──────────────┘
```

- Agent Workflow **produces** workflow events.
- Agent Bus **transports** them to remote agents.
- Agent Workflow **owns** workflow state.
- Agent Bus **does not** interpret business events or decide next stages.

## Agent Workflow Events

Agent Workflow publishes these event types:

| Event Type | When |
|------------|------|
| `workflow.run.created` | Workflow run initialized |
| `workflow.run.started` | First stage begins |
| `workflow.run.completed` | Terminal state reached |
| `workflow.run.failed` | Unrecoverable error |
| `workflow.stage.ready` | Stage inputs available |
| `workflow.stage.started` | Stage execution begins |
| `workflow.stage.waiting` | Stage waiting for external input |
| `workflow.stage.completed` | Stage finished successfully |
| `workflow.stage.failed` | Stage failed |
| `workflow.artifact.published` | Artifact stored and available |
| `workflow.decision.required` | Arbiter decision needed |
| `workflow.decision.recorded` | Decision recorded |
| `workflow.memory.context.requested` | Context query sent to AI Memory |
| `workflow.memory.context.available` | Context returned from AI Memory |
| `workflow.memory.write-candidates.published` | Memory candidates submitted |

## Event Structure

Every event carries:

```json
{
  "eventId": "uuid",
  "eventType": "workflow.stage.completed",
  "schemaVersion": "1.0",
  "occurredAt": "2026-07-07T12:00:00Z",
  "workflowRunId": "run-123",
  "stageRunId": "stage-456",
  "taskId": "task-789",
  "correlationId": "run-123",
  "causationId": "stage-start-event-id",
  "producer": {
    "project": "agent-workflow",
    "component": "workflow-engine"
  },
  "payload": {}
}
```

## Design Rules

1. **Agent Workflow owns workflow state.** Agent Bus transports events; it does not interpret them.
2. **Agent Bus does not decide next stages.** That is the workflow engine's responsibility.
3. **All events support idempotent processing.** Consumers use `eventId` for deduplication.
4. **`correlationId` chains a workflow run.** All events for the same run share the same `correlationId`.
5. **`causationId` links cause and effect.** The event that triggered the current event.
6. **Agent Bus does not store full artifact bodies.** It passes artifact references or small event payloads. Large artifacts live in the Artifact Store.
7. **Event types are namespaced under `workflow.*`** to avoid collisions with other Agent Bus producers.

## Current Agent Bus Compatibility

*Based on inspection of `agent-bus` v0.1 at `github.com/atongrun/agent-bus`.*

### Confirmed Interfaces

| Agent Bus Feature | Status | Notes |
|------------------|--------|-------|
| `POST /events` | ✅ Available | Accepts `from_agent`, `to_agent`, `type`, `payload` |
| `GET /events/stream?agent=` | ✅ Available | SSE stream with replay for un-ACKed events |
| `POST /events/{id}/ack` | ✅ Available | Acknowledges event processing |
| `GET /health` | ✅ Available | Health check (no auth) |
| Bearer token auth | ✅ Available | Single shared token |
| Event persistence (SQLite) | ✅ Available | Events stored before delivery |
| At-least-once delivery | ✅ Available | Events remain pending until ACKed |

### Known Gaps

| Gap | Impact | Resolution |
|-----|--------|------------|
| Agent Bus event schema uses `from_agent`/`to_agent`, not producer/consumer model | Agent Workflow events need adaptation | Phase 2 adapter will map workflow events to agent-bus wire format |
| Agent Bus event types are ad-hoc (`task:new`, `pr:ready`, etc.) | No standard event taxonomy | Agent Workflow namespace (`workflow.*`) avoids collisions |
| No event filtering by type in SSE stream | Consumers receive all events for their agent | Acceptable for Phase 2 — filter client-side |
| Single shared token | No per-agent access control | Acceptable for Phase 2 single-user setup |
| No dead-letter queue | Failed events not retried automatically | Phase 4 consideration |

### Deferred to Phase 2

- Production `AgentBusAdapter` implementation
- Event type mapping layer
- Client-side event filtering
- Retry with backoff for publish failures

### TODO

- [ ] Define stable Agent Bus event wire format alignment (Phase 2)
- [ ] Implement `AgentBusAdapter` that maps workflow events to agent-bus `POST /events` format (Phase 2)
- [ ] Test cross-machine workflow stage dispatch via Agent Bus (Phase 2)
