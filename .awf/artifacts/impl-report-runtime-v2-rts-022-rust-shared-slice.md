# Implementation Report: RTS-022A Rust Shared Disposable Slice

## Summary

Added a removable Rust experiment under `experiments/runtime-v2-rust/` plus an isolated
`rust-shared-slice` matrix job in the existing Binary Feasibility workflow. The executable exposes
experiment-local `run`, read-only `status`, and exact local `stop` commands, with hidden
`provider`, `inject`, `verify`, and `measure` helpers for CI and semantic checks.

The scripted provider is a child process of the same executable but is still launched with
structured argv, no shell, stdin closed, and a credential-minimized environment. Git remains an
external executable prerequisite, is invoked with structured argv only, and trusted disposable
repositories are configured with no remotes.

## Boundary Statement

Real disposable/local evidence implemented:

- immutable compiled RunSpec envelope with checksum and exact source Git head/tree binding;
- one RunStore writer for phase, authorization, handoff, terminal, trusted Git identity, and stop;
- prepared invocation journal before authorization, distinct launch/start/result/validated facts;
- strict duplicate-key rejection before JSON object construction for fixture, state envelopes,
  provider reports, ReviewReport, ImplementationReport, and machine evidence;
- normal implement -> trusted local Git commit -> review -> terminal path with exactly one
  implement and one review provider child;
- byte-read-only `status` projection, completed replay without provider/Git effect, and exact idle
  local `stop`;
- injected shared fault rows for all 14 Candidate fixture rows with assertion/prohibited mappings;
- five-target CI evidence fields for target, executable SHA-256, size, startup samples, child
  executables, dependency counts, provider counts, Git prerequisite, and `python_invoked=false`.

Synthetic or excluded evidence:

- provider intelligence, downstream delivery, transport ACK, Agent Bus, GitHub/PR, production
  package selection, release, installer/updater, native lifecycle manager, cross-host behavior,
  real credentials, retained state, and business payload delivery.

## Dependency Inventory

Direct production dependencies: `0`.

No Cargo `[dependencies]`, no build dependencies, and no dev dependencies are used. The experiment
therefore has no transitive Rust dependency graph. The implementation uses only Rust std plus the
external local `git` executable. This intentionally avoids supply-chain and lockfile ambiguity for
the first native shared-slice gate.

## Measurements

- Frozen Python denominator: 1,454 nonblank/noncomment lines; 1.5x threshold: 2,181.
- Runner-only Python denominator: 1,380 nonblank/noncomment lines; 1.5x threshold: 2,070.
- Rust production numerator under `experiments/runtime-v2-rust/src/`: 2,049 nonblank/noncomment
  lines (`lib.rs` 2,043, `main.rs` 6).
- Rust test code: 54 nonblank/noncomment lines.
- Direct production dependencies: 0.
- Transitive dependencies: 0.

The Rust numerator is below both frozen thresholds. The measured material value to be proven by CI
is removal of the Python runtime prerequisite for this disposable shared slice while preserving the
Candidate fault semantics.

## Verification At Implementation Time

- TOML parse for `Cargo.toml` and `rust-toolchain.toml`: PASS.
- Shared fixture parse/count check: PASS, format `awf.runtime-v2-shared-slice-cases.v1`, maturity
  `Candidate`, 14 unique rows.
- Manual line-length scan for `experiments/runtime-v2-rust/` and Binary Feasibility workflow: PASS,
  zero lines over 120 columns after repair.
- `git diff --check`: PASS.
- Local `cargo`, `rustc`, `pytest`, Ruff, and binary execution: intentionally not run on Mac per
  TaskCard boundary.

## CI Contract

The new Rust job builds and runs the semantic suite on:

- `linux-x86_64`
- `linux-arm64`
- `windows-x86_64`
- `macos-x86_64`
- `macos-arm64`

The aggregate job rejects missing, duplicate, malformed, target-drifted, dependency-drifted,
Python-invoking, shell-boundary-drifted, or incomplete Rust evidence.

## Review Status

Implementation is ready for independent review but not self-approved. The companion ReviewReport is
intentionally `BLOCKED` with `PENDING_INDEPENDENT_REVIEW`.

Known CI risks before reviewer/CI:

- Rust syntax and cross-platform behavior are not locally compiled due to the Mac no-Rust boundary.
- The zero-dependency strict JSON parser and SHA-256 implementation are statically reviewed here
  but require GitHub Rust compilation/test evidence.
- Windows Git/path behavior is covered by workflow design but not locally executed.

<!-- awf-implementation-report
{
  "summary": "Add a removable zero-dependency Rust Runtime v2 shared-slice experiment with run/status/stop, self-child provider, strict duplicate-key JSON, checksummed state, local Git effects, fixture-driven fault evidence, and five-target CI evidence.",
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
    "python3 TOML parse for Cargo.toml and rust-toolchain.toml",
    "python3 shared fixture parse/count check",
    "manual line-length scan for Rust experiment and workflow",
    "git diff --check"
  ],
  "tests": [
    "Static TOML parse PASS",
    "Shared fixture unique-row check PASS",
    "Line-length scan PASS",
    "Whitespace diff check PASS"
  ],
  "source_revision": "WORKING_TREE_PENDING_COMMIT",
  "review_status": "PENDING_INDEPENDENT_REVIEW",
  "preliminary_result": "PENDING_CI_AND_INDEPENDENT_REVIEW",
  "dependency_count": 0,
  "rust_source_nonblank_noncomment_loc": 2049,
  "local_rust_not_run_reason": "TaskCard forbids local Mac cargo/rustc/binary execution"
}
-->
