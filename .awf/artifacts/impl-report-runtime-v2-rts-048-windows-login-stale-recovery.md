# RTS-048 Windows Login Stale-Incarnation Recovery ImplementationReport

## Result

Candidate repair complete for the two causal Windows `-04` logout/login defects. No state format,
lifecycle API, Task Scheduler topology, Agent Bus behavior or product boundary changed.

Independent L3 Review initially found one high strict-lease gap. The focused repair requires exact
lease state-root path/binding in Windows creation-aware cleanup; focused re-review returned `PASS`
with zero residual findings.

## Bounded transient readiness

Agent Bus health-probe failure now has one internal `TransientBusReadinessError` subtype. Profile,
state-root, config, workspace, executable, model and identity errors remain ordinary `NodeError` and
are attempted once.

The existing Task Scheduler wrapper retries only the same exact `node.reconcile(profile)` for four
total attempts with 15-second waits. After every transient failure it re-reads desired state;
`stopped` returns zero immediately and creates no listener. The final transient failure remains
nonzero and is logged by the existing task wrapper.

No retry occurs after a process record, lease, listener or provider effect: `foreground` performs
local readiness before writing process identity. No generic retry framework or Bus operation was
added. Historical `RestartOnFailure` remains rejected; the repair does not reintroduce it.

## Creation-aware exact stale convergence

The existing strict profile/digest/repository/state-root and lease/launch predicates remain the
eligibility gate. On Windows, an exact record additionally requires recorded creation FILETIME.
When the recorded PID is alive but its live FILETIME differs, the old incarnation is proved dead by
PID reuse. Cleanup removes only the exact process record and lease when the lease PID is dead or is
the same semantically dead PID.

Missing creation evidence, incomplete record/lease, any profile/root/launch drift or a different
live lease PID remains preserved and denied.
Windows strict cleanup additionally requires lease state-root path/binding to be explicitly present
and current; the broader legacy lease matcher remains unchanged elsewhere.

Managed reconcile attempts this exact cleanup only after desired `running` and before listener
snapshot/foreground acquisition. Task Scheduler stop/upgrade-stop attempts the same cleanup before
bound PID resolution. Successful cleanup never calls `taskkill` on the reused PID; only the exact
Task Scheduler target may receive `/End`, after which normal uninstall can converge.

## Focused regressions

- transient Bus readiness succeeds on a later bounded attempt;
- desired `stopped` aborts retry; exhaustion is exactly four attempts/three delays;
- nontransient identity error is attempted once with no delay;
- reused live PID plus exact record/lease/creation mismatch clears evidence, performs no taskkill and
  uses only the exact task target;
- missing creation evidence remains preserved even when PIDs later appear dead; and
- missing lease root/binding or a distinct live lease PID remains preserved with zero native calls;
- reconcile clears exact reused evidence before acquiring a fresh foreground identity.

Existing matching-creation taskkill, process-root drift, installed target, POSIX manager and facade
regressions remain green.

## Verification

- Focused lifecycle suite: **83 passed, 1 skipped**.
- Full repository suite: **884 passed, 5 skipped**.
- Exact-head ordinary CI `32551160937`: PASS, including Windows recovery/configuration and all
  installed-wheel jobs.
- Exact-head Binary Feasibility `32551160941`: PASS across all native/Rust cells and aggregates.
- Compileall, Ruff, Ruff format and `git diff --check`: PASS.
- Production added nonblank/noncomment lines: 65; within 70-line budget.
- Focused test added nonblank/noncomment lines: 192; raw additions 220, within budget.
- No dependency, representation, migration or external operation.

## Scope and continuation

Only `node.py`, `node_service.py`, `test_node_service.py` and frozen evidence files changed. The
preserved Windows `-04` identity remains failed with desired stopped and stale records/task intact.
Independent L3 Review and exact-head CI are `PASS`. Reviewed code was installed into the original
`-04` venv only for cleanup. The recorded PID was absent before cleanup; normal stop/uninstall
removed process record, lease, definition, install record and Scheduled Task. Desired/log evidence
remains. No manual signal or record edit occurred.

The current owner window explicitly prohibits another logout, so fresh `-05` was not created.
Phase 5 remains prohibited.
