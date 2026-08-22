# TaskCard: RTS-048 Windows Login Stale-Incarnation Recovery

## Task ID

runtime-v2-rts-048-windows-login-stale-recovery

## Goal

Repair the two causal L3 defects exposed by the preserved RTS-046 Windows `-04` logout/login scope:

1. Task Scheduler logon reconcile must tolerate a bounded transient Agent Bus health failure without
   retrying identity/config/model errors or ignoring desired `stopped`.
2. A fully bound old Windows process/lease whose live PID has a different creation FILETIME must be
   treated as an exactly proved dead incarnation: never signal the reused PID, clear only that exact
   stale record/lease, and allow normal reconcile or stop/uninstall convergence.

No state format, lifecycle API, manager topology, Agent Bus contract or product boundary changes.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Finding head**: `1812330`
- **Task branch**: `codex/runtime-v2-rts-048-windows-login-stale-recovery`
- **Preserved failure identity**: `rts046-win-task-20260822-04`
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`, lifecycle/process section
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4B

## Frozen repair behavior

### Bounded transient readiness

- Introduce one internal readiness-error subtype used only for transient Agent Bus health-probe
  failure. Existing profile/root/config/workspace/executable/model failures remain ordinary
  `NodeError` and are never retried.
- The Task Scheduler wrapper may retry the same exact `node.reconcile(profile)` a bounded number of
  times. Before every retry it re-reads the exact desired state; `stopped` returns success without
  starting a listener.
- No process record, lease, Bus listener or provider effect exists before local readiness passes.
- Do not use Task Scheduler `RestartOnFailure`: prior live evidence rejected it as unreliable.
- Do not add a daemon, background loop, generic retry framework or configurable policy.

### Creation-aware exact stale convergence

- Reuse the existing strict managed record/profile/state-root and lease/launch identity predicates.
- On Windows only, when all those facts match and the recorded creation FILETIME differs from the
  live PID's FILETIME, the recorded incarnation is dead/PID-reused.
- Never call `taskkill` or signal that PID. Remove only the exact process record and lease when the
  lease PID is also dead or is the same semantically dead recorded PID.
- Missing creation evidence, incomplete record/lease, profile/root/launch drift or a different live
  lease PID remains fail-closed and preserved.
- Managed reconcile may attempt this exact cleanup before foreground acquisition. Managed stop may
  attempt it before bound-PID resolution; after successful cleanup it may operate only the exact
  Task Scheduler target and normal uninstall state.

## Writable scope

- `docs/tasks/runtime-v2-rts-048-windows-login-stale-recovery.md`
- `src/agent_workflow/node.py`
- `src/agent_workflow/node_service.py`
- `tests/test_node.py`
- `tests/test_node_service.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-048-windows-login-stale-recovery.md`
- `.awf/artifacts/review-report-runtime-v2-rts-048-windows-login-stale-recovery.md`

After Review/CI PASS, closeout may additionally update:

- `docs/tasks/runtime-v2-rts-048-windows-login-stale-recovery-report.md`
- `.awf/artifacts/impl-report-runtime-v2-rts-046-native-manager-acceptance.md`
- `docs/tasks/runtime-v2-rts-046-native-manager-acceptance.md` (fresh successor scope only)
- `docs/plans/runtime-v2-development-plan.md`
- `HANDOFF.md`
- `ROADMAP.md`

## Prohibited actions

- Editing Runtime Core, facade/CLI/status, scripts/Agent Bus/listener code, schemas, workflows,
  packaging, dependencies or unrelated tests.
- New record fields/formats, migration, repair-by-guessing, PID/process-name signaling, force kill or
  manual record cleanup.
- Retry of profile/config/workspace/executable/model/identity errors; unbounded retry; provider/event
  retry; Agent Bus ACK/requeue/recovery.
- Task Scheduler `RestartOnFailure`, login-policy changes, reboot, another logout or simulated login.
- Agent Host, onboarding, Finding Phase B, launcher, distribution, release or Phase 5 work.
- Reusing preserved Windows `-04` as acceptance PASS after repair.

## Acceptance criteria

- [x] Task ID equals branch leaf and every changed path remains in frozen scope.
- [x] Only explicit transient Bus health failure is retried, with a fixed bounded attempt/delay budget.
- [x] Desired `stopped` between attempts prevents all further reconcile/start effects.
- [x] Non-transient readiness, identity and configuration failures are attempted once and preserved.
- [x] Exact Windows creation mismatch plus complete record/lease join clears only stale evidence and
      never signals/taskkills the reused PID.
- [x] Missing/incomplete/drifted identity or a distinct live lease PID remains preserved with zero
      native calls.
- [x] Reconcile can acquire a new foreground identity only after exact stale cleanup; stop/uninstall
      can converge through the exact manager target without signaling the reused PID.
- [x] Existing matching-creation Task Scheduler taskkill and all POSIX lifecycle behavior remain green.
- [x] Focused additions are at most 70 production nonblank/noncomment lines and 220 test lines; no
      dependency, representation or abstraction is added.
- [x] Focused/full tests, Ruff/format and exact-head cross-platform CI pass.
- [x] One independent L3 Gate Review returns `PASS`; semantic findings receive focused re-review.
- [ ] Preserved `-04` is cleaned only through reviewed code; acceptance resumes under fresh `-05`.

## Verification

```text
python -m compileall -q src/agent_workflow/node.py src/agent_workflow/node_service.py
python -m pytest -q tests/test_node.py tests/test_node_service.py tests/test_facade.py
ruff check src/agent_workflow/node.py src/agent_workflow/node_service.py tests/test_node.py tests/test_node_service.py
ruff format --check src/agent_workflow/node.py src/agent_workflow/node_service.py tests/test_node.py tests/test_node_service.py
git diff --check
```

## Failure handling

- Routine test/lint failure: repair within scope and rerun affected checks.
- Need for new state authority, record format, Bus behavior, login policy or manager design: stop for
  architecture/owner decision.
- Successful repair does not make `-04` PASS and does not authorize Phase 5.

## Required output

- one minimal readiness/stale-incarnation repair;
- focused causal regressions;
- ImplementationReport and independent ReviewReport;
- exact cleanup of `-04` with reviewed code, then one fresh RTS-046 `-05` continuation only.
