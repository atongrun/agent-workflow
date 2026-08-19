# RTS-020 Python Shared Disposable Slice Closeout

Status: **PASS**

Date: 2026-08-20

TaskCard: [`runtime-v2-rts-020-python-shared-slice.md`](runtime-v2-rts-020-python-shared-slice.md)

Executable slice head: `77c7023b98a7c294a95d501f0a0662eb4d9809e1`

Pull request: [#102](https://github.com/atongrun/agent-workflow/pull/102)

## Result

The removable repository-local Python slice passed its shared normal path and all eight named fault
families. One logical `run` command compiled immutable intent, authorized and invoked exactly one
scripted implement child, validated and imported its allowed Artifact into a disposable no-remote
Git repository, invoked exactly one scripted `PASS` reviewer, revalidated the trusted Git identity,
and persisted terminal completion. Identical completed replay added no provider, Git, handoff or
terminal effect. `status` was byte-for-byte read-only and named one legal next action; `stop` wrote
only after proving the exact local slice had no active invocation.

The shared fixture contains eight top-level cases and 14 machine rows. It preserves separate facts
for prepared journal, authorization, launch intent, process observation, durable result, Artifact
validation, trusted local Git effect, handoff intent and terminal. An authorized invocation with a
missing or corrupt bound journal is owner-required and cannot start. Durable launch intent without
an exact recoverable result remains ambiguous and cannot replay.

## Ownership and measurement result

The slice represents immutable run intent, Workflow transition/authorization/terminal,
per-invocation recovery, provider-process observation, trusted local Git effects and read-only
status. It excludes Agent Bus transport/ACK, real provider selection, GitHub/PR/CI provenance,
cross-host adoption, native service lifecycle, retained delivery, release/default wiring and
migration.

Its local representation is deliberately small:

- one per-run `runspec.json` authority record;
- one per-run `run.json` Workflow authority/intent record;
- one journal record per invocation through one `InvocationJournal` API;
- one provider-count evidence file;
- disposable Git repositories as external observations.

There is no experimental checkpoint/outbox/inbox authority split. The eight recovery decisions
join the immutable RunSpec, RunStore, relevant journal, provider-count evidence and exact Git
HEAD/tree/worktree facts. The normal operator surface is one `run`, optional read-only `status`, and
optional exact-slice `stop`; faults expose diagnosis/preserve-evidence actions rather than hidden
automatic repair.

Measured implementation size is 1,380 nonblank/noncomment lines in the experiment runner plus 74
in the scripted provider fixture. The shared JSON fixture is 300 lines and the focused acceptance
module is 636 nonblank/noncomment lines. The experiment adds no runtime dependency: it uses the
Python standard library, the existing pytest test dependency and the local Git executable.

This proves that a smaller Python ownership model is credible enough to remain a first-class
candidate. It does not establish installed `awf` UX, native lifecycle, distribution, cross-host,
real provider, transport/ACK, remote provenance, rework or business parity. It does not select
Python, atomic files, SQLite, a physical Coordinator or a production migration.

## Review and repair evidence

The frozen TaskCard passed independent review before implementation. The same independent
implementation Reviewer performed three bounded rounds:

- `aa315f5` returned four HIGH and one MEDIUM finding covering prohibited-effect assertions,
  checksum-valid identity drift, review recovery state, corrupt-journal stop and report claims;
- `5de5790` closed those findings, then returned one HIGH later-phase evidence-join finding and one
  MEDIUM prohibited-effect coverage finding;
- `b4adae5673e01687c1827bc0f2cd942968e516ae` closed both and returned `PASS` with zero findings.

The fixes added exact phase/binding joins for implement result/commit, review result and terminal;
exact authorization-set validation; concrete one-for-one prohibited-effect assertions; fail-closed
duplicate-key and identity handling; and a credential-minimized child environment. No production
`src/`, `scripts/`, CLI, schema, state format or CI workflow changed.

## CI and publication evidence

The first publication attempt at `b540e28` failed only two Linux Ruff `I001` import-block checks.
Commit `77c7023` removed the two extra separator lines without changing behavior. On that exact
executable head:

- ordinary CI run
  [`32308287706`](https://github.com/atongrun/agent-workflow/actions/runs/32308287706)
  passed all six jobs;
- Ubuntu collected 669 tests: `664 passed, 5 skipped`; Ruff check passed and all 192 files were
  formatted;
- Windows collected 669 tests: `658 passed, 11 skipped`; PowerShell and Git Bash executor suites
  each passed 23/23; Ruff check and format passed;
- installed-wheel Ubuntu, Windows and macOS jobs passed; macOS runtime passed;
- Binary Feasibility run
  [`32308287696`](https://github.com/atongrun/agent-workflow/actions/runs/32308287696)
  passed Linux x86_64/arm64, macOS x86_64/arm64, Windows x86_64 and aggregate.

The PR still requires ordinary CI, Binary Feasibility and a new independent exact-head Review on
its final publication commit before merge. Those integration gates do not change the measured
RTS-020 execution result.

## Next gate

RTS-021 is the first entry-satisfied successor. It compares the smallest credible atomic-file/
journal design with SQLite behind the same shared slice API. RTS-021 is still a removable
experiment: it may not infer a Store choice, language choice, physical Coordinator, production
default, migration or release action from this PASS.
