# TaskCard: RTS-021 Atomic-File versus SQLite Storage Comparison

## Task ID

runtime-v2-rts-021-storage-comparison

## Goal

Compare the smallest credible atomic-file/journal design and Python stdlib SQLite behind one
removable Runtime v2 slice API. Both candidates must execute the same logical `run`, read-only
`status`, exact local `stop`, stable run/invocation identities, shared normal path, and Candidate
fault outcomes. The comparison must show which local recovery windows each representation removes,
which external windows neither can remove, and the operational cost each adds.

This TaskCard produces comparative evidence only. It does not choose a production Store, language,
physical Coordinator, product boundary, default Runtime, migration or release.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@0e6d65ff775943e7fd89f91faa5000dd2a62dc85`
- **Task branch**: `codex/runtime-v2-rts-021-storage-comparison`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 2 / RTS-021
- **Contract**: `docs/runtime-v2-semantic-contract.md`, status `Candidate`
- **Shared fault fixture**: `tests/fixtures/runtime_v2_shared_slice_cases.json`
- **Python baseline**: RTS-020 repair head `457a336315a6549f43d28333f42991c84e18422d`

RTS-020 passed and merged through PR #102. Its experiment, fixture, artifacts and closeout are
read-only comparison inputs under this card; they must not be rewritten to make either candidate
look smaller.

## Experiment boundary

The implementation must live under `experiments/runtime-v2-storage/` and remain disconnected from
the installed `awf` package. Tests may invoke it with Python and disposable paths. It may reuse the
existing scripted no-model provider and the language-neutral RTS-020 fixture as read-only inputs.

Real but disposable/local evidence:

- structured child-process argv with no shell and a credential-minimized environment;
- fresh temporary repositories/workspaces and local Git observations where the slice requires them;
- atomic replacement, exact lock identity and checksum validation for the atomic-file candidate;
- stdlib `sqlite3` transactions, locking, integrity checks, backup and schema migration for SQLite;
- real process restart across separate test subprocesses;
- corruption, contention, stale backup/cache and derived-view deletion checks.

Synthetic:

- implementer/reviewer intelligence and Artifact contents;
- delivery, downstream-intent, transport and ACK observations;
- provider identity, timestamps and event/delivery identifiers;
- PR, CI, GitHub, release and service-manager-shaped facts.

There is no Agent Bus, real provider credential, remote Git write, GitHub mutation, native manager,
production state, retained delivery or cross-host state adoption in this comparison. No local
transaction may claim atomicity with provider execution, Git, Agent Bus, GitHub, the OS manager or
another host.

## Frozen architecture budget

1. One backend-neutral `Store` protocol owns immutable run identity, Workflow phase,
   authorization, invocation journal state, exact local handoff intent and terminal facts.
2. Exactly two implementations exist: `atomic` and `sqlite`. Business/control-flow logic and
   normalized status projection are shared, not duplicated per backend.
3. The atomic candidate uses the smallest credible authoritative envelope/journal plus an exact
   cross-process writer lock. It must not grow a second checkpoint/outbox/inbox authority graph.
4. The SQLite candidate uses one per-run database and explicit transactions. WAL/rollback files,
   locks and backups are operational representations, not additional Workflow authorities.
5. A persistent summary/status file, if emitted, is derived only. Deleting it cannot lose
   authoritative recovery state; stale or forged derived data can deny/diagnose but cannot
   authorize a provider, handoff or terminal transition.
6. Stable run and invocation IDs, authorization, launch intent, process observation, durable
   result, Artifact validation, trusted local Git effect, handoff intent and terminal remain
   separately observable logical facts even when several local facts share one transaction.
7. `status` is byte-for-byte read-only for both backends. It cannot acquire a writer lock, repair,
   migrate, restore, resume, invoke a provider or execute its reported action.
8. `stop` is exact-slice-only. It may record a local stop only after the selected backend proves no
   invocation is active; this remains unequal native-lifecycle evidence.
9. Use the Python standard library, existing pytest dependency and local Git executable only. No
   new dependency, ORM, async framework, scheduler, service, facade, provider registry, generic
   Workflow engine or physical Coordinator.
10. The experiment is removable by deleting only its new experiment/test/artifact files and must
    not migrate or write RTS-020 or production state.

## Shared slice and outcome equivalence

Both backends expose the same experiment-local commands:

```text
run --store atomic|sqlite
status --store atomic|sqlite
stop --store atomic|sqlite
```

One normal `run` performs the same logical sequence for both stores:

```text
compile immutable RunSpec
  -> atomically persist prepared implement journal + exact authorization
  -> persist launch intent, observe one scripted child, persist result
  -> validate Artifact, create/revalidate one trusted disposable Git effect
  -> atomically persist exact review handoff + prepared review journal + authorization
  -> persist review launch/result/validation
  -> revalidate exact Git identity and persist terminal
```

Normal provider count is implement=1, review=1. Completed replay is idempotent. Every machine row
from `runtime_v2_shared_slice_cases.json` must execute against both candidates and return the same
normalized outcome and sole legal next action. The storage comparison may add backend-specific
faults but may not edit or restate the shared expected outcomes.

## Named local file-order windows

The report must reproduce these RTS-020 baseline windows before claiming a reduction:

| ID | RTS-020 local boundary | Required comparison |
|---|---|---|
| `W-AUTH` | prepared InvocationJournal write before RunStore authorization write | show whether one backend commit can persist both without hiding launch intent |
| `W-RESULT` | durable invocation result write before Workflow phase advancement | show whether one backend commit can persist both while provider exit remains external |
| `W-HANDOFF` | Workflow handoff intent before prepared review journal/authorization | show exact recovery state and whether one backend commit removes the local ordering window |
| `W-TERMINAL` | validated review journal before terminal Workflow write | show whether one backend commit removes only the local window after external Git revalidation |

For each candidate and window, the machine-readable result records `eliminated`, `retained_safe`, or
`not_applicable`, the exact transaction/write boundary, joined persistent records and recovery
action. A smaller file count is not proof that an external window disappeared.

## Storage-specific fault contract

`tests/fixtures/runtime_v2_storage_cases.json` must reject duplicate keys and contain stable cases
for at least:

1. concurrent writer/lock contention before mutation;
2. process restart after each named local commit boundary;
3. checksum/envelope corruption for atomic and database/integrity/schema corruption for SQLite;
4. current backup followed by exact offline restore;
5. stale backup/restore attempt after a newer authorization or terminal fact;
6. SQLite schema `v1 -> v2` migration, repeated migration and unsupported newer schema;
7. deletion of every derived view followed by correct recovery/status from authority;
8. forged or stale derived/cache state that claims authorization or terminal;
9. exact stop while idle and denial while an invocation or writer is active.

The cases must name expected outcome, exactly one legal next action, prohibited effects and whether
the fault applies to both candidates or SQLite only. Unknown, stale, corrupt, busy or conflicting
authority cannot be promoted to safe continuation. Backup/restore and migration are explicit
offline maintenance actions in this disposable experiment; `status` never performs them.

## SQLite minimum gate

The comparison result may report `SQLITE_MEETS_MINIMUM_GATE` only when all of these are true:

- SQLite removes at least two named RTS-020 local file-order windows;
- all shared normal/fault outcomes remain equivalent to atomic;
- Windows and non-Windows CI prove bounded lock contention, restart, corruption detection,
  backup/restore and schema migration;
- deleting derived state loses no authoritative recovery fact;
- stale cache, backup or schema state never authorizes provider, handoff or terminal;
- the report keeps provider, Bus, Git, GitHub, OS and cross-host boundaries external.

Otherwise the deterministic result is `RETAIN_ATOMIC_FILE_BASELINE`. Even
`SQLITE_MEETS_MINIMUM_GATE` is eligibility evidence for the later architecture ADR, not a
production Store selection. The report must also state whether atomic removes the same windows and
whether SQLite's locking, backup, migration and distribution cost buys any unique ownership
reduction.

## Measurement contract

For each candidate record:

- authority/intent/evidence/derived/cache families and per-run/per-invocation multiplicity;
- files/database objects joined for every shared and storage-specific recovery decision;
- transaction boundaries and external observations not covered by them;
- normal commands, fault-only maintenance commands and human decision points;
- production and test nonblank/noncomment LOC attributable to the candidate;
- direct dependencies, runtime files, backup artifacts and Windows/macOS/Linux prerequisites;
- lock/restart/corruption/backup/migration timings only as descriptive evidence, never a semantic
  pass criterion;
- named windows removed or retained and the owner/legal action for every ambiguous state.

The final comparison must separate language complexity, Store complexity, compatibility,
packaging, native lifecycle and external truth. It must not count SQLite's internal tables as fewer
authorities merely because they share one file, or count atomic files as extra logical owners merely
because they are visible.

## Frozen model-writable scope

- `experiments/runtime-v2-storage/README.md`
- `experiments/runtime-v2-storage/runner.py`
- `experiments/runtime-v2-storage/storage.py`
- `tests/fixtures/runtime_v2_storage_cases.json`
- `tests/test_runtime_v2_rts021_storage_comparison.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-021-storage-comparison.md`
- `.awf/artifacts/review-report-runtime-v2-rts-021-storage-comparison.md`

The committed TaskCard is frozen owner intent and is not model-writable. After implementation and
compiled ReviewReport pass, owner closeout may add
`docs/tasks/runtime-v2-rts-021-storage-comparison-implementation-report.md` and update only gate
status in the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Modification of RTS-020 experiment/fixture/artifacts or production `src/`, `scripts/`, schemas,
  CLI, facade, package entry points, CI workflows or current Runtime state formats.
- SQLite adoption/selection, production database/schema/migration, dual-write, state import,
  fallback, rollback or current-state conversion.
- Rust/Go/native slice, physical Coordinator, product-boundary ADR, contract Frozen promotion,
  installed `awf` UX, native lifecycle or distribution implementation.
- Live/retained repository, event, delivery, queue, listener, service, state root, payload,
  credential, ACK, provider, GitHub or remote Git operation.
- Manual ACK/requeue/recovery/redispatch, replacement delivery, historical payload read, release,
  default switch or destructive cleanup.

## Acceptance criteria

- [ ] Task ID equals the branch leaf; all state, databases, locks, backups and repositories are
      pytest-owned and fresh.
- [ ] One backend-neutral control flow exposes logical `run/status/stop` for exactly `atomic` and
      `sqlite`; no duplicated per-backend Workflow implementation exists.
- [ ] Both backends complete the normal path with provider count 1+1 and idempotent completed replay.
- [ ] Both backends execute all 14 shared machine rows with the same outcome, sole legal next action
      and prohibited-effect assertions.
- [ ] The four named RTS-020 file-order windows have per-backend machine-readable measurements and
      do not claim atomicity across external systems.
- [ ] Concurrent writer, restart, corruption, backup/restore, stale restore/cache, derived deletion,
      SQLite migration and exact-stop cases pass with fail-closed outcomes.
- [ ] Windows CI exercises real SQLite lock/restart/backup/migration behavior; Ubuntu and macOS
      gates preserve the same normalized semantics.
- [ ] `status` is byte-for-byte read-only and cannot migrate, restore, repair, lock or invoke.
- [ ] The result is deterministically either `SQLITE_MEETS_MINIMUM_GATE` or
      `RETAIN_ATOMIC_FILE_BASELINE`, with no production Store selection claim.
- [ ] Machine-readable output and ImplementationReport contain the complete RTS-020 comparison,
      representation multiplicity, dependency/LOC measurements and synthetic/unequal boundaries.
- [ ] No new dependency or production/default/remote/live/retained/migration/release/destructive
      surface is added or used.
- [ ] Focused test, full pytest/Ruff, ordinary cross-platform CI and Binary Feasibility pass on the
      exact publication head.
- [ ] Independent TaskCard, implementation and final exact-head Reviewers return `PASS`.

## Verification

- Run both backends' normal paths, all 14 shared fault rows and all storage-specific cases in one
  focused pytest module.
- Spawn fresh Python subprocesses for restart and writer-contention assertions; do not substitute
  same-process object recreation for restart evidence.
- Validate both JSON fixtures with duplicate-key rejection and resolve all normalized outcomes
  against `docs/runtime-v2-semantic-contract.md`.
- Run full repository pytest/Ruff and cross-platform CI; Mac does not run local pytest/Ruff.
- Run changed-file compile checks, `git diff --check`, Artifact contract compilation, changed-path
  audit and independent Review at the frozen TaskCard, implementation and exact publication heads.

## Required output

- one removable backend-neutral storage comparison runner;
- exactly one atomic and one SQLite Store implementation;
- one machine-readable storage fault/window fixture;
- one focused cross-platform acceptance suite;
- compiled ImplementationReport and ReviewReport artifacts;
- a later owner-authored comparison closeout.

<!-- awf-postflight
{
  "allowed_paths": [
    "experiments/runtime-v2-storage/README.md",
    "experiments/runtime-v2-storage/runner.py",
    "experiments/runtime-v2-storage/storage.py",
    "tests/fixtures/runtime_v2_storage_cases.json",
    "tests/test_runtime_v2_rts021_storage_comparison.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-021-storage-comparison.md",
    ".awf/artifacts/review-report-runtime-v2-rts-021-storage-comparison.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_v2_rts021_storage_comparison.py"],
    ["{python}", "-m", "pytest", "-q"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
