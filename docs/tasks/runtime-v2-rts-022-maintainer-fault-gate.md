# TaskCard: RTS-022B Independent Maintainer Fault Gate

## Task ID

runtime-v2-rts-022-maintainer-fault-gate

## Goal

Prove whether a fresh maintainer can diagnose and repair one owner-injected L3 fault in the
disposable Rust Runtime v2 shared slice from the frozen semantic contract, current source, existing
tests, and credential-free CI evidence. The maintainer receives no description of the mutation and
must not inspect the seed commit's parent diff or patch history.

This is the second and final RTS-022 implementation TaskCard. It is a maintainability stop gate,
not another feature card, a Rust selection, a production rewrite, or authorization to change the
Runtime default. A PASS advances only to RTS-024. A stop result ends Rust evaluation and makes
RTS-023 entry-eligible only if the owner later confirms that measured native value still warrants
the conditional Go fallback.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@1a499ede2c9342a4b6e5626db829801f83fc5ff3`
- **Task branch**: `codex/runtime-v2-rts-022-maintainer-fault-gate`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 2 / RTS-022
- **Contract**: `docs/runtime-v2-semantic-contract.md`, status `Candidate`
- **Shared fixture**: `tests/fixtures/runtime_v2_shared_slice_cases.json`
- **Rust slice**: `experiments/runtime-v2-rust/`
- **RTS-022A evidence**:
  `docs/tasks/runtime-v2-rts-022-rust-shared-slice-implementation-report.md`

RTS-022A returned `RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE`: all 14 shared rows passed on
five native targets with zero Cargo dependencies and no Python runtime child. Its 3,471-line Rust
numerator exceeded the frozen size threshold, so the development plan requires this independent
maintainer gate before any implementation-choice decision.

## Independent roles

The owner/lead, maintainer, and TaskCard Gate Reviewer are separate roles:

1. The owner freezes this TaskCard and obtains an independent TaskCard Review PASS.
2. The owner injects exactly one bounded fault and publishes the exact failing CI run/job identity.
3. A fresh maintainer with no RTS-022A implementation or review context diagnoses and repairs it.
4. A different independent Gate Reviewer reviews the candidate after focused and full CI evidence.

The maintainer must not receive the mutation description, seed patch, owner diagnosis, likely line,
or suggested fix before submitting the semantic repair. The Gate Reviewer may inspect the full
seed-to-candidate history after the maintainer has finished.

## Frozen owner seed protocol

After this TaskCard is frozen and reviewed, the owner creates one seed commit that:

- changes only `experiments/runtime-v2-rust/src/lib.rs`;
- introduces exactly one L3 authority, recovery, idempotency, exact-stop, or provenance fault;
- changes existing behavior rather than adding a new feature or abstraction;
- is caught by at least one existing Rust shared-slice test or deterministic verification command;
- reaches the test/verification stage without requiring a new dependency, fixture, test, workflow,
  platform API, `unsafe`, or production code;
- leaves all test-owned repositories and state roots disposable and no-remote;
- contains no credential, live/retained state, business payload, remote write, or destructive action.

The owner may choose one fault family only from:

- authorization / launch / durable-result recovery outcome or legal-next-action;
- completed or ambiguous invocation no-replay / duplicate idempotency;
- active writer or active invocation exact-stop denial;
- immutable run, invocation, Artifact, or trusted Git identity/provenance validation.

The seed commit subject and CI handoff identify only this TaskCard and that an injected fault exists.
They do not disclose the family, line, mutation, or fix. If the seed does not compile or no existing
test/verification command fails, the owner discards that seed before maintainer handoff; this is a
seed setup failure, not a maintainer repair attempt.

## Maintainer evidence boundary

The maintainer may use:

- the current seeded source tree and normal file/symbol search;
- this TaskCard, the Candidate semantic contract, RTS-022A closeout, experiment README, shared
  fixture, current Rust tests, and current workflow definitions;
- the exact owner-provided GitHub CI run/job logs for the seeded HEAD;
- focused static inspection and the frozen verification commands;
- ordinary `git status`, current `git rev-parse HEAD`, and uncommitted candidate diff inspection.

Until the semantic repair is submitted, the maintainer must not use any history surface that reveals
the injected patch, including parent comparisons, `git show` of the seed or parent, patch-producing
`git log`, `git diff <seed-parent>..<seed>`, blame/reflog/bisect, GitHub commit patch views, or another
agent/owner hint. This is an experiment constraint, not a production secrecy mechanism.

The maintainer may inspect and explain the candidate diff they create. After the repair is submitted,
the owner and Gate Reviewer may compare the seed and candidate to verify exact restoration and that
the diagnosis was independently derived.

## Bounded diagnosis and repair budget

One bounded pass means:

1. one owner seed and one exact seeded-head CI failure handoff;
2. one maintainer analysis that records the observed failure, semantic invariant, root cause, and
   proposed repair before or together with the candidate;
3. one semantic repair candidate changing only the allowed Rust source path;
4. focused validation, then one exact candidate-head ordinary CI and Binary Feasibility matrix;
5. one independent TaskCard Gate Review;
6. focused repair/revalidation/re-review only if the Reviewer finds a concrete L3 defect.

A rustfmt, Clippy, compiler, path, evidence-SHA, or wording correction that does not change the
diagnosed semantics is L1 and does not consume a second semantic repair attempt. The maintainer may
make at most one such mechanical correction after CI. A second semantic hypothesis, weakening a
test/fixture/gate, changing the injected family into another behavior, or needing another feature
card exceeds the budget and stops Rust.

No new dependency, module, fixture, test, workflow, abstraction, compatibility layer, or production
path may be added to make the repair easier. Existing tests and fault evidence are the oracle and
remain read-only during the maintainer attempt.

## Required semantic preservation

The repair must restore the exact RTS-022A behavior, including:

- immutable RunSpec and exact run/invocation/task/source identity;
- one RunStore transition writer and separately observable authorization, launch intent, started,
  result, Artifact validation, Git effect, handoff, terminal, and stop facts;
- prepared-only launch eligibility, authorization-without-journal owner requirement, launch/start
  ambiguity without replay, and durable-result continuation without a second provider;
- exact provider counts, terminal replay idempotency, and duplicate input no-effect behavior;
- strict duplicate-key/checksum/identity/provenance validation;
- byte-for-byte read-only status with exactly one legal next action;
- exact stop denial for an active invocation, active writer, or mismatched identity;
- no-remote trusted Git import and exact HEAD/tree/worktree validation before acceptance;
- structured child argv, no shell, minimized environment, zero Cargo dependencies, and no Python
  runtime child in the measured Rust path;
- exact five-target aggregate binding for all 14 shared rows and their assertion/prohibited proofs.

The maintainer may simplify the faulty expression locally if behavior remains exact. The attempt must
not refactor unrelated Rust code, reformat the crate broadly, weaken an assertion, delete a test,
change the fixture, suppress a lint globally, or change CI semantics.

## Frozen model-writable scope

- `experiments/runtime-v2-rust/src/lib.rs`
- `.awf/artifacts/impl-report-runtime-v2-rts-022-maintainer-fault-gate.md`
- `.awf/artifacts/review-report-runtime-v2-rts-022-maintainer-fault-gate.md`

The TaskCard, Rust tests, shared fixture, Cargo metadata/lock/toolchain, README, workflow files,
RTS-022A artifacts, production Python Runtime, and all other repository paths are read-only to the
maintainer. The owner seed is the only authorized pre-maintainer edit to `src/lib.rs`.

After independent Review and exact-head CI pass, owner closeout may add
`docs/tasks/runtime-v2-rts-022-maintainer-fault-gate-implementation-report.md` and update only the
gate/next-step sections of the Runtime v2 plan, HANDOFF, and ROADMAP. Those are owner-authored
closeout paths outside model-write scope.

## Out of scope

- Any production `src/`, `scripts/`, schemas, CLI, package metadata, installer, lifecycle manager,
  state format, provider adapter, facade, or Agent Bus integration.
- Any live/retained event, delivery, queue, listener, service, state root, payload, credential,
  provider, ACK, GitHub business mutation, remote Git write, or historical recovery action.
- Manual ACK, requeue, fail, recover, redispatch, replacement delivery, stale-lock deletion,
  migration, or destructive cleanup.
- New tests or expected-result tables written to fit the repair; existing test and fixture behavior
  is frozen.
- SQLite/Store selection, physical Coordinator, product boundary, semantic-contract Frozen
  promotion, Go implementation, production/default/release/migration, signing, packaging,
  installer/updater, or native lifecycle work.
- A second maintainer fault, second semantic repair hypothesis, or another RTS-022 TaskCard.

## Deterministic result

Return exactly one result:

- `RUST_MAINTAINER_GATE_PASS`: the fresh maintainer independently identifies the violated Candidate
  invariant, repairs it in one semantic attempt, preserves scope, passes exact candidate/final-head
  CI, and receives independent Gate Review PASS;
- `STOP_RUST_MAINTAINER_DIAGNOSIS`: the maintainer cannot identify one defensible root cause from
  the permitted evidence in the bounded pass;
- `STOP_RUST_MAINTAINER_REPAIR`: the first semantic repair does not restore the failing behavior or
  creates another semantic failure;
- `STOP_RUST_MAINTAINER_SCOPE`: repair requires forbidden history hints, weakened tests/evidence,
  new dependencies/modules/frameworks/platform APIs, production changes, or another TaskCard;
- `STOP_RUST_MAINTAINER_SEMANTICS`: the repair passes a narrow symptom but violates the Candidate
  fault matrix, no-replay, idempotency, provenance, exact-stop, or read-only-status contract.

A stop result preserves evidence and returns to the owner plan gate. It does not authorize Go,
Python selection, Rust production work, or any default/migration/release action automatically.

## Acceptance criteria

- [ ] The TaskCard is frozen on the exact main base and independently reviewed before fault seed.
- [ ] The owner seed changes only Rust `src/lib.rs`, contains exactly one allowed L3 fault, compiles,
      and produces at least one existing deterministic test/verification failure on exact seeded HEAD.
- [ ] The fresh maintainer has no RTS-022A implementation/review context and does not inspect any
      seed-parent patch/history surface before submitting the repair.
- [ ] The maintainer records the observed CI evidence, violated invariant, root cause, candidate
      repair, and why prohibited effects remain denied.
- [ ] Exactly one semantic repair candidate changes only `src/lib.rs`; any later correction is
      demonstrably L1 and within the single mechanical allowance.
- [ ] The repair restores the seeded failure without changing tests, fixture, Cargo files, workflow,
      dependencies, artifacts from RTS-022A, or production paths.
- [ ] Focused Rust tests, rustfmt, Clippy, release build, all 14 shared rows, normal lifecycle,
      completed replay, status, exact stop, and aggregate evidence pass.
- [ ] Ordinary Python CI and all five Rust/Binary Feasibility target cells pass on the exact final
      candidate head.
- [ ] Scope audit finds no generated files, build artifacts, mass formatting, unrelated refactor,
      or unapproved path.
- [ ] One independent Gate Reviewer verifies the full seed-to-candidate history, independent
      diagnosis record, exact semantic restoration, budget, and stop/fallback result.
- [ ] The final result is one exact deterministic result and does not select a Runtime, Store,
      Coordinator, product boundary, production default, migration, or release.

## Verification

- Local Mac before maintainer handoff: static allowed-path/prohibited-surface audit, Artifact JSON
  parse, and `git diff --check` only. Do not run Cargo, rustc, Rust binaries, pytest, or Ruff.
- Seeded-head GitHub evidence: existing pinned Rust format/lint/build/tests and focused shared-slice
  failure; ordinary CI remains evidence that production Python behavior was not changed.
- Candidate/final-head GitHub evidence: one complete required ordinary CI and Binary Feasibility
  matrix, with focused job reruns only for external or L1 failures.
- Independent Review: frozen TaskCard before seed; one TaskCard Gate Review after candidate; focused
  re-review only for a concrete Reviewer finding.

## Required output

- one frozen and independently reviewed maintainer-gate TaskCard;
- one owner seed commit and exact seeded-head failing CI identity;
- one independent maintainer diagnosis and bounded Rust source repair;
- compiled ImplementationReport and ReviewReport artifacts;
- one owner closeout recording PASS or the exact Rust stop result and the legal next plan gate.

<!-- awf-postflight
{
  "allowed_paths": [
    "experiments/runtime-v2-rust/src/lib.rs",
    ".awf/artifacts/impl-report-runtime-v2-rts-022-maintainer-fault-gate.md",
    ".awf/artifacts/review-report-runtime-v2-rts-022-maintainer-fault-gate.md"
  ],
  "verification_commands": [
    ["cargo", "fmt", "--manifest-path", "experiments/runtime-v2-rust/Cargo.toml", "--check"],
    ["cargo", "clippy", "--locked", "--manifest-path", "experiments/runtime-v2-rust/Cargo.toml", "--", "-D", "warnings"],
    ["cargo", "test", "--locked", "--manifest-path", "experiments/runtime-v2-rust/Cargo.toml"],
    ["cargo", "build", "--locked", "--release", "--manifest-path", "experiments/runtime-v2-rust/Cargo.toml"],
    ["{python}", "-m", "pytest", "-q"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
