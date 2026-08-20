# RTS-031 Atomic RunStore and Invocation Journal Closeout

## Result

`PASS` for the disposable local checksummed atomic-file Store and per-invocation journal boundary.

One checksummed `authority.json` envelope now owns immutable RunSpec, Workflow transitions, bounded
attempt/rework consumption, embedded invocation facts, outgoing handoff intent and terminal. One
exact `O_EXCL` writer lock serializes mutations. Status and journal reads validate the same owner
envelope and reject corrupt, foreign, drifted, newer-schema or redirected authority without repair.

The implementation changes no production/default handler. It creates no separate journal,
checkpoint, outbox or inbox authority, adds no dependency, and performs no provider, Agent Bus,
Git/GitHub, OS manager, legacy-state, migration or destructive operation.

## Verification

- Candidate ordinary CI `32341036671` at exact head `082f9ae`: full Linux and Windows suites,
  Ruff, macOS runtime and all three installed-wheel jobs passed.
- Automatically triggered Binary Feasibility `32341036800` at the same head: passed.
- Independent TaskCard Gate Review: one HIGH parent-path redirection finding.
- Repair `2d4576b`: shared path guard plus nine status/journal/mutation directory-component cases.
- Same independent Reviewer focused re-review of exact head `082f9ae`: `PASS`, including additional
  authority-file and lock-file redirection smokes.
- Final budgets: Store 650/650 nonblank/noncomment lines; focused tests 574/900; dependencies 0;
  one authority envelope and one writer lock per run.

## Exact successor production seam

The only successor seam authorized by this closeout is a separately frozen `RTS-032` TaskCard for
the production provider-renderer boundary. It may move the existing Codex, OpenCode and Pi command
construction behind narrow installed Runtime v2 renderers that receive a fully bound
`InvocationSpec` immediately before the existing provider spawn boundary.

RTS-032 must keep the current RunLedger/checkpoint/outbox/inbox path as the sole production authority
and must not read or write the RTS-031 Store. A renderer cannot interpret Workflow Stage, authorize
an invocation, launch a process, mutate Runtime state, send/ACK transport, invent a generic provider
framework or become an implicit fallback. Exact argv/environment/stdin/workspace behavior and
canonical rendered identity must remain regression-locked and independently reversible.

## Rollback and non-claims

Reverting the isolated Runtime package implementation, tests and closeout references removes the
candidate without touching production or retained state. Phase 3 is not complete. Store adoption,
workspace/Git lifecycle, provider recovery, business transitions, `run/status/stop`, transport,
lifecycle, distribution, default, migration, release and old-representation deletion remain behind
later separately frozen gates.
