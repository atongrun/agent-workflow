# HTTP contract

Every Host `/v1` route requires `Authorization: Bearer <host token>`. It is intended for a protected server-side proxy. No CORS credentials or tokens belong in the browser. Bodies are JSON, writes require a stable caller-generated `requestId` matching `[A-Za-z0-9._:-]{1,128}`. Reuse that ID only with the exact same task, operation and payload. A duplicate returns the original request/current task and never restarts the effect; changed payload yields HTTP 409. Preserve the ID after an ambiguous response.

Errors: `{ "error": { "code": "...", "message": "..." } }`. HTTP 202 is acceptance, not native completion. A write normally returns `{task, request}`; request status can remain `needs_verification`. Task IDs are UUID-shaped stable strings.

| Method | Path | Body / result |
|---|---|---|
| GET | `/v1/health` | Host liveness only |
| GET | `/v1/overview` | `{tasks,agents,settings}` |
| GET | `/v1/agents` | `{agents}`; native reachability, no synthetic online state |
| GET | `/v1/settings` | `{settings}` |
| PATCH | `/v1/settings` | `{requestId,defaultBranch,branchPrefix}` → `{settings}` |
| GET | `/v1/tasks` | `{tasks}` |
| POST | `/v1/tasks` | `{requestId,title,projectId,repository,goal,acceptanceCriteria,nodeId,planId?}` |
| GET | `/v1/tasks/:id` | `{task}` |
| GET | `/v1/tasks/:id/messages?role=architect` | `{messages,session,history}` from native Pi `get_messages` / `get_entries`; `architect` is the compatibility key for the single task Pi; `reviewer` exists only for an explicitly enabled optional session |
| POST | `/v1/tasks/:id/messages` | `{requestId,role,text}` |
| POST | `/v1/tasks/:id/pi/abort` | `{requestId,role}`; native clear_queue then abort |
| POST | `/v1/tasks/:id/pi/ui-response` | `{requestId,role,response:{id,confirmed? ,value?,cancelled?}}` |
| POST | `/v1/tasks/:id/plan/confirm` | `{requestId,revision}` |
| POST | `/v1/tasks/:id/start` | `{requestId,revision}` |
| POST | `/v1/tasks/:id/execution/cancel` | `{requestId,executionRequestId}`; separate native OpenCode cancellation |
| POST | `/v1/tasks/:id/review` | `{requestId,executionRequestId}`; optional-review tasks only; no duplicate active review |
| POST | `/v1/tasks/:id/rework` | `{requestId,revision,executionRequestId}`; latest Pi completion (or optional review) must be Needs Changes |
| GET | `/v1/tasks/:id/events?after=0` | SSE |

Canonical JSON fields are defined in `internal/core/model.go`. Settings are snapshotted at task creation and never retroactively applied. Optional `planId` groups tasks for a shared 180-minute budget; it defaults to the task ID. It does not imply permission to start other tasks. Budgets expose accumulated observed active seconds and retain the 60-minute task / two-rework / 180-minute plan limits across native sessions.

## Conversation and events

Pi owns history, compaction, context and generation. `messages` is native active context; `history` is the raw `get_entries` response. To display pre-compaction history without resurrecting discarded branches, follow native entry `parentId` ancestry from `leafId`, selecting message entries. Do not rebuild model context from an AWF event projection.

SSE emits `event: awf`, numeric `id`, and JSON `{id,type,taskId,time,data}`. `Last-Event-ID` takes precedence over `after`. Types include:
- `task.updated`: full current Task when small enough
- `pi.event`: `{role,event}` with the native Pi event unchanged
- `execution.event`: current Execution projection
- `replay.reset`: refresh Task and native messages/history

Event retention is bounded to approximately 4 MiB / 2,000 events. Oversized payloads are replaced with `{payloadOmitted:true,reloadNativeMessages:true}`; fetch the authoritative Task/native history. Token deltas are process-local replay data; native Pi persists its history. Restarted/expired cursors cause replay.reset. A disconnected browser does not cancel accepted work.

Native `agent_settled` is the idle boundary, not `agent_end`. `awf_queue_cleared` includes the native `steering` and `followUp` text arrays so cancelled queued input can be recovered into a draft. Native dialogs are available as `session.pendingUi` for browser reload. Confirm requires a boolean; select must match an offered option; input/editor require a string; cancellation is exclusive. Dialogs are tied to the current native process, expire after process replacement, and are consumed once. Responses are marked sent because Pi emits no response ACK.

## Native execution

The operator may configure an optional node-side `openCodeModel` object with `providerID` and `modelID`. The accepted job snapshots this selection; no Host/browser job field changes it. When omitted, native OpenCode chooses its default.

Node routes use a separate bearer credential: `GET /v1/health`, `POST /v1/jobs`, `GET /v1/jobs/:id`, `POST /v1/jobs/:id/cancel`. See `internal/node/types.go`. `completed` means a matching native assistant turn terminated with no unfinished tools, not task approval or Git merge. `execution.evidence` contains real native tool references and bounded excerpts, marked `verified:false`; the same Pi must assess them in the default path. Earlier runs are preserved in `executionHistory` and immutable node jobs.

OpenCode permission/question requests are exposed as `pendingPermissions` / `pendingQuestions`. This initial slice does not answer them through the web API; resolve them using the native OpenCode interface. Waiting on them does not consume observed execution time.

`/internal/tasks/:id/{context,plan,execute,finish,review}` is a loopback-only Pi extension capability surface, outside the public proxy allowlist. Credentials are scoped cryptographically to one task/role. A Pi plan tool creates a proposal only; no chat keyword or tool result starts execution without the separate explicit user confirmation/start action.

## Default single-Pi flow

Settings returns `reviewer: "disabled"` by default. OpenCode native completion enters `status: "reporting"`, `phase: "execution"`; the Host sends the real execution evidence back to the original Pi session. Pi uses the structured `awf_finish` tool with the exact executionRequestId and `done` or `needs_changes`. The result is `task.completion` with verdict, summary, findings, at, sessionId and executionRequestId; `completionHistory` preserves earlier rounds. No reviewer session or independent-review gate is created. No plain model text changes task state. Optional independent review requires explicit Host configuration and remains per-task snapshotted.
