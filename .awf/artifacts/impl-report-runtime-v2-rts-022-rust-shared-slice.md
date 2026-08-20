# Implementation Report: RTS-022A Rust Shared Disposable Slice

## Summary

Added and repaired a removable Rust experiment under `experiments/runtime-v2-rust/` plus isolated
`rust-shared-slice` and `rust-shared-aggregate` jobs in the existing Binary Feasibility workflow.
The executable exposes experiment-local `run`, read-only `status`, and exact local `stop` commands,
with hidden `provider`, `inject`, `verify`, `measure`, and `aggregate` helpers for CI and semantic
checks.

The scripted provider is a child process of the same executable but is still launched with
structured argv, no shell, stdin closed, and a credential-minimized environment. Git remains an
external executable prerequisite, is invoked with structured argv only, and trusted disposable
repositories are configured with no remotes during creation. Status and revalidation paths do not
rewrite Git config or remove remotes.

## Boundary Statement

Real disposable/local evidence implemented:

- immutable compiled RunSpec envelope with checksum and exact source Git head/tree binding;
- one RunStore writer for phase, authorization, handoff, terminal, trusted Git identity, and stop;
- prepared invocation journal before authorization, distinct launch/start/result/validated facts;
- authorized recovery launches only from `prepared`; `launch_intent`/`started` are ambiguous and
  `result`/`validated` skip provider and rejoin durable artifacts;
- strict duplicate-key rejection before JSON object construction for fixture, state envelopes,
  provider reports, ReviewReport, ImplementationReport, machine evidence, and aggregate input;
- normal implement -> trusted local Git commit -> review -> terminal path with exactly one
  implement and one review provider child;
- byte-read-only `status` projection, completed replay without provider/Git effect, and exact idle
  local `stop`;
- exact writer lock using `create_new` identity for `run` and `stop`; active writer/invocation stop
  fails closed and no stale lock cleanup is attempted;
- injected shared fault rows for all 14 Candidate fixture rows with exact legal-next-action,
  assertion, prohibited-effect, provider-count, and byte-stability checks;
- five-target CI evidence fields for requested/actual target, source revision, rustc/cargo/toolchain
  versions, executable SHA-256, size, startup samples, child executables, dependency counts,
  provider counts, Git prerequisite, normal/status/replay/stop booleans, and computed
  `python_invoked`;
- strict Rust aggregate command that re-parses evidence with duplicate-key rejection and validates
  exact fixture IDs, outcomes, legal next actions, assertions, prohibited checks, five targets, and
  summary facts.

Synthetic or excluded evidence:

- provider intelligence, downstream delivery, transport ACK, Agent Bus, GitHub/PR, production
  package selection, release, installer/updater, native lifecycle manager, cross-host behavior,
  real credentials, retained state, and business payload delivery.

## Dependency Inventory

Direct production dependencies: `0`.

No Cargo `[dependencies]`, no build dependencies, and no dev dependencies are used. The experiment
therefore has no transitive Rust dependency graph. The implementation uses only Rust std plus the
external local `git` executable.

## Measurements

- Frozen Python denominator: 1,454 nonblank/noncomment lines; 1.5x threshold: 2,181.
- Runner-only Python denominator: 1,380 nonblank/noncomment lines; 1.5x threshold: 2,070.
- Rust production numerator under `experiments/runtime-v2-rust/src/`: 3,470 nonblank/noncomment
  lines (`lib.rs` 3,464, `main.rs` 6) after applying the exact CI-owned rustfmt output and
  the focused ownership/borrowing compile repair.
- Rust test code: 378 nonblank/noncomment lines after rustfmt.
- Direct production dependencies: 0.
- Transitive dependencies: 0.

The Rust numerator exceeds both frozen thresholds after the independent review repair added strict
aggregate parsing, exact writer locking, active-stop denial, status read-only hardening, and fuller
recovery joins. This is not hidden in tests or CI helpers: all normal control-flow Rust remains
under `src/`.

The named material value to be proven by machine evidence is removal of the Python runtime
prerequisite for this disposable shared slice while preserving the Candidate fault semantics. If
five-target CI cannot prove no-Python execution and full semantic parity, the correct result is a
Rust stop condition rather than eligibility.

## Acceptance Inventory

Operator commands implemented for the removable experiment:

- `run --state ... --repo ... --run-id ...`: one-shot local disposable run/replay path.
- `status --state ... --repo ... --run-id ...`: byte-read-only projection; no writer lock, no Git
  config writes, no remote cleanup, no repair.
- `stop --state ... --repo ... --run-id ...`: exact idle local stop only; active writer and active
  invocation both fail closed.
- Hidden CI/test helpers: `provider`, `inject`, `verify`, `measure`, `aggregate`, and
  `inspect-journal-ids`.

Human decision points:

- missing consumed implement or review journal after authorization: `OWNER_DECISION_REQUIRED`;
- `launch_intent` or `started` journals: `AMBIGUOUS_NO_REPLAY`;
- trusted Git drift/remote, extra invocation identity, namespace escape, or checksum/identity
  drift: fail closed before mutation/provider;
- provider non-zero result or corrupt report/artifact: `HANDLER_FAILURE_NO_ACK`.

Persistent families represented in the slice:

- authority: compiled RunSpec envelope, RunStore authorizations/phases, writer lock identity;
- evidence: invocation journals, ImplementationReport/ReviewReport artifacts, machine evidence,
  aggregate summary, provider counts;
- external/disposable: source Git prerequisite, trusted local Git repository, implement workspace,
  self-executable provider child.

Named recovery joins:

- implement/review authorized recovery requires a bound exact journal;
- only `prepared` may launch;
- `launch_intent`/`started` never replay automatically;
- `result`/`validated` require exact journal identity plus `result.exit_code == 0` before artifact
  and trusted Git joins;
- completed replay revalidates both successful journals, both artifacts, and trusted Git head/tree;
- status uses the same joins without writing.

Runtime prerequisites:

- compiled Rust executable for the target under test;
- external `git` executable with local no-remote disposable repositories;
- no Python runtime, shell provider, dependency registry, service manager, database, FFI, or
  production lifecycle prerequisite.

Baseline comparison:

- RTS-001 remains the broader Python baseline with 28 local persistent families and multiple
  external joins. RTS-022A is intentionally a removable Rust shared-slice experiment, not a
  replacement for RTS-001 production/default/release behavior.

## Verification At Implementation Time

- Frozen-scope check: PASS, current diff only touches the 5 authorized repair paths.
- TOML parse for `Cargo.toml` and `rust-toolchain.toml`: PASS.
- Shared fixture JSON parse: PASS.
- Static source scan: PASS for run-id namespace gate, fail-closed provider counter validation,
  successful-result journal joins, on-disk journal filename scanning, frozen source revision before
  unrelated-cwd switch, row identity/decision evidence, and aggregate row validation.
- `git diff --check`: PASS.
- Local `cargo`, `rustc`, `pytest`, Ruff, and binary execution: intentionally not run on Mac per
  TaskCard boundary.

## CI Contract

The new Rust job runs `cargo +1.85.1 fmt --check`, `cargo +1.85.1 clippy -D warnings`,
`cargo +1.85.1 test`, and `cargo +1.85.1 build --release --locked` on:

- `linux-x86_64`
- `linux-arm64`
- `windows-x86_64`
- `macos-x86_64`
- `macos-arm64`

The Rust aggregate job is independent from the existing Binary Feasibility aggregate job. It
downloads the Linux Rust executable and all five Rust evidence artifacts, then runs the hidden
`aggregate` command. It rejects missing, duplicate, malformed, target-drifted, dependency-drifted,
Python-invoking, shell-boundary-drifted, fixture-action-drifted, assertion/prohibited-drifted, or
incomplete Rust evidence.

## Review Status

Independent review of exact head `5ea5ea0` returned `REQUEST_CHANGES`. This repair addresses:

- authorized RunStore + journal-state recovery and late-phase revalidation;
- fixture legal-next-action comparison and aggregate validation;
- removal of unconditional prohibited-pass mappings;
- Rust-only aggregate separation and strict parser reuse;
- pinned `cargo +1.85.1` fmt/clippy/test/release workflow gates;
- exact writer lock, active-stop denial, and status read-only Git revalidation;
- corrupt counter fail-closed handling;
- derived target/child/python evidence and toolchain/source revision facts;
- atomic temp-file `sync_all` before rename;
- same-fault redelivery byte/count/head checks;
- active-writer and active-invocation stop denial evidence;
- status Git-readonly remote/drift evidence;
- aggregate validation for source revision, toolchain, provider counts, child inventory, dependency
  completeness, and exact preliminary result.
- successful-result journal joins requiring `result.exit_code == 0` before later phase/status
  recovery, plus review missing-journal owner projection;
- `--repo .` source-revision freeze before unrelated cwd changes;
- on-disk invocation filename set validation without embedded identity conflation;
- row evidence for task/run/invocation identities, provider counts, terminal fact, and
  decision owner/source;
- public run/status/stop/inject run-id namespace fail-closed validation.
- exact aggregate binding for fixture injection boundary, recomputed decision owner/source, and
  one-to-one assertion/prohibited proof objects with allowed `proved_by` sets;
- negative aggregate tests for mutated injection, decision-source, and concrete assertion evidence.

Focused independent TaskCard Gate re-review of exact candidate `9309bb6` returned `PASS` with zero
remaining findings. The companion ReviewReport records that reviewed semantic candidate; CI and
cross-platform execution remain pending and no Rust selection is inferred.

Known CI risks before machine validation:

- Rust syntax, rustfmt, clippy, and cross-platform behavior are not locally compiled due to the Mac
  no-Rust boundary.
- The zero-dependency strict JSON parser and SHA-256 implementation are statically reviewed here
  but require GitHub Rust compilation/test evidence.
- Windows Git/path behavior is covered by workflow design but not locally executed.

<!-- awf-implementation-report
{
  "summary": "Repair the removable zero-dependency Rust Runtime v2 shared-slice experiment with successful-result journal joins, exact namespace/evidence gates, writer locking, status read-only joins, strict aggregate evidence validation, and pinned five-target Rust CI gates.",
  "changed_files": [
    "experiments/runtime-v2-rust/Cargo.toml",
    "experiments/runtime-v2-rust/Cargo.lock",
    "experiments/runtime-v2-rust/rust-toolchain.toml",
    "experiments/runtime-v2-rust/README.md",
    "experiments/runtime-v2-rust/src/lib.rs",
    "experiments/runtime-v2-rust/src/main.rs",
    "experiments/runtime-v2-rust/tests/shared_slice.rs",
    ".github/workflows/binary-feasibility.yml",
    ".awf/artifacts/impl-report-runtime-v2-rts-022-rust-shared-slice.md",
    ".awf/artifacts/review-report-runtime-v2-rts-022-rust-shared-slice.md"
  ],
  "commands": [
    "git diff --name-only",
    "python3 static scope/TOML/fixture/source scan",
    "git diff --check"
  ],
  "tests": [
    "Static TOML parse PASS",
    "Shared fixture JSON parse PASS",
    "Frozen 5-path repair scope PASS",
    "Source gate scan PASS",
    "Whitespace diff check PASS"
  ],
  "source_revision": "8dc91fd77efce6cb7fefd59f7393fc395a1c3589",
  "review_status": "PASS",
  "preliminary_result": "PENDING_CI",
  "dependency_count": 0,
  "rust_source_nonblank_noncomment_loc": 3470,
  "rust_lib_nonblank_noncomment_loc": 3464,
  "rust_test_nonblank_noncomment_loc": 378,
  "rust_source_exceeds_2181_threshold": true,
  "named_value_requiring_machine_evidence": "removes Python runtime prerequisite for this disposable shared slice",
  "local_rust_not_run_reason": "TaskCard forbids local Mac cargo/rustc/binary execution"
}
-->
