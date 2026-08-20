# TaskCard: RTS-042 Fresh Isolated Mac-to-Windows Runtime v2 Transport Acceptance

## Task ID

runtime-v2-rts-042-cross-machine-acceptance

## Goal

Prove one fresh, fully isolated Mac-to-Windows no-model command/result exchange over a real Agent
Bus, with the return result sent through the selected RTS-041 Store-owned
`OutgoingIntentDispatcher` boundary. Both Agent Bus handler processes must launch a real bounded
child, return success only after exact envelope validation and durable evidence, and leave the two
scoped queues at `0/0 -> 0/0` through normal handler-success ACK behavior.

This is a disposable Phase 4A external-boundary acceptance only. It does not adopt the Runtime v2
Store or adapter in production, edit Agent Bus, invoke a provider/model/business handler, inspect
any production/retained delivery, migrate authority, change a default, begin lifecycle/launcher
work, release or delete compatibility.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@adc79941c142c7b3fc79e7eb517ffba6d0444760`
- **Task branch**: `codex/runtime-v2-rts-042-cross-machine-acceptance`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4A / RTS-042
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Passed prerequisite**: RTS-041 exact Store-owned outgoing result bytes and conservative
  attempt-before-I/O dispatcher, independently reviewed and merged through PR #114

The current production Runtime, Agent Bus service, role queues, RunLedger, checkpoint, outbox,
inbox and retained evidence are outside this card. Historical no-model Preflight evidence may be
read only as a protocol/isolation precedent; none of its identities, credentials, state or events
may be reused.

## Frozen acceptance shape

### Fresh command path: Mac to Windows

One credential-free fixture creates a strict canonical RTS-040 `CommandEnvelope` with fresh run,
task, RunSpec, source/target invocation, authorization, route, payload and delivery identities. A
narrow acceptance-only Agent Bus CLI sender submits exactly those bytes from a fresh source role to
a fresh target role on the isolated Bus as the JSON payload, using native argv and no shell.

The Windows listener uses Agent Bus `--on-argv` with fixed tokens and payload placeholders. Its
handler must:

1. receive the complete `{payload}` as one structured argv value, canonicalize it, and decode the
   exact command envelope;
2. bind event type, source/target role, route, delivery and payload identity to the expected fresh
   acceptance identity before any child starts;
3. launch one bounded `sys.executable -c` child with closed stdin and no model/provider command;
4. persist credential-free target evidence only after the child returns zero; and
5. prepare one causally bound canonical `ResultEnvelope`, commit it with one matching
   `OutgoingIntent` to a fresh disposable RTS-041 Store, and invoke the selected
   `OutgoingIntentDispatcher` using the real isolated Agent Bus sender.

The handler must return non-zero before result send if envelope identity or child execution fails.
Agent Bus alone owns whether the incoming command is ACKed after handler success.

### Fresh result path: Windows to Mac

The real sender behind `OutgoingIntentDispatcher` receives only the Store-reconstructed canonical
result bytes and exact delivery/target/route metadata. It may map those already-bound values to one
`agent-bus send` argv and return `TransportSendReceipt(True, evidence_sha256)` only for an explicit
zero exit. Non-zero, timeout, unknown or exception returns/raises without secrets and therefore
leaves the Store `ambiguous`; this card never resends that identity.

The Mac listener uses a second exact `--on-argv` registration and likewise receives the complete
`{payload}` as one argv value. Its handler canonical-decodes the result, joins it to the original
command delivery and expected source/target identities, launches one bounded child, then persists
source evidence and returns zero. Agent Bus alone owns the result ACK after handler success. No
local Store observation is called ACK, handler success, downstream acceptance or exactly-once
delivery.

### Evidence and queue convergence

Before the first send, payload-blind pending counts for only the isolated Windows coder and Mac
reviewer queues must be exactly zero. The fresh architect identity sends the initial command but
does not run a listener. After source evidence exists, both scoped pending counts must return to
zero within the bounded wait. A credential-safe isolated Bus audit must prove exactly two fresh
acceptance records with distinct event identities and the expected event types; both are
acknowledged, with pending, delivered, failed, retry and last-error facts clear. The audit reads
only the isolated database/API selected by the fresh acceptance identity.

The report must join:

- exact repository candidate SHA on Mac and Windows;
- exact Agent Bus version/commit or installed package identity;
- unique acceptance scope, RunSpec, command/result delivery and event identities;
- target/source child return codes and handler evidence digests;
- Store result intent, `attempting` then `sent` observations and byte hashes;
- scoped `0/0 -> 0/0` queue counts plus isolated ACK audit; and
- exact cleanup identity and post-cleanup absence checks.

No token, private URL, private IP, payload content, machine username or credential-bearing argv/log
may enter repository evidence.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-042-cross-machine-acceptance.md`
- `tests/fixtures/runtime_v2_bus_acceptance.py`
- `tests/test_runtime_bus_acceptance.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-042-cross-machine-acceptance.md`
- `.awf/artifacts/review-report-runtime-v2-rts-042-cross-machine-acceptance.md`

After implementation, exact candidate CI, live acceptance and one independent Gate Review PASS,
owner closeout may add
`docs/tasks/runtime-v2-rts-042-cross-machine-acceptance-implementation-report.md` and update only
the Phase 4A gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Editing `src/agent_workflow/runtime/`, production `scripts/`, CLI/facade/node/status/listener,
  Agent Bus client/server, manifest/schema, packaging/workflow or dependency files.
- Reading, identifying, ACKing, requeueing, recovering, redispatching, moving, failing or deleting
  any production, retained, historical, business or previous-acceptance event.
- Reusing an existing Bus database, token, role, config, state root, process, listener lease,
  delivery/event identity or queue; querying any unscoped role or endpoint.
- Invoking Codex, OpenCode, Pi or another model/provider; running the production role handler or
  changing Workflow Stage/terminal authority from an envelope or Bus fact.
- Calling the initial command send a Runtime Store transition; the owner command remains external
  input while the return result alone exercises the selected RTS-041 outgoing boundary.
- Automatic resend after `attempting`/`ambiguous`, manual ACK, exactly-once claims, hidden recovery,
  payload-history inspection or retry around a handler failure.
- Production Store adoption, legacy dual write/import/deletion, state migration, default switch,
  native lifecycle/launcher, release, compatibility deletion or broad cleanup.

## Budgets and stop/fallback rules

- One acceptance fixture: at most 450 nonblank/noncomment lines.
- One focused test module: at most 650 nonblank/noncomment lines.
- No new dependency, Runtime persistent family, generic Bus/provider adapter, background daemon or
  production import direction.
- Exactly one fresh isolated Bus, three fresh role credentials (architect/coder/reviewer), two
  listeners (Windows coder/Mac reviewer), two acceptance events and two bounded child processes;
  no model or business event.
- Development may use deterministic local fake-CLI tests. Live execution receives one fresh
  identity set and no event-level retry budget.
- Pre-send setup/readiness failure may be repaired once without sending. After the first send, any
  timeout, non-zero handler, `attempting`/`ambiguous`, nonzero queue, identity drift or uncertain ACK
  stops live execution as `EXTERNAL_BLOCKED`; preserve the isolated evidence and do not resend,
  ACK, requeue or replace either event.
- Cleanup may target only resources carrying the exact fresh acceptance scope plus verified
  process/config/state/database bindings. If exact targeting is unavailable, leave the isolated
  resource stopped and report `EXTERNAL_BLOCKED`; never widen cleanup or touch production.
- One TaskCard Gate Review after candidate evidence and at most one L3 repair/focused re-review
  round. If acceptance requires Runtime Core/production-handler/Agent Bus edits, a second Store,
  weaker identity, manual ACK, ambiguous replay, unscoped queue/history access or a budget breach,
  stop with `PLAN_CONFLICT`.

## Acceptance criteria

- [ ] Task ID equals branch leaf; every changed path stays within frozen/closeout scope.
- [ ] Fixture source and static tests prove no model/provider, production scripts/state, socket
      implementation, manual ACK/requeue/retry, shell command string or generic framework surface.
- [ ] Command and result bytes are strict canonical RTS-040 envelopes with fresh exact identity;
      malformed, foreign, stale, role/route/payload/causation drift denies before child execution.
- [ ] Windows request handler and Mac result handler each launch exactly one bounded real child and
      persist credential-free evidence only after child return code zero.
- [ ] Windows result commits one exact `OutgoingIntent` in one disposable Store authority and the
      unmodified RTS-041 dispatcher persists `attempting` before real Agent Bus sender entry.
- [ ] Real sender sends only Store-reconstructed bytes; explicit CLI success records `sent`, while
      local fault fixtures prove false/non-zero/timeout/exception becomes ambiguity with zero replay.
- [ ] Exact candidate SHA and installed package import work on fresh Mac and Windows checkouts;
      Agent Bus consumer supports the pinned structured `--on-argv` contract.
- [ ] One real Mac-to-Windows command and one Windows-to-Mac result complete with distinct isolated
      event/delivery identities, exact causation, handler/child success and no provider invocation.
- [ ] Isolated scoped queues prove `0/0 -> 0/0`; exact isolated audit proves two acknowledged
      records, zero pending/delivered/failed/retry/last-error facts, with no ACK manufactured by
      Runtime evidence.
- [ ] Production Bus API/queues/database/config/state and retained events are neither queried nor
      changed; evidence and post-cleanup checks prove exact isolated bindings without exposing
      secrets or requiring a production liveness probe.
- [ ] Exact-target cleanup removes/stops only disposable acceptance resources; no production
      process or service command is issued.
- [ ] LOC/dependency/no-core-edit/no-second-representation/no-background budgets pass.
- [ ] Focused fixture tests, full pytest/Ruff and ordinary Linux/Windows/macOS/installed-wheel CI
      pass on the candidate head; automatically triggered Binary Feasibility remains green.
- [ ] One independent TaskCard Gate Reviewer returns `PASS` after inspecting local/static, exact CI
      and credential-safe live evidence; any L3 repair receives focused re-review.
- [ ] Closeout names exactly one Phase 4B native lifecycle TaskCard gate without claiming
      production adoption, migration, default, launcher, release or compatibility deletion.

## Verification sequence

1. Freeze this TaskCard in its own commit and push it before any live operation.
2. Implement only the acceptance fixture/tests; run local compile/AST/fake-CLI/scope/LOC/diff
   checks, then exact-head CI/Binary on the code candidate.
3. From that exact candidate, create fresh isolated Mac/Windows checkouts, Bus/config/state/role
   identities and listeners; verify scoped zero baseline without reading other queues.
4. Execute the two-event no-model exchange once. On the first post-send uncertainty, stop under the
   preserved-event rule instead of retrying.
5. Capture credential-safe Store/handler/queue/ACK/audit evidence, perform exact-target cleanup,
   and verify absence plus production separation without inspecting production payload/history.
6. Add the ImplementationReport, run final exact-head required CI, then obtain one independent Gate
   Review. Repair only evidence-backed findings under the risk policy.

## Required output

- one bounded acceptance-only Agent Bus sender/handler fixture behind the selected Runtime ports;
- deterministic local success/failure/identity/no-replay/static boundary tests;
- one fresh isolated two-event Mac-to-Windows/Windows-to-Mac no-model acceptance record;
- ImplementationReport and independent ReviewReport;
- closeout naming exactly one separately frozen Phase 4B native-lifecycle gate.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-042-cross-machine-acceptance.md",
    "tests/fixtures/runtime_v2_bus_acceptance.py",
    "tests/test_runtime_bus_acceptance.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-042-cross-machine-acceptance.md",
    ".awf/artifacts/review-report-runtime-v2-rts-042-cross-machine-acceptance.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "tests/fixtures/runtime_v2_bus_acceptance.py", "tests/test_runtime_bus_acceptance.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_bus_acceptance.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No token, private URL/IP, machine username, provider/business payload, retained-event content or credential-bearing argv/log may enter fixture output or repository reports."
}
-->
