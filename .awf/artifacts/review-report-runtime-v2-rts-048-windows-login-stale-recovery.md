# RTS-048 Independent Windows Login Recovery ReviewReport

## Verdict

`PASS` after focused L3 repair and re-review.

## Closed finding

Initial review found that creation-aware cleanup reused a legacy lease matcher that permits both
lease state-root fields absent. That could delete incomplete evidence. Windows strict cleanup now
requires explicit current lease state-root path and binding before any unlink. Legacy compatibility
remains unchanged elsewhere.

## Gate assessment

1. Only `TransientBusReadinessError` from Agent Bus health probing is retried. Four total attempts and
   three 15-second delays are fixed; desired `stopped` cancels immediately; other NodeError classes
   execute once.
2. Retry remains before process record, lease, listener or provider effect because local readiness
   precedes foreground identity creation.
3. Creation-aware cleanup requires strict profile/digest/repository/state-root record identity,
   exact launch/lease identity, explicit strict lease root/binding and recorded/live FILETIME
   mismatch.
4. A reused PID is never taskkilled. After exact stale cleanup, only the deterministic Task Scheduler
   target may receive `/End`; normal reconcile/stop/uninstall may converge.
5. Missing creation, missing lease root/binding, incomplete/drifted evidence or a distinct live lease
   PID remains preserved with zero native calls.
6. Existing matching-creation taskkill, POSIX lifecycle, installed target and facade behavior remain
   green. No record/API/dependency/Bus/login-policy change was introduced.

## Verification

- Focused lifecycle suite: **83 passed, 1 skipped**.
- Full repository suite: **884 passed, 5 skipped**.
- Compileall, Ruff, Ruff format and `git diff --check`: PASS.
- Production nonblank/noncomment additions: 65/70.
- Focused test raw additions: 220/220.
- Reviewer environment lacked pytest; test counts remain author evidence pending exact-head CI.

## Continuation

The preserved `-04` failure cannot become PASS. Exact-head CI must pass before reviewed code cleans
its stale evidence/task. RTS-046 then requires fresh `-05`; Phase 5 remains prohibited.

<!-- awf-review-report
{
  "verdict": "PASS",
  "critical": 0,
  "high": 0,
  "medium": 0,
  "low": 0,
  "closed_high": 1,
  "focused_tests": "83 passed, 1 skipped",
  "full_tests": "884 passed, 5 skipped",
  "next_gate": "exact-head CI then fresh RTS-046 -05"
}
-->
