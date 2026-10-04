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
| PATCH | `/v1/tasks/:id/budget` | `{requestId,expectedBudgetRevision,taskMinutes?,maxReworks?}`; tighten inactive task totals only |
| PATCH | `/v1/tasks/:id/target` | `{requestId,expectedTargetRevision,repository,repositoryId?,projectId,nodeId}` |
| GET | `/v1/tasks/:id/messages?role=architect` | `{messages,session,history}` from native Pi `get_messages` / `get_entries`; `architect` is the compatibility key for the single task Pi; `reviewer` exists only for an explicitly enabled optional session |
| POST | `/v1/tasks/:id/messages` | `{requestId,role,text}` |
| POST | `/v1/tasks/:id/pi/abort` | `{requestId,role}`; native clear_queue then abort |
| POST | `/v1/tasks/:id/pi/ui-response` | `{requestId,role,response:{id,confirmed? ,value?,cancelled?}}` |
| POST | `/v1/tasks/:id/plan/confirm` | `{requestId,revision}` |
| POST | `/v1/tasks/:id/start` | `{requestId,revision,expectedTargetRevision}` |
| GET | `/v1/tasks/:id/execution/questions?executionRequestId=…&jobId=…&sessionId=…` | bound native question view |
| POST | `/v1/tasks/:id/execution/questions/:questionId/reply` | `{requestId,executionRequestId,jobId,sessionId,answers:string[][]}` |
| GET | `/v1/tasks/:id/requests/:requestId` | original durable request receipt |
| POST | `/v1/tasks/:id/execution/cancel` | `{requestId,executionRequestId}`; separate native OpenCode cancellation |
| POST | `/v1/tasks/:id/review` | `{requestId,executionRequestId}`; optional-review tasks only; no duplicate active review |
| POST | `/v1/tasks/:id/rework` | `{requestId,revision,executionRequestId,expectedTargetRevision}`; latest Pi completion (or optional review) must be Needs Changes |
| GET | `/v1/tasks/:id/events?after=0` | SSE |

Canonical JSON fields are defined in `internal/core/model.go`. Global settings are snapshotted at task creation and never retroactively applied. Optional `planId` groups tasks for a shared 180-minute budget; it defaults to the task ID. It does not imply permission to start other tasks. Budgets expose accumulated observed active seconds and default to 60-minute task / two-rework / 180-minute plan limits across native sessions.

## Tightening an existing task budget

Read the task's `budgetRevision` (zero for existing tasks), then PATCH its budget with that `expectedBudgetRevision` and at least one integer limit. For a 10-minute / one-rework total, send `{requestId:"<stable-id>",expectedBudgetRevision:0,taskMinutes:10,maxReworks:1}`. `taskMinutes` must be at least 1; `maxReworks` may be 0. Omitted limits remain unchanged. Neither limit may increase, and at least one must decrease. Unknown fields and query parameters are rejected; plan limits cannot be changed here.

The operation accepts settled tasks, including Blocked tasks with prior failed execution. It rejects active/queued/uncertain execution, reporting/review, active Pi or compaction, pending commands/dialogs/native permissions/questions, unresolved request receipts, unknown task/execution/receipt states, and Trash tasks. It does not start work, reset counters/waits, change plan confirmation, or alter prior executions and native session identities. A lower total may be below already spent seconds or reworks: spent usage remains visible, with no further time or rework allowance. Existing rework eligibility still applies; tightening a failed execution does not authorize a retry.

A successful PATCH returns HTTP 202 with a **completed** request receipt, atomically increments `budgetRevision`, and emits `budget.tightened` plus `task.updated`. The durable receipt's `result` records before/after limits and the resulting revision. Exact retries do not reapply the change, including after the task becomes active. Changed payloads or stale revisions return 409. Verified POST request lookup supports operation `budget` and the original payload, as well as GET receipt lookup. Defaults and other tasks are unaffected.

`taskMinutes` caps accumulated **observed active time**, including Host-accounted Pi planning/compaction/reporting and node-accounted execution; it is not a deadline measured from task creation or start. OpenCode busy/retry observations accrue execution time; permission/question waits do not. Sampling, native terminal-duration fallback and integer-second accounting are the existing measurement limits. First node dispatch rechecks remaining task/shared-plan time and caps the persisted timeout before submission; exhaustion or an invalid timeout fails closed for verification. Already attempted dispatch fingerprints remain unchanged.

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

OpenCode permission/question requests remain exposed as `pendingPermissions` / `pendingQuestions`. The bounded question API below answers only native questions. Permission approvals remain in the native interface. Waiting on either does not consume observed execution time.

### Cancelled-question cleanup

The existing node `POST /v1/jobs/:id/cancel` also verifies question cleanup after a confirmed abort and on retries of an already-cancelled job. It retains the original durable cancellation request ID; a timeout without explicit cancellation authority does not acquire question-rejection authority. Only the original configured workspace/session/user turn and its exact assistant question message/call/part IDs qualify. Newer/reused turns, unknown native state or ambiguous bindings fail closed. Node authentication/source restrictions and its existing native Basic-auth client are reused; no independent reject command, password export or arbitrary native proxy is added.

A bounded `job.questionCleanup` map (at most 128 IDs) durably fences each native reject before its single POST. Receipts include `questionId`, `taskId`, `jobId`, `executionRequestId`, `sessionId`, assistant `messageId`, `callId`, `partId`, original `cancelRequestId`, `createdAt`, `status` (`dispatching`, `needs_verification`, `cleared`), `acknowledged`, optional `error`. `acknowledged` means a durably received native boolean ACK. `cleared` means a subsequent authoritative list and idle/turn recheck established absence, including after a lost ACK; it never invents ACK provenance. Neither ambiguity nor restart replays a fenced reject. Still-pending, malformed or unreadable native state returns 409 `question_cleanup_pending` and retains verification gates. Read the existing authenticated job GET for the original receipt and retry its cancellation to reconcile.

`job.questionCleanupState` is `needs_verification` until native checks and durable persistence establish `cleared`, even when the first retry finds the question already absent and no reject was necessary. Both node/offline idleness and the existing native idle checks stay fail closed. Other sessions' questions and all permissions are untouched. Cleanup neither answers a question, starts a prompt, submits another job nor resets execution counters/history. The existing Host cancellation route accepts an exact retry of its original request to reconcile a still-pending cancelled execution; it cannot create new cancellation authority for a terminal run. Only verified cancellation question waits refresh on an otherwise absorbing terminal Host execution; status, evidence, verdict and accounting remain unchanged.

### Bound native questions

GET requires exactly one each of `executionRequestId`, `jobId`, `sessionId`; no extra parameters. It returns `{taskId,jobId,executionRequestId,sessionId,questions:[...]}`. Each native question contains `id` (`que_…`), `sessionID`, `questions:[{question,header,options:[{label,description}],multiple?,custom?}]` and a verified `tool:{messageID,callID}` binding. Native `sessionID` casing is preserved inside the question; API input uses `sessionId`. Use the native question ID, not its tool call ID. An empty list means no bound question is currently pending.

POST replies require the same exact current task/job/execution/native-session binding. `answers` has one nonempty string array per native question; a single-select question allows one choice, multiple-select allows distinct choices, and `custom:false` requires offered labels. No arbitrary native route, permission approval, password, model selection or shell command is exposed. The node verifies the configured workspace, original user message and current assistant question tool; a reused session alone is insufficient. Deleted, cancelled, inactive, unknown-state or stale jobs fail closed.

A successful forward returns HTTP 202 `{task,request}`. `request.status:"completed"` means the node durably recorded the native boolean acknowledgement, not that execution or review finished. Definite validation rejection returns 400; stale/expired binding returns 409; absent jobs can return 404. A reserved rejected request has status `failed`; exact retries return the same error. Transport/storage ambiguity or a missing/malformed acknowledgement leaves `needs_verification`: retain the same request ID, inspect GET `/v1/tasks/:id/requests/:requestId`, and retry only the identical original request to reconcile the node receipt. GET request lookup alone reads the Host receipt and does not refresh the node. Never make up a new ID to resend an uncertain answer.

The node persists a per-job answer fence before the single native POST because OpenCode provides no answer idempotency key. Same-ID retries read the receipt; another ID for the same question is rejected. A crash after the fence or a lost ACK stays uncertain and is never automatically resent. At most 128 question receipts are retained per job. Historical retries may reconcile the original recorded job's receipt after terminal transition, replacement or Trash; they cannot answer a new question. Native in-memory pending questions may expire independently. `execution.question-reply` events expose request ID/status; reload the task/receipt after an event or reconnect. These routes use the existing Host bearer and node bearer/source restriction; native Basic authentication stays on the node.

`/internal/tasks/:id/{context,plan,execute,finish,review}` is a loopback-only Pi extension capability surface, outside the public proxy allowlist. Credentials are scoped cryptographically to one task/role. A Pi plan tool creates a proposal only; no chat keyword or tool result starts execution without the separate explicit user confirmation/start action.

## Default single-Pi flow

Settings returns `reviewer: "disabled"` by default. Newly observed native `completed`, `failed` or `cancelled` receipts enter `status:"reporting"`, `phase:"execution"`. The Host durably queues one `result-<executionRequestId>` command for the original Pi session, including when that session is busy. It uses existing Pi RPC/events and reopens the same saved native session after restart. Queued, never-dispatched receipts can recover; any receipt that crossed the persisted JSONL dispatch fence is never automatically replayed after ambiguity. Exhausted task/shared-plan time blocks result delivery. This flow submits no new executor job and grants no additional rework.

`execution.resultReview` exposes `requestId`, `executionRequestId`, original Pi `sessionId`, OpenCode `nativeSessionId`, `status` (`queued`, `dispatching`, `awaiting_verdict`, `needs_verification`, `blocked`, `reviewed`), `verdict?`, `evidenceChecks`, `independentlyVerified:false`, `error?`. Review transitions emit task updates; the verdict emits `execution.review`. Inspect the existing request lookup for delivery status. A valid matching same-Pi verdict reconciles a sent/uncertain result receipt to completed without replay; late delivery updates cannot regress it. A verdict arriving before dispatch cancels the unsent result receipt. Repeated terminal polls cannot reopen a finished verdict or regress a terminal execution to running.

Pi calls structured `awf_finish` with the current `executionRequestId`, `verdict`, `summary`, and three `evidenceChecks`, one each of `diff`, `tests`, `remote_sha`. A check is `{kind,status:"observed"|"unknown",sources:string[],remoteSha?,notes?}`. Unknown requires an empty sources list, no SHA and a reason. A legacy `needs_changes` call without checks remains accepted and records unknown checks. Done requires a completed execution and all three observed checks supported by actual completed native `bash` tools in this execution/session: diff output, a recognizable test command with successful recorded exit metadata, and `git ls-remote` output containing the exact work-branch ref and claimed 40/64-character SHA. Push output, model summaries, missing exit data, truncated output, pipelines, background commands, masked exits or ambiguous command attribution cannot satisfy the gate. The conservative recognizer accepts a single command, optionally preceded by `cd … &&`; unsupported command styles must be reported unknown. This is an observation gate, not an independent shell verifier or a guarantee of test adequacy, freshness or repository correctness.

`execution.evidence[]` retains bounded native `input`, `output`, `metadata`, `tool`, `status`, `messageId`, `callId`, `sessionId`, `source`, `truncated` alongside existing fields. Input/output are limited to 64 KiB each, metadata to 8 KiB, at most 100 records; truncation disqualifies observed checks. All evidence remains `verified:false`; model-provided verification flags cannot promote it. Neither a successful push nor a same-Pi verdict is independent verification. The Host runs no Git commands.

The result is `task.completion` with verdict, summary, findings, at, sessionId, executionRequestId and evidenceChecks; `completionHistory` preserves earlier rounds. Failed executions remain Blocked and cancelled executions remain Cancelled after review; neither Done nor rework is authorized for those receipts. No reviewer session is created by this path. Optional separate Pi review remains explicitly configured and per-task snapshotted; its existing behavior is unchanged.

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

## Recoverable task deletion

`POST /v1/tasks/{id}/delete` and `POST /v1/tasks/{id}/restore` accept exactly
`{requestId}` and return the durable `{task,request}` receipt (202). Deletion
sets additive `task.deletedAt` metadata and increments `lifecycleRevision`; it never removes task/session IDs,
conversation files, repositories, plans, execution history, or old receipts.
The default task list and overview exclude deleted tasks. `GET /v1/tasks?deleted=true`
returns only Trash; `deleted=false` is the default. Detail and receipt reads
remain available, and task SSE publishes the deletion/restoration snapshot.

Delete is rejected while execution is queued, active, uncertain, reporting or
under review; Pi is busy, has pending work/dialogs/control; or unresolved
requests need verification. Idle Pi processes close under the same lifecycle
lock as process startup and eviction. The durable deletion marker immediately
blocks new changes and native process startup, and the receipt becomes
`completed` only after process exit is verified. `accepted` or
`needs_verification` is not success: retain the original ID and payload, and
reconcile using `POST /v1/tasks/{id}/requests/{requestId}` with operation
`delete` or `restore`. Exact replays only retrieve the historical receipt,
including a delete replay after a later restore. Never replace an uncertain
request with a new ID.

Restore requires the deletion receipt to have settled and clears only the
marker. It does not resume a process or automatically start any execution.
Native conversation reads return `task_deleted` (409) while deleted; after
explicit restore, opening the conversation resumes the original native history.
There is no hard-purge endpoint.
