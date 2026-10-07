# Native Durable transport v1 draft

Draft for the parent and PRIVATE consumer to freeze before transport
implementation. Published Pi Durable baseline is 1.0.4, source
`7c10bd4337495ee613f2224843ecdf349b80d1df`. This replaces the unlaunched
execution/attempt protocol; no compatibility adapter is required.

## Boundary

GoHost provides one existing HTTP listener, owner-scoped authentication, bounded
envelopes and typed business-result validation. It manages one long-lived
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

Suggested worker routes:

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
  history. Final pagination details are pending freeze.

Suggested receipt:

```json
{"version":1,"requestId":"<application request UUID>","conversationId":1,"submissionId":2,"status":"placed","abortRequested":false}
```

IDs are positive native JavaScript safe integers, not Go UUIDs. Native input
status is exactly `queued`, `placed`, `done` or `unanswered`. Optional `reason`
comes from an unanswered native receipt; arbitrary private error detail is not
exposed. Optional `result` is the agreed typed business artifact, not a textual
claim of completion. No executionId/ownerEpoch/nativeSessionRef is fabricated.

Errors are bounded versioned code envelopes for `request_conflict`, `not_found`,
`invalid_input`, `unavailable` and `admission_pending`; no prompts, credentials or
stderr. Incomplete application admission has no invented submission ID. Go does
not retry mutations after timeout/disconnect; the original request/native IDs
are the recovery keys.

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
