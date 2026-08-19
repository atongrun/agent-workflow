# Implementation Report: RTS-021 Storage Comparison

## Summary

Added a removable Runtime v2 storage comparison experiment under
`experiments/runtime-v2-storage/`. The slice exposes the same local `run`, `status`, and `stop`
commands for exactly two backends, `atomic` and `sqlite`, and keeps Workflow control flow in
`runner.py` rather than duplicating it per backend.

The atomic backend persists one checksummed authority envelope behind an exact writer lock. The
SQLite backend persists the same authority payload in one per-run stdlib `sqlite3` database using
explicit writer transactions, `mode=ro` status reads, integrity checks, backup, and offline schema
migration. Derived status files are non-authoritative and are ignored for authorization, handoff,
stop, and terminal decisions.

## Boundary statement

Real disposable/local evidence:

- structured child-process argv with no shell and credential-minimized environment;
- fresh local source/trusted Git repositories with no remotes and exact HEAD/tree revalidation;
- atomic envelope replacement plus exact lock identity for the atomic backend;
- stdlib SQLite transaction, read-only status connection, backup, restore, integrity check, writer
  contention, and `v1 -> v2` migration evidence;
- process restart via separate test subprocess calls after named local boundaries;
- corruption, stale backup, derived deletion/forgery, and exact-stop denial checks.

Synthetic or excluded evidence:

- implementer/reviewer intelligence, provider identity, timestamps, event/delivery identifiers;
- Agent Bus, retained delivery, ACK, GitHub, remote Git, release/default state, native lifecycle,
  cross-host adoption, and production Store migration.

No local transaction claims atomicity with provider execution, Git, Bus, GitHub, an OS manager, or
another host.

## Comparison result

Deterministic preliminary result: `SQLITE_MEETS_MINIMUM_GATE`.

The focused tests derive this result from machine fixture facts rather than trusting the prefilled
fixture string. SQLite removes at least two named RTS-020 local file-order windows, both backends
preserve the 14 shared Candidate outcomes/actions, and storage-specific tests cover lock
contention, restart, corruption, backup/restore, stale restore denial, migration, derived state,
and exact stop. This is eligibility evidence for a later ADR only; it is not a production Store
selection.

Atomic removes the same four local file-order windows in this experiment by joining logical facts
inside one locked authority envelope. SQLite buys no unique Workflow ownership reduction here; its
extra cost is schema migration, database locking behavior, backup artifact handling, and platform
SQLite compatibility.

## Measurements

- Experiment production nonblank/noncomment LOC: `runner.py` 915, `storage.py` 594.
- Focused test nonblank/noncomment LOC: 478.
- Storage fixture size: 156 lines.
- Shared fixture rows executed per backend: 14.
- Storage-specific fixture cases: 9.
- Runtime dependencies: Python standard library, stdlib `sqlite3`, local `git` executable.
- Test dependencies: existing repository pytest dependency for CI; local direct smoke did not use
  pytest.

## Verification at implementation time

- `python3 -m py_compile experiments/runtime-v2-storage/runner.py
  experiments/runtime-v2-storage/storage.py
  tests/test_runtime_v2_rts021_storage_comparison.py`: PASS
- duplicate-key JSON parse for `tests/fixtures/runtime_v2_storage_cases.json`: PASS, 4 named
  windows and 9 storage cases
- direct normal run/status/stop smoke for `atomic` and `sqlite`: PASS, provider count 1+1 and
  idempotent completed replay
- direct shared fixture smoke: PASS, 14 rows per backend match expected outcome and sole legal
  next action
- direct focused test helper smoke: PASS, all focused test functions called with temporary state
  roots
- manual line-length scan for changed Python files: PASS, zero lines over 100 columns
- local pytest/Ruff: intentionally not run on Mac per task boundary

## Review status

Independent implementation review is pending. The companion ReviewReport is intentionally marked
`BLOCKED` with `PENDING_INDEPENDENT_REVIEW` rather than claiming PASS.

<!-- awf-implementation-report
{
  "summary": "Add a removable Runtime v2 storage comparison with one backend-neutral runner, one atomic Store, one SQLite Store, shared Candidate fault equivalence, and storage-specific recovery evidence.",
  "changed_files": [
    "experiments/runtime-v2-storage/README.md",
    "experiments/runtime-v2-storage/runner.py",
    "experiments/runtime-v2-storage/storage.py",
    "tests/fixtures/runtime_v2_storage_cases.json",
    "tests/test_runtime_v2_rts021_storage_comparison.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-021-storage-comparison.md",
    ".awf/artifacts/review-report-runtime-v2-rts-021-storage-comparison.md"
  ],
  "commands": [
    "python3 -m py_compile experiments/runtime-v2-storage/runner.py experiments/runtime-v2-storage/storage.py tests/test_runtime_v2_rts021_storage_comparison.py",
    "duplicate-key JSON fixture validation with object_pairs_hook",
    "direct normal run/status/stop smoke for atomic and sqlite",
    "direct shared fixture smoke for 14 rows per backend",
    "direct focused test helper smoke for all RTS-021 test functions",
    "manual Python line-length scan"
  ],
  "tests": [
    "Static compile PASS",
    "Storage fixture duplicate-key validation PASS",
    "Normal backend equivalence PASS",
    "Shared Candidate fixture equivalence PASS",
    "Storage-specific direct helper smoke PASS"
  ],
  "source_revision": "CONTAINING_COMMIT",
  "review_status": "PENDING_INDEPENDENT_REVIEW",
  "comparison_result": "SQLITE_MEETS_MINIMUM_GATE",
  "synthetic_boundaries": [
    "provider intelligence",
    "delivery observation",
    "downstream intent",
    "transport ACK",
    "GitHub/PR/CI/release facts"
  ],
  "unequal_evidence": [
    "installed awf UX",
    "native lifecycle/service manager",
    "distribution",
    "cross-host state",
    "real provider/transport/ACK/business parity"
  ]
}
-->
