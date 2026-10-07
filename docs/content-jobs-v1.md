# Content jobs v1 contract

Local candidate based on `f5656895f241f88a0aff340ce0758ca60874a3f8`.
The production entry is `awf host --config host.json --content-config content.json`:
content jobs and AWF share one GoHost and one listener. `cmd/awf-content` remains
an isolated development/test entry point. Pi and its private extensions/Markdown
skills own model execution, context and tools. This contract contains generic
envelopes only. It does not change `extensions/awf.ts`, AWF state/locks,
installation or released binaries. Content credentials grant only content routes.

## HTTP

All routes require a bearer credential configured by the service operator. A
credential maps to one owner. The owner is never accepted from the request body.
Cross-owner lookup and cancellation return 404. The default listener is loopback.

* `POST /v1/content/jobs` accepts the envelope below; returns 202 and a job.
* `GET /v1/content/jobs/{jobId}` returns a job, including its result on success.
* `POST /v1/content/jobs/{jobId}/cancel` durably requests cancellation and returns
  the job. A terminal job is returned unchanged.
* `GET /v1/content/jobs?limit=20&before={jobId}` returns `jobs` summaries and
  `nextCursor`. Limit is 1–100; cursor belongs to the authenticated owner. Neither
  input nor artifact bytes are included in list summaries.

```json
{"requestId":"00000000-0000-4000-8000-000000000001","capability":"shortpost","payloadSchema":"shortpost.input.v1","opaquePayload":{"example":"fixture"}}
```

`requestId` is a lowercase canonical UUIDv4. Only `shortpost` and
`shortpost.input.v1` are supported. `opaquePayload` is a non-null JSON object;
its business keys are interpreted by the private extension. Unknown envelope
fields and duplicate JSON keys are rejected. Body limit is 131072 bytes, input
limit is 65536 UTF-8 bytes and nesting limit is 32. No content-length assumptions
about JavaScript string characters are made.

Idempotency is unique on `(owner, requestId)`. The Go service fingerprints the
validated envelope after its own JSON normalization (sorted object keys, JSON
number lexical representation retained); whitespace and object key order do not
change the fingerprint. Array order and number spelling remain significant.
The same fingerprint returns the original job with 202, including if terminal;
a different fingerprint returns 409 `request_conflict`. Full queue returns 429
`queue_full`. The queue bounds all nonterminal jobs, default 64, with exactly one
executor per ledger. Cancellation does not require a queue slot.

A job contains `jobId`, `requestId`, `capability`, `payloadSchema`, `status`,
`createdAt`, `updatedAt`, `cancelRequested`, and, when present, `executionId`,
`ownerEpoch`, `nativeSessionRef`, `nativeStopReason`, `errorCode`, `result`.
Times are UTC RFC3339 with nanoseconds. `result` uses the artifact envelope below.
States are `queued`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`,
`needs_verification`. The last four are terminal. Error responses are
`{"error":{"code":"..."}}`; private prompts, subprocess stderr and credentials
are never returned. GET is the durable recovery path; v1 has no SSE requirement.
HTTP failures use `unauthorized` (401), `invalid_request` (400),
`body_too_large` (413), `request_conflict` (409), `queue_full` (429),
`not_found` (404), `unavailable` (503), or `method_not_allowed` (405).

## Child bridge (UTF-8 JSON Lines on stdin/stdout)

The service checks the complete encoded frame before starting one configured
executable per attempt, without a shell. Configuration admission also reserves
the maximum input's frame budget after JSON escaping. It
commits a dispatch fence before sending one execute frame. `ownerEpoch` is a
fresh UUIDv4 process epoch; `executionId` is a fresh UUIDv4 attempt identity.
Owner identity and HTTP credentials are not sent to the child. Execution profile
is fixed by service configuration; `modelRef` and `resourceVersions` are opaque
operator-selected references, not client-selected credentials or instructions.

```json
{"version":1,"type":"execute","jobId":"00000000-0000-4000-8000-000000000002","executionId":"00000000-0000-4000-8000-000000000003","ownerEpoch":"00000000-0000-4000-8000-000000000004","capability":"shortpost","payloadSchema":"shortpost.input.v1","opaquePayload":{"example":"fixture"},"modelRef":"fixture-model","resourceVersions":{"shortpost":"fixture-version"},"deadlineAt":"2026-10-07T06:00:00Z"}
```

Cancellation is a separate frame, once at most:

```json
{"version":1,"type":"cancel","jobId":"00000000-0000-4000-8000-000000000002","executionId":"00000000-0000-4000-8000-000000000003","ownerEpoch":"00000000-0000-4000-8000-000000000004"}
```

Every event repeats `version`, `jobId`, `executionId`, `ownerEpoch`; `sequence`
starts at 1 and increments by exactly 1. Event types are `ready`, `artifact`,
`settled`, `error`. JSONL frame limit is 131072 bytes including newline.

```json
{"version":1,"jobId":"00000000-0000-4000-8000-000000000002","executionId":"00000000-0000-4000-8000-000000000003","ownerEpoch":"00000000-0000-4000-8000-000000000004","sequence":1,"type":"ready","nativeSessionRef":"opaque-session-reference"}
```

`ready` appears once before artifact or settlement. `nativeSessionRef` is an
opaque, nonempty UTF-8 reference of at most 512 bytes; it is not a filesystem path
that Go opens. There is at most one artifact:

```json
{"version":1,"jobId":"00000000-0000-4000-8000-000000000002","executionId":"00000000-0000-4000-8000-000000000003","ownerEpoch":"00000000-0000-4000-8000-000000000004","sequence":2,"type":"artifact","artifact":{"schema":"shortpost.result.v1","mediaType":"application/json","bytes":2,"sha256":"44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a","dataBase64":"e30="}}
```

Artifact length is 1–65536 bytes. Decode `dataBase64`, check its exact byte count
and lowercase SHA-256, require valid UTF-8 and a non-null JSON object without
duplicate keys (depth at most 32). SHA is over these exact decoded bytes, not a
re-serialized JSON object. The service stores this same byte sequence as a BLOB
in the success transaction. The public layer does not validate private business
fields. A native settlement follows:

```json
{"version":1,"jobId":"00000000-0000-4000-8000-000000000002","executionId":"00000000-0000-4000-8000-000000000003","ownerEpoch":"00000000-0000-4000-8000-000000000004","sequence":3,"type":"settled","stopReason":"completed"}
```

`stopReason` is exactly `completed`, `aborted`, or `failed`. `settled` appears
once and is the last event. `error` is terminal protocol information with
`errorCode` exactly `execution_failed` or `invalid_input`; it makes the attempt
uncertain unless followed by a valid native `settled` with reason `failed`.
No event claims process exit: Go observes actual owned process exit separately.
No output is allowed after settlement. Extra fields, identities, sequences,
hashes, multiple artifacts or invalid ordering fail closed.

Success requires verified artifact + native `completed` settlement + clean
owned process exit/quiescence + a successful ledger transaction with the current
fence and no cancellation intent. An execute ACK, artifact alone, exit alone or
cancel ACK is insufficient. Explicit native failure/abort with clean exit gives
`failed`/`cancelled`; missing/contradictory evidence gives `needs_verification`.

Cancel records intent before it is sent. If success committed first, cancel
returns success unchanged. If cancel intent committed first, later output is
not published; verified native settlement and clean exit yield `cancelled`,
while `nativeStopReason` retains the actual observed reason. A queued cancel is
terminal without starting a child. Abort grace expires after 5 seconds; timeout,
forced termination, malformed protocol or uncertain cleanup yields
`needs_verification`. Runtime limit defaults to 5 minutes (maximum 15 minutes).

## Persistence and ownership

Use a separate private data directory containing `content.db` and its own
`content.lock`. The lock excludes another service before schema/recovery work;
it never reuses AWF locks. Linux local-filesystem single-host operation only in
v1. SQLite uses WAL, synchronous FULL, foreign keys and a bounded busy timeout.
Jobs, attempts, generic transition events and result bytes use short transactions.
The target directory/files must be private and service-owned. Because SQLite
reopens paths, ancestors must have root/service ownership and prevent replacement
by untrusted users (root-owned sticky /tmp is allowed). A read-only bind view is
not sufficient proof: its backing inode may have another writable view. This
conservative v1 guard rejects UID-mapped system ancestors whose trust cannot be
established; supporting those layouts needs an explicit trusted mapping or a
pinned filesystem access design. It does not modify their ownership/permissions.
Request identity/fingerprint reservation and queue admission are atomic.
No process or model side effect occurs until dispatch is committed. On restart,
queued jobs can run if no previous dispatch was interrupted. All
dispatched/nonterminal jobs become `needs_verification` with `restart_unknown`.
Recovery also persists an execution/admission halt, because v1 cannot prove that
old native descendants have exited; another restart does not clear the halt.
GET and cancellation remain available. An operator must verify old processes
and perform an explicit offline recovery; v1 offers no HTTP reset API.
These jobs are never automatically prompted again. A failed
dispatch or finish transaction stops the executor and closes mutation admission.
Reads remain available only when the ledger can serve them.

Verified artifact bytes can be retained for investigation after failure or
cancellation. GET exposes `result` only for `succeeded`; lists never expose it.
The private extension decides whether its business result is complete. Public Go
stores its original bytes, without inventing or discarding business fields.

The bridge owns no durable queue/ledger and performs no automatic prompt retry.
It uses one native Pi attempt and its extensions/skills. Real private bridge
integration, native settlement provenance and process cleanup must be verified
before acceptance; protocol fixture tests alone do not establish those facts.

The content configuration is a private regular file (mode 0600) containing
`dataDir` (absolute, separate private directory), `credentials:[{token,owner}]`,
`bridge:{executable,args,env}`, `profile:{modelRef,resourceVersions,timeoutSeconds}`,
and `queueLimit`. Tokens have at least 24 characters and must be distinct from
AWF Host and extension credentials. The bridge executable must
be absolute; its argv contains no substituted client data. It inherits only a
default PATH plus explicitly configured environment variables, so neither GoHost
credentials nor provider secrets leak through process environment inheritance.
No credential-bearing example file is checked in. Host shutdown stops content
execution before closing the ledger. Existing AWF execution limits are not a
global Pi capacity limit shared with content in this initial implementation.
The browser cannot select models, resources or filesystem paths: model and
resource references are snapshots of service configuration, and the private
bridge must honor them rather than reinterpret opaque payload as configuration.

Offline recovery:

1. Stop GoHost. As the service UID, run
   `awf content inspect --content-config /absolute/private/content.json`.
   acquires the same independent content lock and reports `halted`, `queuedCount`,
   fenced `unknownAttempts` summaries and an opaque `recoveryToken`. Opening the
   ledger records any interrupted dispatch as unknown before inspection.
2. Inspect every reported attempt and verify its bridge/Pi/native descendants
   have exited. Do not infer quiescence from a settlement or kill ACK. If this
   cannot be proved, keep execution paused; preserve the ledger.
3. `awf content recover --content-config /absolute/private/content.json
   --confirm-quiescent --recovery-token TOKEN` requires the current inspection
   token and explicit operator attestation. It records an audit entry and clears
   only the pause; unknown jobs remain unknown, with all data retained. A stale
   token fails. This command does not launch a process or call a model.
4. Next approved GoHost startup may execute previously queued, never-dispatched
   jobs. Cancel those through the authenticated API before restarting execution
   if they should not run. Unknown jobs are never requeued by recovery.

Recovery summaries include the Go-observed `bridgePid` and `bridgeStartToken`
(`/proc/PID/stat` field 22), recorded before execute is sent, plus a native
session reference recorded on ready. A PID alone is insufficient: compare its
start marker before treating it as the old process. Missing/reused PID does not
prove that native descendants exited; inspect the native session and service
process ownership as well. The configured bridge must keep native children in
its owned group and join them before exit. Process-group checks cannot prove
the exit of detached descendants; that remains a real private/native acceptance
gate. Recovery never kills a PID or changes user data automatically.

## Dependency and local verification gate

Pin `modernc.org/sqlite v1.59.0` (2026-09-15, Go 1.25.0; CGO-free). Its published
go.mod pins `modernc.org/libc v1.75.7`; keep the release's dependency versions.
Module/go.mod hashes from the verified Go checksum database are
`h1:X1es1GpqBlS/5T+vbM4HLUdaa8OtQx468DF2vrx+38A=` and
`h1:+paeT2A3iPRHkQDwG7oA6Tk0zQd5woMEI8q7orfry8k=` respectively. The driver is
BSD-3-Clause according to its [official package documentation](https://pkg.go.dev/modernc.org/sqlite);
SQLite itself is public domain. Preserve and inspect all transitive license files
once bytes are available. The root module's minimum Go version becomes 1.25.0.
The local compiler is Go 1.25.14. The newer v1.60.1 requires Go 1.26.0.

The real ledger/locking tests can also run locally on Darwin with the same
official driver and a physical, private service-owned TMPDIR. This is a test
and dependency-verification path; native process execution remains Linux-only.

The official registry module ZIP redirect returned 403 in this executor; neither
the driver bytes nor a newer toolchain are cached. No source restriction has
been bypassed. SQLite integration tests and complete binary builds are blocked
until the authorized dependency bytes are available here. No model call, system
installation, listener/firewall change, deployment, push or release is authorized
by this local contract.
