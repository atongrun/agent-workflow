# Native Durable transport v1 draft

Explicit contract defaults for the locally implemented Go Host adapter. The
parent authorized independent implementation on 2026-10-07 while PRIVATE's final
owner/result/pagination/lease schema is pending; this is not a claim of a
cross-implementation freeze. Wire types/constants are isolated in
`internal/durablebridge/contract.go`. Published Pi Durable baseline is 1.0.4, source
`7c10bd4337495ee613f2224843ecdf349b80d1df`. This replaces the unlaunched
execution/attempt protocol; no compatibility adapter is required.

## Boundary

GoHost provides one existing HTTP listener, owner-scoped authentication, bounded
envelopes and bounded opaque JSON results. PRIVATE validates business results,
including catalog/CAS and ownership of result references. Go manages one long-lived
PRIVATE worker and an OS storage-owner lease. It does not persist an execution
ledger, scheduler, checkpoint, attempt/session identity or prompt retry.

PRIVATE implements Pi extensions/Skills and the existing catalog/CAS selection.
One native Harness owns agent tasks, native progress, abort and recovery.
Application admission/index/result documents may be stored in Durable; native
submission/task receipts remain authoritative. Browser input cannot override
owner, fingerprint, provider/model configuration, executable, environment or
storage paths.

## Transport

Use HTTP over a Unix socket in a service-owned 0700 runtime directory, socket
0600. No new TCP listener. The worker is launched with explicit operator-owned
argv/environment, without inheriting GoHost HTTP credentials. Socket, storage
directory, Pi agent directory and owner lease are fixed at startup. The lease
must remain held for the worker's lifetime, including parent failure; the final
startup/lease handoff details are part of the pending freeze.

Proposed lease handoff: Go takes `flock(LOCK_EX|LOCK_NB)` on the private,
service-owned, singly linked `<storageDirectory>/.awf-owner.lock` and passes
its open descriptor as child FD 3 (`AWF_DURABLE_OWNER_FD=3`). PRIVATE must keep
that descriptor open until its Harness/storage is closed and must not unlink,
replace or explicitly unlock the file. Go closes only its own descriptor after
worker shutdown; it does not call `LOCK_UN` on the shared open-file description.
The descriptor is a process ownership lease, with no application state inside.
Startup refuses an already owned directory. The native installation must ensure
only one canonical storage pathname and systemd control-group cleanup before a
replacement worker opens storage. This startup proposal still requires the
parent/PRIVATE freeze.

PRIVATE must verify the descriptor's type, owner, permissions and inode against
the configured lock path before opening native storage. Tools and auxiliary
processes must not inherit the lease descriptor; use close-on-exec where the
runtime exposes it and explicit spawn stdio that excludes FD 3. Released
NodeExecutionEnv already supplies only stdin/stdout/stderr to its tool spawns;
verify the actual PRIVATE worker's custom spawn paths as well. No native addon
or private Node binding is required merely to set a descriptor flag.

Implemented default worker routes (public paths add `/content` after `/v1`):

* `GET /v1/health`: protocol version 1, Durable package 1.0.4, ready only after
  native storage open and recovery initialization.
* `POST /v1/submissions`: authenticate at Go, validate bounded input and send
  `{version:1,owner,requestId,fingerprint,capability,payloadSchema,opaquePayload}`.
* `GET /v1/conversations/{conversationId}/submissions/{submissionId}`: owner must
  match the saved application/native mapping.
* `POST /v1/conversations/{conversationId}/submissions/{submissionId}/abort`:
  withdraw queued input or abort the isolated job conversation's running work.
* `GET /v1/requests/{requestId}`: read-only owner-scoped request lookup after lost
  acknowledgement; never creates a conversation, resolves a model or submits.
* `GET /v1/submissions`: bounded owner-scoped native-reference list for product
  history. Query `limit` defaults to 20 and is 1–100; optional `cursor` is opaque,
  nonempty, at most 512 UTF-8 bytes with no control characters. Go normalizes and
  forwards these fields only. Unknown/duplicate query fields are rejected.

Every authenticated call sets `X-AWF-Owner` from the trusted Go token mapping;
no browser header is forwarded. Submit also includes that owner in its envelope.
Abort sends `{version:1,owner}` and accepts no public body. PRIVATE must verify
owner against its saved mapping on every operation, including request lookup and
list. Startup health is the sole ownerless readiness probe on the private socket.
Health is `{version:1,durableVersion:"1.0.4",ready:true}` after native storage and
recovery initialization. Success receipt/page echoes the checked owner, which
Go verifies before forwarding it.

Default receipt:

```json
{"version":1,"owner":"<authenticated owner>","requestId":"<application request UUID>","conversationId":1,"submissionId":2,"status":"placed","abortRequested":false}
```

IDs are positive native JavaScript safe integers, not Go UUIDs. Native input
status is exactly `queued`, `placed`, `done` or `unanswered`. `abortRequested` is
required. Reason is required only for `unanswered`, bounded to 256 UTF-8 bytes.
Go passes released safe codes `aborted`, `model_error`, `no_model`, `reset`,
`stale`, `faulted`, `missing_task`, `task_too_old`, `migration_failed`; every other
valid native reason becomes fixed public `unanswered`. Private detail and
arbitrary error text are never public. Optional non-null `result` is opaque JSON
only on `done`, bounded to 256 KiB. Its semantic/schema/reference ownership
validation remains PRIVATE's responsibility. No executionId/ownerEpoch/nativeSessionRef
is fabricated.

List response is `{version:1,owner,items:[summary...],nextCursor?}`. Each summary
contains only requestId/conversationId/submissionId/status/abortRequested/reason.
No input, result, model configuration, prompt or transcript is permitted. Go
rejects unknown fields, duplicate native references or more items than requested.
PRIVATE owns cursor/index order and scope; Go stores no product history ledger.

Public submit takes exactly
`{version:1,requestId,capability,payloadSchema,opaquePayload}`. Owner and fingerprint
are generated in Go. RequestId is a lowercase canonical UUID; owner and labels
are bounded ASCII identifiers. Public JSON is limited to 256 KiB; the final
worker request frame including trusted fields is limited to 256 KiB + 1 KiB.
Worker response bodies read by Go are limited to 512 KiB; public result JSON is
independently limited to 256 KiB before re-encoding. Exact JSON tag spellings are required. Duplicate
keys, invalid UTF-8, depth over 32 and trailing JSON are rejected. Opaque JSON is
normalized using Go encoding/json with sorted map keys, preserved numeric
lexemes and HTML escaping disabled. The SHA256 lowercase hexadecimal fingerprint
is over `{version,capability,payloadSchema,opaquePayload}` in that field order,
using this same compact encoder. Different numeric spellings may conflict;
requestId and owner do not enter the digest because they are the admission key.

Errors are `{version:1,error:{code}}` envelopes for `request_conflict`, `not_found`,
`invalid_input`, `unavailable` and `admission_pending`; no prompts, credentials or
stderr. Incomplete application admission has no invented submission ID. Go does
not retry mutations after timeout/disconnect; the original request/native IDs
are the recovery keys.
HTTP codes are 400 invalid_input, 404 not_found, 409 request_conflict/admission_pending,
503 unavailable. Successful submit is 200 or 202; other success responses are 200.
Go also uses 401 unauthorized, 405 method_not_allowed and 413 invalid_input for
its own boundary. Wrong version, IDs, owner, status, shape, bounds or redirects
become generic unavailable. There are no forwarded error messages or stderr.
All responses are JSON with `Cache-Control: no-store`. Transport uses a fresh
connection per request, no idempotency-key header, no redirect and no mutation
retry. GET lookup cannot finish an interrupted admission.

## Application admission

PRIVATE checks owner/requestId/fingerprint before model resolution. A mismatch
conflicts; an existing request returns its original native mapping and model
snapshot. For a new job, the trusted existing catalog/CAS adapter resolves the
selected model and configures a dedicated native conversation. Store stable
fingerprint, input or existing immutable input reference, selected model and
conversation in one minimal application admission Doc. Native submit is a
separate commit; complete an interrupted gap with that same saved input and
requestId. Public raw Tx.createSubmission is not full native admission.

## Host lifecycle gap

Pi Durable 1.0.4 supplies no cross-process storage lock and cannot forcibly stop
non-cooperative JavaScript. Go needs the sole-owner lease and actual owned
process management. Systemd control-group termination/cleanup remains required
for production hard-stop containment, because native shell tools can detach
their own process groups. Local subprocess fixtures cannot establish that
native service guarantee. Do not retain a second agent ledger to address this
physical lifecycle boundary.
