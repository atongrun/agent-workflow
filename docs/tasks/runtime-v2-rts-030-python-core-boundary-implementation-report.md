# RTS-030 Selected Python Core Boundary Closeout

## Result

`PASS` for the first independently reversible Phase 3 package/interface boundary.

`agent_workflow.runtime` is importable from source and installed wheels and now owns only immutable
contract values and typed ports. `RunSpec` binds owner/compiler intent, `InvocationSpec` is fully
bound before provider rendering, `RenderedInvocation` has a canonical launch identity, `RunStore`
is the sole logical Workflow writer port, each invocation has one journal port, and status remains
read-only by interface and static dependency tests.

The new package imports only the standard library and its own relative modules. It does not import
packaged operations scripts, manipulate `sys.path`, implement effects, add a dependency, or change
the existing production/default Runtime.

## Verification

- Candidate ordinary CI `32335336859`: all Linux/Windows tests, macOS runtime and three installed-
  wheel jobs passed after one L1 import-order correction.
- Candidate Binary Feasibility `32335336776`: all automatically triggered jobs passed.
- Independent TaskCard Gate Review: one HIGH canonical launch-identity finding.
- Repair `c9e2c5f`: exact `RenderedInvocation` canonical bytes/SHA plus field-drift and derived
  `LaunchIntent` tests.
- Repair ordinary CI `32336141952`: Ruff, complete Linux tests/distribution validation, macOS runtime
  and all three installed-wheel jobs passed before closeout; final publication-head CI remains the
  PR merge gate.
- Same independent Reviewer focused re-review of repair/evidence head `b7281ae`: `PASS`.
- Final package budget: 679/700 nonblank/noncomment lines; focused tests: 450/900; dependencies: 0.

## Exact successor integration seam

The only successor seam authorized by this closeout is a separately frozen `RTS-031` TaskCard that
implements the checksummed atomic-file `RunStore` and one per-invocation journal behind these ports
in pure disposable local fixtures.

RTS-031 must cover exact writer identity/locking, immutable RunSpec re-open, checksum/corruption
denial, authorization/launch/result/effect separation, outgoing-intent and terminal ordering,
idempotent replay, ambiguity/no-replay and read-only reconstruction. It must not migrate or dual-
write a production handler, read legacy state, delete checkpoint/outbox/inbox, invoke providers,
touch Agent Bus/Git/GitHub/OS truth, or change a default. The first production integration seam is
deferred until that Store/journal implementation passes its own fixtures and Gate Review.

## Rollback and non-claims

Reverting the RTS-030 package/tests/artifacts and closeout references removes the candidate without
touching production state. No live/retained delivery, queue, listener, provider, repository or state
root was operated. Phase 3 as a whole is not complete; transport, lifecycle, distribution, default,
migration, release and old-representation deletion remain behind later gates.
