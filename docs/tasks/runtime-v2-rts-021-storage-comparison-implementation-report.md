# RTS-021 Storage Comparison Closeout

Status: **PASS**

Date: 2026-08-20

TaskCard: [`runtime-v2-rts-021-storage-comparison.md`](runtime-v2-rts-021-storage-comparison.md)

Executable slice head: `e2f39602c4ede3c550707b9a848ef5d4cbb721db`

Pull request: [#103](https://github.com/atongrun/agent-workflow/pull/103)

## Result

One removable backend-neutral Runtime v2 slice ran the same `run`, read-only `status`, exact local
`stop`, normal provider path and all 14 Candidate fault rows against exactly two Store candidates:
one checksummed atomic authority envelope and one per-run stdlib SQLite database. Both candidates
preserved the same normalized outcome, sole legal next action, one implement plus one review child,
trusted disposable Git effect and idempotent terminal replay.

The storage fixture adds four named local windows and 11 storage cases. Both candidates join
`W-AUTH`, `W-RESULT`, `W-HANDOFF` and `W-TERMINAL` inside one local writer boundary. Contention,
fresh-process restart, corruption, current/stale/foreign backup, offline restore, derived deletion
or forgery, SQLite `v1 -> v2` migration and exact stop all passed. Status uses only authority reads,
opens SQLite with `mode=ro`, remains byte-for-byte read-only and never migrates, restores, repairs,
locks or invokes.

The strict observed-fact evaluator reports `SQLITE_MEETS_MINIMUM_GATE`: all 14 required booleans
must be present, true and machine-produced by the focused suite. Missing, extra,
non-boolean or false evidence deterministically returns `RETAIN_ATOMIC_FILE_BASELINE`. This result
only makes SQLite eligible for the later owner ADR. It does not select SQLite for production.

## Ownership and measurement result

Atomic and SQLite remove the same four local file-order windows in this experiment. SQLite therefore
buys no unique Workflow ownership reduction. It adds schema migration, database lock behavior,
backup-file handling and platform SQLite compatibility. The atomic candidate remains a credible
simpler baseline; the Store choice is intentionally deferred to RTS-024.

The experiment keeps immutable RunSpec, Workflow authority, per-invocation recovery, provider
observation, trusted local Git effects and derived status separate by meaning. It claims no
transaction across provider execution, Git, Agent Bus/ACK, GitHub, OS lifecycle or hosts. Backup,
restore and migration are explicit offline fault-only commands, never normal-path repair.

Current measured size is 954 nonblank/noncomment lines in `runner.py`, 670 in `storage.py`, 685 in
the focused acceptance module and 171 JSON fixture lines. It adds no package dependency: both
backends use the Python standard library, existing pytest dependency and local Git executable.

The remaining native-language question is distribution rather than demonstrated Workflow
ownership. RTS-020 proved a smaller Python ownership model credible, while existing binary
readiness evidence still leaves relocatable distribution unresolved. That satisfies RTS-022's
conditional “may materially improve ownership or distribution” entry criterion without selecting
Rust or authorizing production distribution.

## Review and repair evidence

The frozen TaskCard passed independent review before implementation. The same independent
implementation Reviewer performed three bounded rounds:

- `70f222f` returned one HIGH foreign-backup identity hole and two MEDIUM evidence/artifact findings;
- `ac8dcc8` confirmed exact restore identity but returned one HIGH because exact-stop and
  active-writer restore were absent from the eligibility facts;
- `eaa055f78f8200baeac40b60abb90add6c42860b` confirmed both repairs and returned `PASS` with zero
  remaining findings.

The repair compares backup and current RunSpec digest, run ID, task ID and bound run-spec digest
before replacement. Equal/newer foreign backups and stale backups preserve the victim authority.
The final gate evidence becomes true only after its corresponding disposable helper passes.

## CI and publication evidence

Initial ordinary CI run `32314268437` failed only Ruff import/format checks before tests. Commit
`e2f3960` applied the exact mechanical layouts reported by Ubuntu and Windows; no behavior or
TaskCard boundary changed.

On exact pre-closeout publication head `00baa3566e2207abbe5ae7adc3bb1ff02d7d26e9`:

- ordinary CI run
  [`32314492329`](https://github.com/atongrun/agent-workflow/actions/runs/32314492329)
  passed all six jobs;
- Ubuntu collected 682 tests: 677 passed and 5 skipped; all 12 RTS-021 focused tests passed;
- Windows collected 682 tests: 671 passed and 11 skipped; all 12 RTS-021 focused tests passed;
- Ruff check/format passed on Ubuntu and Windows with 198 files formatted;
- installed-wheel Ubuntu, Windows and macOS jobs passed, and macOS runtime passed;
- Binary Feasibility run
  [`32314492349`](https://github.com/atongrun/agent-workflow/actions/runs/32314492349)
  passed Linux x86_64/arm64, macOS x86_64/arm64, Windows x86_64 and aggregate.

The final closeout head still requires a fresh ordinary CI run, Binary Feasibility run and one
independent exact-head Reviewer before merge.

## Next gate

RTS-022 is the next entry-satisfied TaskCard gate. It may run one bounded Rust shared slice because
native distribution value remains an evidence-backed open hypothesis. Its frozen stop budgets
remain authoritative: no async Runtime, ORM, embedded Git, generic registry or production adoption;
at most two focused implementation TaskCards before RTS-024. RTS-023 remains conditional on a
Rust-specific stop with native value still present. No language, Store, physical Coordinator,
product boundary, production default, migration or release decision has been made.
