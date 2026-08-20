# RTS-041 Store-Owned Outgoing Intent and Bounded Adapter Closeout

## Result

`PASS` for the independently reversible disposable Phase 4A outgoing-intent adapter boundary.

The selected checksummed atomic RunStore now retains the exact canonical result-envelope bytes in
the same authority mutation as each accepted handoff or terminal effect. One narrow Stage-blind
dispatcher persists `attempting` before injected sender I/O and then records only `sent` or
`ambiguous`. Stale, corrupt, stopped and in-flight state deny or preserve ambiguity; none can
authorize automatic replay.

Production handlers, Agent Bus, current RunLedger/checkpoint/outbox/inbox/RunEvidence authority,
retained deliveries, defaults, migration, native lifecycle, launcher and release paths are
unchanged.

## Verification

- Independent Gate Review initially returned `REQUEST_CHANGES` at `a0abb83`, then focused
  re-review returned `PASS` with zero findings at repaired candidate `beec962`.
- Exact repaired-head ordinary CI `32376015654` passed Ruff, full Linux, Windows recovery, macOS
  runtime, resource/workflow/distribution and all installed-wheel jobs.
- Exact repaired-head Binary Feasibility `32376016069` passed the five-target native/Rust comparison
  matrix and aggregates.
- Local compileall, AST/static boundary checks, deterministic Store/dispatcher smoke and
  `git diff --check` passed.
- Final budgets: outgoing 219/300 nonblank/noncomment lines; Store/ports/transport/application net
  219/300; focused tests net 388/900; no dependency, second representation, adapter registry or
  background component.
- Scope audit found only frozen implementation paths before closeout, with no generated/build,
  mass-formatting, production Runtime or unrelated tracked changes.

## Closed review failures

The first reviewer found that concurrent dispatchers holding stale `prepared` snapshots could both
reach sender I/O, and that stopped-plus-`prepared` status exposed an illegal send action. Repair
`beec962` requires an authoritative Store `SAFE_CONTINUE` attempt decision immediately before I/O,
projects duplicate in-flight facts as `AMBIGUOUS_NO_REPLAY`, and gives stopped state precedence.
Focused fixtures prove exactly one sender call under stale-read interleaving and zero calls for a
stopped run. No ACK, handler-success or exactly-once claim was introduced.

## Exact successor gate

The only successor authorized by this closeout is a separately frozen **RTS-042 fresh isolated
Mac-to-Windows no-model request/result acceptance**. It must place a real Agent Bus sender behind
the selected adapter boundary, use fresh isolated Bus/config/state/queue identities, run a real
child handler, prove external success-gated ACK and scoped queues `0/0 -> 0/0`, and preserve exact
request/result identity.

RTS-042 may not invoke a model or business handler, inspect or operate production/retained events,
adopt or dual-write production authority, change Agent Bus itself, migrate state, change defaults,
begin lifecycle/launcher work, release or delete compatibility. Its TaskCard must be frozen before
any live operation.

## Rollback and non-claims

Reverting RTS-041 removes only the isolated outgoing-intent/dispatcher/test surfaces and disposable
state. No production state rollback is required. RTS-041 does not claim Agent Bus delivery,
handler success, ACK, cross-machine acceptance, migration, lifecycle, launcher, release or
compatibility deletion.
