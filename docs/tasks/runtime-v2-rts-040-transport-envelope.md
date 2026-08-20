# TaskCard: RTS-040 Stage-Blind Command/Result Envelope

## Task ID

runtime-v2-rts-040-transport-envelope

## Goal

Define one versioned, canonical and Stage-blind command/result envelope plus one narrow local receive
gate around the accepted Runtime v2 application. The candidate must provide stable idempotency and
causation identity, reject malformed or mismatched bytes before any provider start, and preserve the
distinction between a Store-owned outgoing intent and external Agent Bus send, handler success and
ACK.

This is a disposable no-model Phase 4A contract candidate only. It does not implement Agent Bus,
send or ACK anything, consume production/retained deliveries, replace the production handler, adopt
legacy state, migrate authority or change a default. The RTS-035 local application and RTS-031
atomic Store/journal remain the only authority and writer used by the fixture.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@d309d075e3d0bd008790cda67a294a401da09c14`
- **Task branch**: `codex/runtime-v2-rts-040-transport-envelope`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4A / RTS-040
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Passed prerequisite**: RTS-035 selected local application, exact-head CI/Binary Feasibility and
  independent Gate Review PASS

Phase 3 is complete. The installed Python Runtime package has an accepted disposable local
`run/status/stop` application, but it has no accepted transport representation or receive gate.
Current production `awf.delivery.v1`, outbox/inbox and handler behavior are compatibility evidence
only and remain untouched.

## Frozen envelope boundary

### One canonical representation

The installed package may add one pure-standard-library envelope module with exactly two public
immutable values, `CommandEnvelope` and `ResultEnvelope`, backed by one shared canonical JSON codec.
Both use one versioned family and exact-key decoding; they are not Store records or authority.

Every envelope binds:

- its exact format and kind (`command` or `result`);
- stable delivery/idempotency identity derived from canonical immutable metadata and payload bytes;
- `run_id`, `task_id` and `run_spec_sha256` as opaque correlation/owner-intent identity;
- exact source/target role and route;
- exact source invocation/authorization plus target invocation identity;
- a canonical JSON payload plus its prefixed SHA-256; and
- for a result, the exact causing command delivery ID.

No top-level envelope field may carry Workflow Stage, attempt/rework budget, transition
authorization, terminal authority, Store path/state-root, checkpoint/outbox/inbox/ACK status or
provider launch permission. The payload is opaque canonical JSON: the codec neither interprets nor
authorizes Workflow-shaped payload keys. Workflow-specific content remains an untrusted input until
separately bound and validated by the application/Artifact contract.

The codec must reject duplicate JSON keys, unknown/missing keys, non-UTF-8/non-canonical input,
non-finite/non-JSON values, control characters, excessive nesting or size, malformed prefixed hashes,
unsupported roles/routes/kinds/formats and every recomputed payload/delivery/causation mismatch.
Encoding is deterministic across platforms and decoding an accepted envelope then encoding it again
must produce byte-identical canonical JSON.

The new identity is a Runtime v2 envelope identity and must not pretend to equal the existing
`awf.delivery.v1` identity. Focused tests use the current production helper only as a compatibility
oracle for canonical payload hashing and explicitly document the intentional identity-version
boundary. No production producer or consumer changes in this card.

### Local receive gate

One narrow `LocalTransportBoundary` (or equivalently named value) may compose the codec with the
accepted `LocalRuntimeApplication` without owning transport:

1. Decode and fully validate the command bytes.
2. Bind exact run/task/RunSpec, roles, route, source invocation/authorization, target invocation,
   delivery and payload identity to the supplied local stage request and current Store-owned
   expectation.
3. Reject mismatch before calling `LocalRuntimeApplication.run`, rendering or starting a provider.
4. On exact input, call the existing application once; it alone applies Workflow Stage,
   authorization, invocation journal, validation, handoff and terminal semantics.
5. Prepare a canonical result envelope only from an exact Store-owned outgoing intent/result fact
   supplied after the application commit, binding the causing command delivery ID.

The boundary may expose pure `decode`, `accept` and `prepare` operations needed by this sequence. It
must not open a socket, execute Agent Bus, poll a queue, retry/resend, claim handler success or ACK,
read external delivery history, start a provider itself, mutate a Store directly, or reconstruct
Workflow authority from envelope payload.

### Ordering and fault semantics

- Envelope acceptance is validation only; duplicate exact bytes are idempotent input facts and do
  not imply duplicate provider authorization.
- Malformed, foreign, stale, route/role/run/spec/invocation/authorization/payload/delivery or
  causation-conflicting input returns `DENY_BEFORE_PROVIDER` with no application/provider/Store
  mutation.
- The accepted local application atomically commits validation plus its outgoing intent where the
  Store permits. The codec can project that exact intent but cannot mark it sent.
- Agent Bus send may be absent, successful or ambiguous without changing local Workflow authority;
  handler success follows the complete local result path; ACK remains transport-owned after handler
  success. None of those external facts is inferred from an envelope or local Store.
- An identical accepted command after a durable application result follows the existing Store
  idempotency/no-replay decision. An ambiguous provider result remains `AMBIGUOUS_NO_REPLAY` and is
  never hidden by envelope redelivery.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-040-transport-envelope.md`
- `src/agent_workflow/runtime/__init__.py`
- `src/agent_workflow/runtime/application.py`
- `src/agent_workflow/runtime/transport.py`
- `tests/test_runtime_transport.py`
- `tests/test_runtime_application.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_command_boundary.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-040-transport-envelope.md`
- `.awf/artifacts/review-report-runtime-v2-rts-040-transport-envelope.md`

After implementation, exact-head CI and one independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-040-transport-envelope-implementation-report.md` and update only the
Phase 4A gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Editing production `scripts/`, CLI/facade/node/status/listener/service paths, Agent Bus client or
  server, manifest/schema or current delivery/outbox/inbox/checkpoint representations.
- Reading, converting, importing, shadowing, dual-writing or deleting RunLedger/context packet,
  checkpoint, outbox, inbox, RunEvidence, retained events or production state.
- Network/queue I/O, Bus send/receive/retry/ACK, handler-success assertion, historical delivery
  lookup, queue inspection/manipulation or live cross-machine acceptance.
- Treating envelope data as Workflow transition, provider authorization, terminal, ACK or external
  observation authority; deriving a local ACK/sent fact.
- Remote Git/GitHub, native lifecycle/process stop, credentials, real provider intelligence,
  generic transport/provider/plugin framework, scheduler, physical Coordinator, daemon, leader
  election, distributed lock, SQLite or Rust/Go production Runtime.
- Native launcher, packaging/distribution work, production adoption, representation migration,
  compatibility deletion, default switch, release, retained-event operation or destructive cleanup.
- Editing the Frozen semantic contract, ADR-0006, Phase 2/3 evidence or shared fault fixture.

## Budgets and stop rules

- New `transport.py`: at most 480 nonblank/noncomment lines.
- New focused transport tests plus existing-test refinements: at most 900 net nonblank/noncomment
  lines.
- `application.py` refinement: at most 100 net nonblank/noncomment lines and only the receive-gate
  composition seam; no duplicated Workflow, Store, workspace, Artifact or provider body.
- No new dependency or persistent representation; installed Runtime remains standard-library only.
- One envelope family, one canonical codec, one receive boundary and the existing application/Store;
  no alternate adapter registry, transport implementation, second writer or background component.
- One candidate Gate Review and at most two L3 repair/focused re-review rounds.
- If acceptance requires production-handler edits, Bus I/O, a second authority/idempotency store,
  Stage authority in the envelope, provider replay, live/retained events, migration or any budget
  breach, stop with `PLAN_CONFLICT` rather than widening scope.

## Acceptance criteria

- [ ] Task ID equals branch leaf; every changed path stays within frozen/closeout scope.
- [ ] Exactly one versioned command/result envelope family and one canonical strict JSON codec exist;
      deterministic round trips are byte-identical on all platforms.
- [ ] Stable delivery/idempotency identity binds kind, run/task/RunSpec, exact roles/route, source
      invocation/authorization, target invocation, payload hash and result causation; payload
      mutation changes identity.
- [ ] Top-level envelope fields contain no Workflow Stage/attempt/rework/terminal, Store
      path/state-root, checkpoint/outbox/inbox/ACK or provider-launch authority; opaque payload keys
      are never interpreted as authority by the codec.
- [ ] Duplicate keys, unknown/missing fields, malformed/noncanonical/oversized/deep JSON, invalid
      Unicode/number/control values, unsupported format/kind/role/route and all identity/hash drift
      fail closed before application/provider/Store mutation.
- [ ] The receive gate binds exact command identity to the supplied RunSpec and local request, then
      calls the existing application once; no copied transition/provider/workspace/Artifact logic.
- [ ] Exact redelivery after a durable result remains idempotent through existing Store facts;
      launch-intent-without-result remains ambiguous and never invokes again.
- [ ] Result preparation requires one exact Store-owned outgoing fact and exact command causation;
      conflicting/foreign intent denies without mutation and cannot claim send/handler-success/ACK.
- [ ] Disposable no-model PASS, REQUEST_CHANGES/rework/PASS and BLOCKED command/result sequences
      preserve the RTS-035 local outcomes and stable identities.
- [ ] Fault injection snapshots Store bytes and provider-call evidence before malformed/mismatched/
      duplicate/ambiguous operations and proves exact stability at the first legal boundary.
- [ ] Static boundary tests prove no socket/HTTP/Agent Bus/subprocess/queue/ACK/history/production
      script import, transport implementation, generic registry, scheduler/Coordinator or external
      truth ownership.
- [ ] Existing production `awf.delivery.v1` canonical payload hashing is comparison-compatible while
      its delivery identity remains intentionally separate and unchanged.
- [ ] LOC/dependency/single-codec/single-boundary/no-persistent-representation budgets pass.
- [ ] Focused tests, full pytest/Ruff and ordinary Linux/Windows/macOS/installed-wheel CI pass on the
      candidate head; automatically triggered Binary Feasibility remains green evidence.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; any L3 repair receives focused re-review
      by the same Reviewer.
- [ ] Closeout names exactly one later Phase 4A adapter/live-isolated gate without claiming Bus
      adoption, cross-machine acceptance, ACK, migration, default, lifecycle, launcher or release.

## Verification

- Local Mac: AST/static/import/codec checks, disposable fake-application/provider call counters,
  Store byte snapshots, scope/LOC/dependency audit and `git diff --check` only.
- CI: focused transport/application/Core tests plus full pytest/Ruff, installed-wheel and ordinary
  cross-platform jobs.
- Fault fixtures corrupt every envelope binding independently and assert zero application/provider
  calls and byte-stable authority; exact duplicate/ambiguity fixtures reuse the accepted Store path.
- Independent Review checks Stage-blindness, identity/causation completeness, pre-provider gate,
  outgoing-intent/send/handler-success/ACK ordering, no replay and all external/production boundaries.

## Required output

- one installed strict command/result envelope codec;
- one narrow local receive/preparation boundary around the accepted local application;
- disposable exact/duplicate/ambiguous and malformed/mismatch fixtures;
- ImplementationReport and independent ReviewReport;
- owner closeout naming exactly one later Phase 4A gate.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-040-transport-envelope.md",
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/application.py",
    "src/agent_workflow/runtime/transport.py",
    "tests/test_runtime_transport.py",
    "tests/test_runtime_application.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_command_boundary.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-040-transport-envelope.md",
    ".awf/artifacts/review-report-runtime-v2-rts-040-transport-envelope.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "tests/test_runtime_transport.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_transport.py", "tests/test_runtime_application.py", "tests/test_runtime_core_boundary.py", "tests/test_runtime_command_boundary.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credential, token, private URL, provider/business payload, retained-event content or personal environment fact may enter envelope fixtures or reports.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-040-transport-envelope.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-040-transport-envelope.md"
}
-->
