# ImplementationReport: RTS-041 Store-Owned Outgoing Intent and Bounded Adapter

## Outcome

Implemented one reconstructable `OutgoingIntent` inside the existing checksummed atomic authority,
one immutable transport-send observation set, and one conservative Stage-blind
`OutgoingIntentDispatcher` around an injected `TransportSender` port.

Each handoff or terminal mutation now commits its validation effect, transition command and exact
canonical Runtime v2 result-envelope bytes in one Store replacement. No second outbox/authority
file, legacy dual write, production handler/Bus change, default, migration, lifecycle, launcher or
release surface was added.

## Exact ordering and recovery

- `OutgoingIntent` decodes and byte-round-trips one strict RTS-040 `ResultEnvelope`, verifies raw
  envelope SHA-256 and binds RunSpec, delivery, route and target.
- Store replay validation joins the envelope's source invocation/authorization, payload hash and
  causation delivery to the exact authorization/result/effect that owns the transition.
- `prepared` is derived only from a durable outgoing intent with no send observation.
- Dispatcher records one deterministic exact `attempting` observation before calling the injected
  sender.
- Explicit true receipt records `sent`; false, unknown, invalid receipt or ordinary exception
  records `ambiguous` without persisting exception text.
- A crash after sender entry leaves `attempting`; both `attempting` and `ambiguous` return
  `AMBIGUOUS_NO_REPLAY` and never call the sender again in this bounded candidate.
- Exact `sent` replay is byte-stable and performs zero sender calls. Conflicting delivery, bytes,
  target, route, attempt or state denies and cannot regress `sent`.
- `AtomicStatusReader.outgoing()` is read-only, exposes exact intent/observation identity plus one
  legal next action, and treats an active writer lock as ambiguous without mutation.

No local fact means downstream acceptance, handler success, ACK or exactly-once transport.

## Files and budgets

- `src/agent_workflow/runtime/outgoing.py`: 222 nonblank/noncomment lines (budget: 300).
- Store/ports/transport/application refinements remain below the 300 net-line combined budget.
- `tests/test_runtime_outgoing_adapter.py` plus focused refinements remain below the 900-line test
  budget.
- Store schema advances from 2 to 3 fail-closed for fresh disposable Runtime v2 state; this card
  provides no migration/fallback and reads no old or production state.
- No dependency, persistent file family, adapter registry or background component was added.

## Focused evidence

- `python3 -m compileall -q` for the Runtime package and affected focused tests — PASS.
- Direct standalone disposable Store/dispatcher smoke — PASS for atomic prepared intent,
  attempting-before-sender, exact byte delivery, sent observation and zero-call sent replay.
- AST/import/line-length/static boundary checks — PASS.
- `git diff --check` — PASS.
- Scope audit contains only frozen RTS-041 paths and no tracked generated/build/mass-formatting or
  unrelated repository changes.

Exact-head full pytest/Ruff/installed-wheel/cross-platform and Binary Feasibility evidence remains
the candidate CI gate; local macOS intentionally did not install or run pytest/Ruff.

## Fault coverage

- canonical envelope SHA/text/target mismatch;
- missing/foreign Store intent and command/source-delivery/causation drift;
- sender true, false, unknown, invalid receipt and exception;
- crash-visible attempting with no automatic re-entry;
- exact sent and ambiguous replay with zero additional sender calls;
- conflicting attempt identity, illegal result-before-attempt and state regression;
- corrupt stored intent with a recomputed authority checksum;
- byte-stable read-only outgoing status and prohibited second representation;
- static prohibition of sockets, HTTP, subprocess, Agent Bus implementation, queue/history and ACK.

## Preserved limitations and next gate

This card uses an injected fake sender only. It does not import or execute Agent Bus, observe handler
success/ACK, inspect queues or prove cross-machine behavior. After exact-head CI and independent
Gate Review PASS, the sole next Phase 4A gate is a fresh isolated Mac-to-Windows no-model
request/result acceptance using the selected adapter boundary. That later gate must use fresh
identities and isolated queues/config/state, and must not touch production or retained deliveries.
