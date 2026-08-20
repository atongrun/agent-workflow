# RTS-022B Maintainer Fault Gate Implementation Report

## Scope

- Task: `runtime-v2-rts-022-maintainer-fault-gate`
- Branch: `codex/runtime-v2-rts-022-maintainer-fault-gate`
- Seed HEAD observed locally: `1731a4b95079c6b6c3532fbb88b0764cdcdaf05b`
- Draft PR: `#105`
- Source change path: `experiments/runtime-v2-rust/src/lib.rs`
- Report path: `.awf/artifacts/impl-report-runtime-v2-rts-022-maintainer-fault-gate.md`

No test, fixture, Cargo, workflow, production, queue, provider, release, migration, retained-state,
remote-Git, or destructive path was changed.

## Independence Boundary

I did not inspect seed-parent history or patch surfaces before making this repair. Specifically, I
did not use `git show` of the seed or parent, seed-parent diffs, patch-producing `git log`, blame,
reflog, bisect, GitHub commit patch views, or owner/agent hints about the injected mutation.

Permitted evidence used:

- Current seeded source tree and tests.
- `docs/tasks/runtime-v2-rts-022-maintainer-fault-gate.md`.
- `docs/runtime-v2-semantic-contract.md`.
- `docs/tasks/runtime-v2-rts-022-rust-shared-slice-implementation-report.md`.
- `tests/fixtures/runtime_v2_shared_slice_cases.json`.
- Exact seeded Binary Feasibility run/job logs from GitHub Actions.

`AGENTS.md` was requested by the TaskCard handoff, but no `AGENTS.md` file exists in this worktree
or its immediate parent search path. The AGENTS instructions supplied in the task prompt were
followed.

## Seeded CI Evidence

Seeded Binary Feasibility run: `32324044913`.

The complete Rust shared semantic suite failed on the same fixture row across all five pinned jobs:

| Target job | Job ID | Observed failure |
|---|---:|---|
| `rust-shared-linux-x86_64` | `96291587574` | `S-AUTH-START-LAUNCH-NO-RESULT outcome drift: SAFE_CONTINUE` |
| `rust-shared-linux-arm64` | `96291587564` | `S-AUTH-START-LAUNCH-NO-RESULT outcome drift: SAFE_CONTINUE` |
| `rust-shared-macos-arm64` | `96291587468` | `S-AUTH-START-LAUNCH-NO-RESULT outcome drift: SAFE_CONTINUE` |
| `rust-shared-macos-x86_64` | `96291587567` | `S-AUTH-START-LAUNCH-NO-RESULT outcome drift: SAFE_CONTINUE` |
| `rust-shared-windows-x86_64` | `96291587592` | `S-AUTH-START-LAUNCH-NO-RESULT outcome drift: SAFE_CONTINUE` |

In the sampled logs, rustfmt, Clippy, and release build completed before the failing test step. The
failing test was `shared_slice_fixture_and_normal_path_pass` at `tests/shared_slice.rs:62`, where
the verifier rejected the current evidence with:

`DENY_BEFORE_PROVIDER: preserve files and diagnose exact run identity (S-AUTH-START-LAUNCH-NO-RESULT outcome drift: SAFE_CONTINUE)`

## Violated Candidate Invariant

Candidate semantic contract section 4 says persisted launch intent with no trusted recoverable
result is ambiguous and MUST NOT auto-invoke. Section 5.1 binds `model_started` / launch intent as a
durable launch/workspace identity and allows recovery only from separately proved same-event,
same-role, zero-exit result evidence; otherwise it must fail ambiguous and never invoke again.

The shared fixture encodes this as row `S-AUTH-START-LAUNCH-NO-RESULT`:

- inject: `auth_launch_no_result`
- expected outcome: `AMBIGUOUS_NO_REPLAY`
- legal next action: `preserve exact process/workspace/evidence for owner decision`
- prohibited effects: automatic provider replay, fall back to prepared recovery, fresh replacement
  delivery
- assertions include `no_provider`, `no_terminal`, `no_trusted_repo`, `auth_implement_once`,
  `journal_state_launch_intent`, and `state_stable_on_rerun`

## Root Cause

`inject_case(..., "auth_launch_no_result")` creates a prepared implement journal with launch intent,
adds the implement authorization, and stores the run phase as `implement_launch_intent`. That is the
outer phase used when launch intent is durable before process-start/result observation.

`status_slice_inner` handled journal state `launch_intent` inside the `implement_authorized` phase
as `AMBIGUOUS_NO_REPLAY`, but handled the equivalent outer run phase `implement_launch_intent` as
`SAFE_CONTINUE`. The projection therefore reported a legal continuation for evidence that the
Candidate requires to be ambiguous/no-replay.

This was a status projection fault, not a fixture or provider-count fault. The state already records
the launch-intent journal and the verifier observed the correct injected row; only the reported
outcome was wrong.

## Repair

Changed only the `status_slice_inner` match arm for phase `implement_launch_intent`:

- before: outcome `SAFE_CONTINUE`
- after: outcome `AMBIGUOUS_NO_REPLAY`
- unchanged legal next action: `preserve exact process/workspace/evidence for owner decision`
- unchanged phase/source/counts/terminal/trusted-repo projection fields

This aligns the outer phase projection with both:

- the `run_slice` fail-closed branch for `implement_launch_intent | implement_started`; and
- the journal-state projection branch for `launch_intent | started` under `implement_authorized`.

The repair does not authorize a provider, Git mutation, handoff, terminal transition, replacement
delivery, or state rewrite. It only corrects the read-only status outcome for already-durable launch
intent without result.

## Local Static Checks

Mac hard-boundary respected: no Cargo, rustc, Rust binary, pytest, Ruff, provider, queue, retained
state, or remote write command was run locally.

Allowed checks performed:

- Current branch and HEAD checked with `git status --short --branch` and `git rev-parse HEAD`.
- Current source/tests/fixture/contract inspected with `sed` and `rg`.
- Exact CI logs inspected read-only with `gh api repos/atongrun/agent-workflow/actions/jobs/<job>/logs`.
- Allowed-path audit:
  - tracked diff: `experiments/runtime-v2-rust/src/lib.rs`
  - ignored artifact created intentionally under allowed report path:
    `.awf/artifacts/impl-report-runtime-v2-rts-022-maintainer-fault-gate.md`
- `git diff --check` passed with no whitespace errors.
- `tests/fixtures/runtime_v2_shared_slice_cases.json` parsed successfully as JSON.
- `experiments/runtime-v2-rust/Cargo.toml` was inspected and still has an empty `[dependencies]`
  table.
- Modified source and report were checked for trailing whitespace. The only debug-text scan hits in
  `lib.rs` were pre-existing CLI `println!` output paths, not new debug leftovers.

## Not Run Locally

Per TaskCard Mac boundary, I did not run:

- `cargo fmt`
- `cargo clippy`
- `cargo test`
- `cargo build`
- Rust executable commands
- `pytest`
- `ruff`

Candidate ordinary CI `32324509595` and Binary Feasibility `32324509603` passed on exact head
`194e6398d993735ba2927f8e8547dc9bc60643e6`. The same independent Gate Reviewer initially stopped
on missing repository-visible pre-seed Review evidence, then verified the existing timestamped Codex
rollout transcript and its extraction digest. That evidence proves exact TaskCard head `c3d373f` was
independently reviewed PASS 47 seconds before seed `1731a4b`. The deterministic result is
`RUST_MAINTAINER_GATE_PASS`; final closeout-head CI and exact-head evidence review remain.

<!-- awf-implementation-report
{
  "summary": "Independently diagnose the five-target seeded Candidate failure and restore the ambiguous no-replay status projection for durable implement launch intent in one semantic repair.",
  "changed_files": [
    "experiments/runtime-v2-rust/src/lib.rs",
    ".awf/artifacts/impl-report-runtime-v2-rts-022-maintainer-fault-gate.md"
  ],
  "commands": [
    "gh api read-only exact seeded job logs",
    "static current-source, test, fixture, contract, dependency, and allowed-path inspection",
    "git diff --check"
  ],
  "tests": [
    "Seeded five-target rustfmt, Clippy, and release build PASS",
    "Seeded five-target existing shared semantic suite failed exact S-AUTH-START-LAUNCH-NO-RESULT outcome drift",
    "Candidate source exactly matches the RTS-022A passed origin/main source",
    "Candidate local static scope and whitespace checks PASS",
    "Candidate ordinary CI 32324509595 PASS",
    "Candidate Binary Feasibility 32324509603 PASS",
    "Independent Gate Review PASS after pre-seed transcript evidence verification"
  ],
  "source_revision": "3ba1db590587071cd69708c5806207311451468e"
}
-->
