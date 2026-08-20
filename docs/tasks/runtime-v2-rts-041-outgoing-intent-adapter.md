# TaskCard: RTS-041 Store-Owned Outgoing Intent and Bounded Adapter

## Task ID

runtime-v2-rts-041-outgoing-intent-adapter

## Goal

Extend the selected checksummed atomic RunStore so each accepted handoff or terminal transition
atomically retains the exact canonical Runtime v2 result-envelope bytes it authorizes, then add one
narrow Stage-blind dispatcher around an injected sender. The dispatcher must record an exact send
attempt before external I/O and one explicit `sent` or `ambiguous` observation afterward without
claiming handler success, ACK or Workflow transition authority.

This is a disposable no-model Phase 4A adapter candidate only. It does not import or execute the
production Agent Bus client, use a live queue, consume production/retained deliveries, replace the
production handler, adopt legacy state, migrate authority or change a default. RTS-031 Store,
RTS-035 application and RTS-040 envelope remain the only authority/application/transport-contract
surfaces used by the fixture.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@a31af9187026334148d9328d998944703c757c53`
- **Task branch**: `codex/runtime-v2-rts-041-outgoing-intent-adapter`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4A / RTS-041
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Passed prerequisite**: RTS-040 strict Stage-blind envelope, exact-head CI/Binary Feasibility and
  one independent Gate Review PASS

RTS-040 proves exact local envelope identity and Store-owned delivery/hash joins, but the selected
Store does not retain complete outgoing bytes and no selected adapter can prove the ordering around
an external send attempt. Current production outbox/inbox/handler behavior remains compatibility
evidence only and is not read, written or changed by this card.

## Frozen outgoing-intent boundary

### One atomic representation

The existing `awf.runtime-v2.atomic-authority.v1` envelope remains the sole persistent Runtime v2
authority representation and one logical writer remains its only mutator. Its schema may advance by
one version to represent, inside the same handoff/terminal event:

- exact `run_spec_sha256` and result-envelope delivery identity;
- exact target role and route;
- exact canonical UTF-8 result-envelope text plus a raw SHA-256 of those bytes; and
- the already validated handoff/terminal command and validation effect.

One immutable `OutgoingIntent` value may express that data at the Store port. The Store must verify
its own run/command/delivery/route/target/hash joins and preserve exact byte reconstruction. It must
not parse envelope payload as Workflow authority, introduce a second file/store, copy legacy
checkpoint/outbox/inbox state or treat send observation as Stage/terminal authorization.

The application must prepare the exact RTS-040 result envelope before its existing atomic
handoff/terminal commit and pass the matching `OutgoingIntent` in that same Store mutation. There is
no legal transition commit with an absent, foreign or hash-conflicting outgoing intent.

### One Stage-blind send boundary

One narrow `OutgoingIntentDispatcher` (or equivalently named value) may use read/write Store ports
and one injected `TransportSender` protocol:

1. Read the exact current Store-owned outgoing intent.
2. If no send observation exists, atomically record one exact `attempting` observation before I/O.
3. Pass only the Store-reconstructed canonical bytes plus delivery/route/target metadata to the
   injected sender once.
4. Record `sent` only when the sender explicitly returns success; an exception, false/unknown
   result or crash-visible `attempting` state becomes/preserves `ambiguous`.
5. On exact redelivery after `sent`, return stable no-send evidence. On `attempting` or `ambiguous`,
   return `AMBIGUOUS_NO_REPLAY` and do not call the sender again in this TaskCard.

The sender is Stage-blind and has no Store, journal, Workflow, provider, workspace, Artifact,
handler-success or ACK capability. The dispatcher must not open its own socket, shell or subprocess,
poll a queue, inspect delivery history, generate replacement identity, infer ACK or advance Workflow
Stage. A later isolated acceptance may provide a real Agent Bus sender behind this exact port.

### Send observations

The same atomic authority may append exact immutable transport observations for one outgoing
delivery:

- `attempting`: the exact delivery/envelope/target/route attempt is durable before sender entry;
- `ambiguous`: the attempt raised, returned false/unknown or cannot be proven successful;
- `sent`: the injected sender explicitly returned success for those exact bytes.

`prepared` is a derived status when the exact outgoing intent exists without an observation. No
stored state may mean ACK, handler success, downstream acceptance or exactly-once delivery. Same
identity/same fact is idempotent; same identity/different bytes, route, target, attempt or state
denies. `sent` cannot regress or be overwritten. Status remains read-only and reconstructs these
facts from validated authority without repair.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-041-outgoing-intent-adapter.md`
- `src/agent_workflow/runtime/__init__.py`
- `src/agent_workflow/runtime/application.py`
- `src/agent_workflow/runtime/outgoing.py`
- `src/agent_workflow/runtime/ports.py`
- `src/agent_workflow/runtime/store.py`
- `src/agent_workflow/runtime/transport.py`
- `tests/test_runtime_application.py`
- `tests/test_runtime_atomic_store.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_outgoing_adapter.py`
- `tests/test_runtime_transport.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-041-outgoing-intent-adapter.md`
- `.awf/artifacts/review-report-runtime-v2-rts-041-outgoing-intent-adapter.md`

After implementation, exact-head CI and one independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-041-outgoing-intent-adapter-implementation-report.md` and update only the
Phase 4A gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Editing production `scripts/`, CLI/facade/node/status/listener/service paths, Agent Bus client or
  server, manifest/schema or current delivery/outbox/inbox/checkpoint representations.
- Reading, converting, importing, shadowing, dual-writing or deleting RunLedger/context packet,
  checkpoint, outbox, inbox, RunEvidence, retained events or production state.
- Real network/queue I/O, real Bus send/receive/retry/ACK, handler-success assertion, historical
  delivery lookup, queue inspection/manipulation or live cross-machine acceptance.
- Automatic resend after `attempting` or `ambiguous`; this bounded candidate remains conservative
  even though the Frozen compatibility contract permits exact resend under stronger downstream
  dedupe evidence.
- Treating send state as Workflow transition, terminal, downstream acceptance, handler success or
  ACK authority; locally manufacturing an ACK observation.
- Provider execution/rendering changes, remote Git/GitHub, native lifecycle/process stop,
  credentials, generic transport/provider/plugin registry, scheduler, Coordinator, daemon,
  distributed lock, SQLite or Rust/Go production Runtime.
- Native launcher, packaging/distribution work, production adoption, representation migration,
  compatibility deletion, default switch, release, retained-event operation or destructive cleanup.
- Editing the Frozen semantic contract, ADR-0006, completed Phase 2/3/RTS-040 evidence or shared
  fault fixture.

## Budgets and stop rules

- New `outgoing.py`: at most 300 nonblank/noncomment lines.
- Store/ports/transport/application refinements: at most 300 net nonblank/noncomment lines combined;
  no copied Workflow, envelope codec, provider, workspace or Artifact body.
- New focused adapter tests plus existing-test refinements: at most 900 net nonblank/noncomment
  lines.
- No new dependency or persistent file family; installed Runtime remains standard-library only.
- One outgoing-intent value, one send-observation value/state set, one dispatcher, one sender port
  and the existing Store/application/envelope; no adapter registry or background component.
- One candidate Gate Review and at most two L3 repair/focused re-review rounds.
- If acceptance requires production-handler/Bus edits, a second authority file/store, send-before-
  attempt ordering, ambiguous automatic retry, Stage authority in the adapter, live/retained events,
  migration or any budget breach, stop with `PLAN_CONFLICT` rather than widening scope.

## Acceptance criteria

- [ ] Task ID equals branch leaf; every changed path stays within frozen/closeout scope.
- [ ] One immutable outgoing-intent value reconstructs exact canonical envelope bytes and binds
      RunSpec/delivery/route/target/hash without becoming a second authority representation.
- [ ] Handoff/terminal validation effect and complete outgoing intent commit in one existing Store
      transaction; missing/foreign/conflicting bytes deny with byte-stable authority.
- [ ] Store schema/load/recovery rejects unknown, corrupt, non-UTF-8, hash-drifted, identity-drifted,
      route/target-conflicting and illegal observation histories.
- [ ] One Stage-blind dispatcher records exact `attempting` before the injected sender is called and
      records only `sent` or `ambiguous` afterward.
- [ ] Sender success, false/unknown, exception and crash-visible attempting fixtures preserve exact
      outcomes; `attempting`/`ambiguous` never call sender again in this TaskCard.
- [ ] Exact replay after `sent` performs zero send calls; conflicting replay/observation denies and
      cannot regress or rewrite `sent`.
- [ ] Status/read APIs reconstruct `prepared|attempting|ambiguous|sent`, exact identity and one legal
      next action without writing bytes or claiming handler success/ACK.
- [ ] Disposable no-model PASS, REQUEST_CHANGES/rework/PASS and BLOCKED sequences still preserve
      exact RTS-035/040 application/envelope outcomes.
- [ ] Fault fixtures snapshot Store bytes and sender-call evidence at every pre-send/post-attempt
      boundary and prove exact stability where mutation is prohibited.
- [ ] Static boundary tests prove the sender port is Stage/Store/Workflow/provider/Artifact-blind;
      the dispatcher has no socket/HTTP/subprocess/queue/history/ACK/production-script surface.
- [ ] Existing production `awf.delivery.v1`, outbox/inbox/checkpoint and Agent Bus code remain
      byte-for-byte unchanged.
- [ ] LOC/dependency/single-representation/single-dispatcher/no-background budgets pass.
- [ ] Focused tests, full pytest/Ruff and ordinary Linux/Windows/macOS/installed-wheel CI pass on the
      candidate head; automatically triggered Binary Feasibility remains green evidence.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; any L3 repair receives focused re-review
      by the same Reviewer.
- [ ] Closeout names exactly one fresh isolated Mac-to-Windows no-model request/result acceptance
      gate without claiming production adoption, ACK, migration, default, lifecycle, launcher or
      release.

## Verification

- Local Mac: AST/static/import checks, disposable fake sender call counters, exact authority byte
  snapshots, scope/LOC/dependency audit and `git diff --check` only.
- CI: focused Store/application/envelope/adapter tests plus full pytest/Ruff, installed-wheel and
  ordinary cross-platform jobs.
- Fault fixtures inject sender success/false/exception and corrupted intent/observation fields,
  assert attempting-before-call and prove no resend after ambiguous/sent.
- Independent Review checks atomic intent/effect ordering, send-attempt crash semantics, immutable
  reconstruction, no Workflow/ACK ownership leak, status read-only behavior and all production/live
  boundaries.

## Required output

- exact Store-owned reconstructable outgoing intent in the existing atomic authority;
- one narrow Stage-blind sender port and dispatcher with durable send observations;
- disposable success/ambiguity/replay/corruption fixtures and preserved application sequences;
- ImplementationReport and independent ReviewReport;
- owner closeout naming exactly one fresh isolated Mac-to-Windows no-model acceptance gate.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-041-outgoing-intent-adapter.md",
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/application.py",
    "src/agent_workflow/runtime/outgoing.py",
    "src/agent_workflow/runtime/ports.py",
    "src/agent_workflow/runtime/store.py",
    "src/agent_workflow/runtime/transport.py",
    "tests/test_runtime_application.py",
    "tests/test_runtime_atomic_store.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_outgoing_adapter.py",
    "tests/test_runtime_transport.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-041-outgoing-intent-adapter.md",
    ".awf/artifacts/review-report-runtime-v2-rts-041-outgoing-intent-adapter.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "tests/test_runtime_outgoing_adapter.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_outgoing_adapter.py", "tests/test_runtime_atomic_store.py", "tests/test_runtime_application.py", "tests/test_runtime_transport.py", "tests/test_runtime_core_boundary.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credential, token, private URL, provider/business payload, retained-event content or personal environment fact may enter adapter fixtures or reports.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-041-outgoing-intent-adapter.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-041-outgoing-intent-adapter.md"
}
-->
