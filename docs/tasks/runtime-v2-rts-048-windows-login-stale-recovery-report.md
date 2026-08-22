# RTS-048 Windows Login Stale-Incarnation Recovery Closeout

## Result

`PASS`. The repair closes the transient login-readiness and PID-reuse stale-convergence defects
without changing state formats, lifecycle API, Task Scheduler topology, Agent Bus or product scope.

## Behavior

- Only explicit pre-listener Agent Bus health failure retries: four attempts, three 15-second waits.
- Desired `stopped` cancels retry immediately; other readiness/identity/config/model errors run once.
- Windows stale cleanup requires complete strict record and lease profile/root/launch identity plus
  recorded/live creation FILETIME mismatch.
- A reused PID is never signaled or taskkilled. Exact stale record/lease may be removed, then only the
  deterministic Scheduled Task target may receive `/End`.
- Missing creation, missing lease root/binding, incomplete/drifted identity or a distinct live lease
  PID remains preserved with zero native calls.
- Reconcile can acquire a fresh foreground identity only after exact stale cleanup.

## Verification

- Focused lifecycle suite: 83 passed, 1 skipped.
- Full suite: 884 passed, 5 skipped.
- Compileall, Ruff, Ruff format and `git diff --check`: PASS.
- Independent L3 Review: initial high finding repaired; focused re-review PASS with zero findings.
- Ordinary CI `32551160937`: PASS.
- Binary Feasibility `32551160941`: PASS.
- Production nonblank additions: 65/70; test raw additions: 220/220.

## Failed-identity cleanup

Reviewed commit `59123f2` was installed into the preserved `-04` venv without changing its Python or
manager argv identity. The recorded PID had already exited before cleanup. Normal stop/uninstall
removed process record, lease, task definition, install record and Scheduled Task. Desired-state and
credential-safe log evidence remain. No PID signal, force kill or manual record edit occurred.

`-04` remains failed acceptance evidence. A fresh `-05` logout/login is required to prove the repair,
but the current owner continuation explicitly prohibits another logout. Phase 4B therefore remains
open and Phase 5 is not authorized.
