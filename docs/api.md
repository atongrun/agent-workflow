# HTTP contract

Every Host `/v1` route requires `Authorization: Bearer <host token>`. It is intended for a protected server-side proxy. No CORS credentials or tokens belong in the browser. Bodies are JSON, writes require a stable caller-generated `requestId` matching `[A-Za-z0-9._:-]{1,128}`. Reuse that ID only with the exact same task, operation and payload. A duplicate returns the original request/current task and never restarts the effect; changed payload yields HTTP 409. Preserve the ID after an ambiguous response.

Errors: `{ "error": { "code": "...", "message": "..." } }`. HTTP 202 is acceptance, not native completion. A write normally returns `{task, request}`; request status can remain `needs_verification`. Task IDs are UUID-shaped stable strings.

| Method | Path | Body / result |
|---|---|---|
| GET | `/v1/health` | Host liveness only |
| GET | `/v1/overview` | `{tasks,agents,settings}` |
| GET | `/v1/targets` | `{targets:[{projectId,nodeId,projectLabel,nodeLabel,ready}],nodes:[{nodeId,label,status}]}`; status is `online`, `unavailable` or `unknown` |
| GET | `/v1/agents` | `{agents}`; native reachability, no synthetic online state |
| GET | `/v1/settings` | `{settings}` |
| PATCH | `/v1/settings` | `{requestId,defaultBranch,branchPrefix}` → `{settings}` |
| GET | `/v1/tasks` | `{tasks}` |
| POST | `/v1/tasks` | `{requestId,title}`; legacy optional `projectId,repository,goal,acceptanceCriteria,nodeId,planId` remain accepted |
| GET | `/v1/tasks/:id` | `{task}` |
| PATCH | `/v1/tasks/:id/target` | `{requestId,expectedTargetRevision,repository,repositoryId?,projectId,nodeId}` |
| GET | `/v1/tasks/:id/messages?role=architect` | `{messages,session,history}` from native Pi `get_messages` / `get_entries`; `architect` is the compatibility key for the single task Pi; `reviewer` exists only for an explicitly enabled optional session |
| POST | `/v1/tasks/:id/messages` | `{requestId,role,text}` |
| POST | `/v1/tasks/:id/pi/abort` | `{requestId,role}`; native clear_queue then abort |
| POST | `/v1/tasks/:id/pi/ui-response` | `{requestId,role,response:{id,confirmed? ,value?,cancelled?}}` |
| POST | `/v1/tasks/:id/plan/confirm` | `{requestId,revision}` |
| POST | `/v1/tasks/:id/start` | `{requestId,revision,expectedTargetRevision}` |
| POST | `/v1/tasks/:id/execution/cancel` | `{requestId,executionRequestId}`; separate native OpenCode cancellation |
| POST | `/v1/tasks/:id/review` | `{requestId,executionRequestId}`; optional-review tasks only; no duplicate active review |
| POST | `/v1/tasks/:id/rework` | `{requestId,revision,executionRequestId,expectedTargetRevision}`; latest Pi completion (or optional review) must be Needs Changes |
| GET | `/v1/tasks/:id/events?after=0` | SSE |

Canonical JSON fields are defined in `internal/core/model.go`. Settings are snapshotted at task creation and never retroactively applied. Optional `planId` groups tasks for a shared 180-minute budget; it defaults to the task ID. It does not imply permission to start other tasks. Budgets expose accumulated observed active seconds and retain the 60-minute task / two-rework / 180-minute plan limits across native sessions.

## Drafts and execution targets

Only the title is required when creating a task. The task ID is derived from the request ID; a retry preserves its task and native session identities. A blank goal or acceptance criteria remains unset. New tasks persist `planningProfile:"restricted"` and initially have `targetRevision:0`. Providing legacy create fields does not authorize execution or replace explicit target binding.

`GET /v1/targets` returns only project/node pairs confirmed by the configured node's authenticated catalog and also present in the Host project configuration. Labels currently use configuration keys. It never returns workspace paths or bearer credentials. A node without the catalog route is `unknown`; failed discovery or unavailable native execution is `unavailable`. Do not synthesize target pairs from the health endpoint's project count. An already selected target remains on the task during an outage, but saving or starting requires fresh verification.

A target PATCH requires the current `expectedTargetRevision`, a canonical GitHub `owner/name`, and existing configured project and node keys. Optional `repositoryId` is a positive decimal string, avoiding JavaScript integer precision loss. The authenticated application is responsible for resolving GitHub authorization and canonical identity before forwarding; the Host does not authenticate GitHub or create/clone repositories. Selection is metadata only.

Saving a target increments the revision and clears plan confirmation. It fails while any Pi role is active, queued, or waiting on a dialog, or once the task has any execution history. Legacy sessions with a reserved native process or existing session reference cannot change their planning workspace. Exact request retries resolve before mutable configuration validation and do not increment again.

Start/rework requires a current confirmed plan, settled Pi roles and a freshly verified configured target. Restricted tasks additionally require a saved target and matching `expectedTargetRevision`. Legacy tasks with target revision zero may omit this field to preserve historical request serialization; any explicitly rebound legacy task must provide it, but target availability and repository syntax are still checked for new execution. Historical noncanonical repository metadata is preserved; it may require explicit remediation before any further execution. No migration changes existing native jobs, session IDs, request fingerprints or history.

New execution records include an immutable `target` snapshot with revision, project/node IDs and repository identity. Before first dispatch, new snapshots are revalidated again, including after queueing or Host restart. Reconciliation continues to use the original node job payload shape. A target save never starts Pi, performs Git operations or sends an execution job.

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

Node routes use a separate bearer credential: `GET /v1/health`, `GET /v1/projects`, `POST /v1/jobs`, `GET /v1/jobs/:id`, `POST /v1/jobs/:id/cancel`. The projects result is `{available,reachable,projects:[{projectId,label,ready}]}`; it is read-only and never contains workspace paths. See `internal/node/types.go`. `completed` means a matching native assistant turn terminated with no unfinished tools, not task approval or Git merge. `execution.evidence` contains real native tool references and bounded excerpts, marked `verified:false`; the same Pi must assess them in the default path. Earlier runs are preserved in `executionHistory` and immutable node jobs.

All node routes also require an allowed TCP source: loopback by default, or an exact match in the configured `allowedSourceIPs` list. Forwarding headers are ignored. Invalid or denied peers receive HTTP 403 with `source_denied`, even with a valid token; allowed peers still require bearer authentication. See [node source restriction](deployment.md#node-source-restriction).

OpenCode permission/question requests are exposed as `pendingPermissions` / `pendingQuestions`. This initial slice does not answer them through the web API; resolve them using the native OpenCode interface. Waiting on them does not consume observed execution time.

`/internal/tasks/:id/{context,plan,execute,finish,review}` is a loopback-only Pi extension capability surface, outside the public proxy allowlist. Credentials are scoped cryptographically to one task/role. A Pi plan tool creates a proposal only; no chat keyword or tool result starts execution without the separate explicit user confirmation/start action.

## Default single-Pi flow

Settings returns `reviewer: "disabled"` by default. OpenCode native completion enters `status: "reporting"`, `phase: "execution"`; the Host sends the real execution evidence back to the original Pi session. Pi uses the structured `awf_finish` tool with the exact executionRequestId and `done` or `needs_changes`. The result is `task.completion` with verdict, summary, findings, at, sessionId and executionRequestId; `completionHistory` preserves earlier rounds. No reviewer session or independent-review gate is created. No plain model text changes task state. Optional independent review requires explicit Host configuration and remains per-task snapshotted.

## Pi command menu and explicit native controls

These authenticated routes adapt official Pi 1.0.0 RPC. They do not provide an
arbitrary RPC endpoint or terminal/TUI emulation. Capability reads use the
existing running role process and never start/evict Pi just to open a menu.

- `GET /v1/tasks/{id}/pi/commands?role=architect|reviewer` returns `binding`
  (`role`, native `sessionId`, Host `processId`), native `commands` (`name`, optional
  `description`, `source`: extension/prompt/skill), and the explicit controls
  `stats`, `model`, `compact`, `stop`. Restricted planning normally has no
  discovered commands. Filesystem source metadata is omitted.
- `GET .../pi/models?role=...` returns the same binding, `current` (nullable), and
  `models`, each limited to provider/id/name. No transport URLs or headers escape.
- `GET .../pi/stats?role=...` returns binding, current model and native message,
  token, cost and context-usage statistics. Unknown context usage remains null;
  session filenames are omitted. These are Pi-reported values, not account bills.
- `POST .../pi/model` accepts requestId, role, expectedSessionId,
  expectedProcessId, provider and modelId. Selection changes this native session,
  not global model defaults. The chosen model must still be returned by Pi.
- `POST .../pi/compact` accepts the same binding and requestId without model
  fields. Requires idle Pi, no queued/pending messages or native dialogs, and
  remaining task budget. Compaction can consume model tokens and may fail on a
  small session. It never authorizes remote execution.
- `POST .../pi/abort` accepts the same binding and requestId without model fields.
  It fences pending Host prompt dispatches, clears Pi's queue and aborts Pi's
  current run/compaction. Undispatched and native queued text is offered as an
  unsent draft. This is separate from `execution/cancel` and never cancels a node
  job or rolls back files. An in-flight model selection must settle first.

Control writes return the durable `{task,request}` receipt (202). `accepted` is
not completion. Poll `GET /v1/tasks/{id}/requests/{requestId}` for that exact
receipt; completed/failed/cancelled are terminal. Retain the original ID and
payload across response loss, navigation and reload. `needs_verification` is an
unknown outcome, not permission to issue the control again. Exact POST retries
retrieve the old receipt before mutable-state checks, including after restart;
changed payloads conflict. Late results never update a replacement process.

Control selection in the UI only stages an action. Native discovered-command
selection only fills the draft. Sending a selected native command uses the
existing messages endpoint with expectedSessionId and expectedProcessId; these
optional fields preserve historical unbound message request hashes. Menu state
is scoped to task, role, native session and Host process identity. No session
switch/reset/fork/export, bash, login, thinking setting or arbitrary RPC control
is exposed by this menu.

`POST /v1/tasks/{id}/requests/{requestId}` is a read-only exact-payload receipt
lookup for target/start/rework recovery. The JSON body is `{requestId,operation,
payload}` where payload is the unchanged original input including requestId.
All three IDs must match. The Host applies the original typed serialization and
role default before comparing the stored hash. It returns the existing receipt
and task (200), absent (404), or conflict (409), with no reservation, node lookup,
Pi start, or external effect. This lets the gateway recover an existing receipt
before rechecking current GitHub authorization for a new operation.
