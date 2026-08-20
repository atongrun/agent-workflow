# TaskCard: RTS-022A Rust Shared Disposable Slice

## Task ID

runtime-v2-rts-022-rust-shared-slice

## Goal

Build one removable, repository-local Rust implementation of the Runtime v2 shared slice. The
experiment must consume the existing language-neutral 14-row fixture, execute the same disposable
implement -> review -> terminal path, and expose experiment-local `run`, read-only `status`, and
exact local `stop` commands. It must measure whether a native executable removes a current runtime
prerequisite or distribution burden without weakening the Candidate semantics.

This is the first of at most two RTS-022 implementation TaskCards. It is not a Rust selection, a
production rewrite, a Store decision, a distribution ABI, or authorization to modify installed
`awf`. If this card passes without hitting a Rust stop condition, the only permitted second
RTS-022 card is the independent-maintainer injected-fault diagnosis and repair gate required by the
development plan.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@7df8fc2c21087b021df892e365dbf7374dc36724`
- **Task branch**: `codex/runtime-v2-rts-022-rust-shared-slice`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 2 / RTS-022
- **Contract**: `docs/runtime-v2-semantic-contract.md`, status `Candidate`
- **Shared fixture**: `tests/fixtures/runtime_v2_shared_slice_cases.json`
- **Python baseline**: `docs/tasks/runtime-v2-rts-020-python-shared-slice-implementation-report.md`
- **Store evidence**: `docs/tasks/runtime-v2-rts-021-storage-comparison-implementation-report.md`

RTS-020 proved the smaller Python ownership model credible. RTS-021 showed that atomic and SQLite
remove the same four local ordering windows, while relocatable distribution remains unresolved.
That evidence satisfies RTS-022's conditional entry criterion but does not select Rust, SQLite, a
physical Coordinator, a product boundary, or a production migration.

## Experiment boundary

The implementation lives only under `experiments/runtime-v2-rust/` plus its dedicated CI wiring and
artifacts. It must not be imported by, delegated to, packaged by, or selected from the production
Python package. The Rust executable is an experiment named independently of the installed `awf`
command.

Real but disposable/local evidence:

- a natively built Rust executable on the existing five GitHub-hosted target runners;
- structured child-process argv with no shell and a credential-minimized environment;
- immutable run-intent compilation and digest checking;
- one exact local writer boundary and checksummed append/atomic journal state;
- isolated provider workspaces and Artifact validation/import;
- trusted disposable local Git commits with no remotes and exact HEAD/tree revalidation;
- deterministic fault injection, restart, duplicate invocation, contention, and exact-stop checks;
- artifact size, startup samples, direct dependency inventory, and runtime-prerequisite observation.

Synthetic or excluded evidence:

- implementer and reviewer intelligence;
- delivery, downstream send, handler success, transport, and ACK observation;
- remote Git, GitHub, PR, CI-as-business-fact, signing, notarization, attestation, release, updater,
  installer, native lifecycle manager, and cross-host behavior;
- real provider credentials, Agent Bus, production state, retained delivery, and business payloads.

The five-target CI result is evidence about this disposable executable only. It cannot establish
installed `awf` resource compatibility, Python interpreter re-entry, native service lifecycle,
production distribution trust, or release readiness.

## Frozen architecture and dependency budget

1. One immutable compiled `RunSpec` concept owns task, repository, allowed-path, provider-command,
   and identity bindings. Source input and compiled digest cannot both become mutable authorities.
2. One logical `RunStore` writer owns Workflow phase, authorization, exact local handoff intent,
   terminal, and local stop facts. Physical Coordinator deployment remains undecided.
3. One `InvocationJournal` API owns implement/review prepared state, launch intent, process
   observations, durable result, Artifact validation/import, and completion facts. The API may
   encode records in the same checksummed local journal as `RunStore`; it must not recreate the
   production checkpoint/outbox/inbox graph.
4. The Rust slice uses only the simplest credible checksummed atomic-file or append-journal baseline
   supported by RTS-021. It must not implement or select SQLite. Store choice remains RTS-024 work.
5. The supported writer API persists a non-launching prepared invocation before committing its
   exact RunStore authorization. Prepared is not launch intent. Authorization without its bound
   journal is injected owner-required state and cannot start a child or be guessed-repaired.
6. Authorization, launch intent, process observation, result, Artifact validation, trusted Git
   effect, handoff intent, and terminal remain separately observable facts. The rejected five-state
   invocation model is not sufficient.
7. The scripted provider is a separate child process. It may be implemented as a hidden subcommand
   of the same Rust executable so the measured normal path does not require Python. Self-execution
   still uses structured argv, no shell, an isolated workspace, and the same durable start/result
   rules as any external provider.
8. Git remains an external executable prerequisite and must be invoked with structured argv. Do
   not embed Git, use libgit2, retain a remote, or claim local state is atomic with Git.
9. `status` is a pure authority projection. It never writes, locks for mutation, repairs, resumes,
   invokes, imports, stops, migrates, or executes its displayed action.
10. `stop` is scoped to the exact experiment/run identity and succeeds only after proving there is
    no active invocation or writer. No PID-only, process-name-only, stale-lock deletion, service
    manager, or platform lifecycle logic is allowed.
11. Cargo `[dependencies]` contains at most six direct production dependencies. Every direct
    dependency requires its exact locked version, SPDX license expression, purpose, maintenance
    signal, supported-platform evidence, transitive count, and supply-chain note in the report.
    Build/dev dependencies are listed separately and do not evade the direct-dependency budget.
12. No async runtime, ORM, embedded Git, plugin framework, generic provider registry, scheduler,
    database, unsafe block, FFI, OS service framework, or new production Python dependency is
    permitted.
13. The complete slice is removable by deleting its experiment, dedicated test/CI additions, and
    artifacts. It writes no production format and performs no production migration.

## Shared normal path and command protocol

One Rust `run` command must execute, without intermediate operator commands:

```text
compile immutable RunSpec
  -> persist prepared implement journal
  -> authorize exact implement invocation
  -> persist launch intent and observe one scripted child
  -> persist and validate ImplementationReport
  -> import allowed delta into trusted no-remote disposable Git and commit
  -> persist exact local review handoff intent
  -> persist prepared review journal and authorize exact review invocation
  -> persist launch intent and observe one scripted child
  -> persist and validate normalized PASS ReviewReport
  -> revalidate exact Git/workspace identity
  -> terminal completed
```

Normal provider count is exactly implement=1 and review=1. Repeating the same completed `run` is
byte/effect-idempotent and starts no child or Git effect. `status` reports the same terminal and one
legal next action without changing state. `stop` records only the exact idle local slice stop and is
explicitly unequal to production lifecycle evidence.

The executable may expose test-only `inject`, `verify`, or `measure` commands. They are not counted
as normal user commands and cannot mutate production or live state.

## Shared fixture contract

`tests/fixtures/runtime_v2_shared_slice_cases.json` is read-only input to this TaskCard. The Rust
suite must reject duplicate keys, require its current format and `Candidate` maturity, resolve all
declared outcomes against `docs/runtime-v2-semantic-contract.md`, and execute all eight top-level
fault families and all 14 current machine rows. It must not copy expected results into a
Rust-specific table or silently skip unknown/new rows.

The same duplicate-key rejection applies to every JSON document the Rust slice trusts, including
RunSpec input, authority records, provider results, ImplementationReport, ReviewReport, and
machine evidence. Default map deserialization that silently keeps the first or last duplicate is
not sufficient.

For every row, machine-readable evidence must match:

- exact case/subcase ID and injection boundary;
- Candidate normalized outcome;
- exactly one legal next action;
- every fixture `assertions` item through a concrete effect/state assertion;
- every fixture `prohibited` item through at least one concrete no-effect assertion;
- stable run/invocation identities, provider counts, terminal fact, and blocker owner/source;
- byte-for-byte read-only status before and after projection.

At minimum the Rust slice must preserve the existing rules for authorization-without-journal,
authorized prepared start-once, persisted launch intent ambiguity/no-replay, durable-result resume,
trusted-effect revalidation, duplicate pre-start/terminal behavior, checksum/identity drift, and
Git/workspace drift before terminal.

The Rust implementation may encode state differently from Python. It may not weaken or reinterpret
fixture outcomes, legal next actions, owner boundaries, ambiguity, or prohibited effects.

## Platform and distribution evidence

The existing `Binary Feasibility` workflow may gain one isolated Rust job without changing its
existing Python/Go candidate semantics. The job builds and exercises the Rust slice natively on:

- Linux x86_64 and arm64;
- Windows x86_64;
- macOS x86_64 and arm64.

Each target must:

1. use the committed lockfile and pinned repository toolchain contract;
2. build the release executable and run the complete shared semantic suite;
3. run normal `run`, `status`, completed replay, and exact `stop` from an unrelated working
   directory with fresh temporary state and a no-remote Git repository;
4. prove child argv uses no shell and list every runtime child executable actually invoked;
5. record executable SHA-256, byte size, target triple, Rust/Cargo versions, direct and transitive
   dependency counts, five bounded startup samples, normal provider counts, Git prerequisite, and
   whether Python was invoked;
6. upload only credential-free machine evidence and the disposable executable with short
   retention; never upload state roots, provider workspaces, Git repositories, payloads, tokens, or
   absolute local paths.

The aggregate job fails closed on missing, duplicate, malformed, target-drifted, or semantically
unequal evidence. It reports measured facts and a preliminary Rust eligibility result only; green
CI is not a production distribution decision.

## Measurement and stop contract

The report compares like-for-like executable experiment code. The frozen Python denominator is
1,454 nonblank/noncomment lines: 1,380 in the RTS-020 runner plus 74 in its scripted provider. The
Rust numerator is all nonblank/noncomment `.rs` lines under `experiments/runtime-v2-rust/src/`,
including any self-provider implementation. The 1.5-times threshold is therefore 2,181 lines.
Tests, build metadata, the shared JSON fixture, CI collection code, and reports are measured and
reported separately, not hidden in the production numerator.

The report also gives a runner-only comparison against the Python runner's 1,380 lines and its
2,070-line 1.5-times value. This secondary split cannot exclude Rust source that participates in
normal control flow merely by naming it a helper.

The report also records the RTS-021 1,624-line runner/storage comparison as secondary context, but
that value does not replace the frozen RTS-020 threshold.

Return `RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE` only if all shared semantics and all five
target cells pass, dependency evidence is complete, no prohibited expansion exists, and the slice
shows at least one measured prerequisite, ownership, or distribution improvement. Otherwise return
one explicit stop result and preserve the evidence:

- `STOP_RUST_SHARED_SEMANTICS`: any supported OS still fails a shared row after bounded repair;
- `STOP_RUST_PROHIBITED_EXPANSION`: safety requires async/ORM/embedded Git/plugin/registry/unsafe/
  lifecycle or another prohibited surface;
- `STOP_RUST_DEPENDENCY_BUDGET`: more than six direct production dependencies or incomplete
  license/maintenance/platform/supply-chain evidence;
- `STOP_RUST_SIZE_WITHOUT_VALUE`: Rust exceeds 2,181 production lines without eliminating a named
  ownership boundary or prerequisite;
- `STOP_RUST_NO_MATERIAL_VALUE`: semantics pass but no measured ownership, prerequisite, or
  distribution improvement remains over the Python candidate.

If the Rust numerator exceeds 2,181, the report must name the exact eliminated boundary or runtime
prerequisite and prove it with machine evidence; a single binary, class-count reduction, memory
safety, or language preference alone is not sufficient. This card cannot waive a stop condition.

An eligible result authorizes only a separately frozen RTS-022B maintainer-fault TaskCard. A stop
result returns to the plan's later decision/fallback gate; it does not authorize Go automatically,
production Rust work, or a workaround under this card.

## Frozen model-writable scope

- `experiments/runtime-v2-rust/Cargo.toml`
- `experiments/runtime-v2-rust/Cargo.lock`
- `experiments/runtime-v2-rust/rust-toolchain.toml`
- `experiments/runtime-v2-rust/README.md`
- `experiments/runtime-v2-rust/src/lib.rs`
- `experiments/runtime-v2-rust/src/main.rs`
- `experiments/runtime-v2-rust/tests/shared_slice.rs`
- `.github/workflows/binary-feasibility.yml`
- `.awf/artifacts/impl-report-runtime-v2-rts-022-rust-shared-slice.md`
- `.awf/artifacts/review-report-runtime-v2-rts-022-rust-shared-slice.md`

The committed TaskCard and the existing shared fixture are frozen owner inputs and are not
model-writable. Adding another source module, build script, fixture, test helper, workflow, or
dependency file requires an owner-authored TaskCard correction before implementation.

After an implementation ReviewReport is compiled, owner closeout may add
`docs/tasks/runtime-v2-rts-022-rust-shared-slice-implementation-report.md` and update only the gate
status/next-step sections of the Runtime v2 plan, HANDOFF, and ROADMAP. Those paths are outside the
model-write scope.

## Out of scope

- Any production `src/`, `scripts/`, schemas, CLI, facade, entry point, dependency metadata,
  installed resource, state format, lifecycle manager, provider adapter, or Agent Bus integration.
- Any live/retained repository, event, delivery, queue, listener, service, state root, payload,
  credential, ACK, provider, GitHub mutation, remote Git write, or historical recovery operation.
- Manual ACK, requeue, fail, recovery, redispatch, replacement delivery, stale-lock deletion, or
  destructive cleanup.
- SQLite, Store selection, physical Coordinator, product-boundary ADR, semantic-contract Frozen
  promotion, Go slice, production migration/default/release, installer/updater, signing,
  notarization, attestation, or artifact publication outside short-retention CI artifacts.
- Production lifecycle parity, Python interpreter re-entry parity, real provider/transport/ACK,
  remote provenance, rework, cross-host state, or business parity claims.
- The independent maintainer fault injection/repair itself; that consumes the only possible second
  RTS-022 TaskCard after this card passes.

## Acceptance criteria

- [ ] Task ID equals the branch leaf; every state root and Git repository is test-owned, fresh,
      no-remote, disposable, and outside production paths.
- [ ] One native executable exposes the experiment-local `run/status/stop` protocol and reaches
      terminal with exactly one implement and one review child in one normal `run`.
- [ ] Identical completed rerun starts no provider and produces no additional trusted Git, handoff,
      terminal, or state effect.
- [ ] One RunStore writer and one InvocationJournal API preserve separate authorization, launch,
      process, result, Artifact, Git effect, handoff, and terminal observations.
- [ ] Prepared journal precedes exact authorization; authorization without its journal is
      owner-required/no-start; launch intent without recoverable result is ambiguous/no-replay.
- [ ] Artifact allowlist/validation, isolated workspace, no-remote trusted Git import/commit, and
      exact Git revalidation are real disposable operations using structured argv and no shell.
- [ ] The Rust suite consumes the existing fixture, rejects duplicate keys, executes all 14 rows,
      and matches every normalized outcome, sole legal next action, assertion, and prohibited
      effect without an independent expected-result table.
- [ ] Status is byte-for-byte read-only for normal, terminal, failed, corrupt, ambiguous, and
      Git-drift states and never executes its reported action.
- [ ] Exact stop denies while the invocation/writer identity is active or mismatched and succeeds
      only for the exact idle local run; no PID-only or stale-lock cleanup path exists.
- [ ] Cargo has at most six direct production dependencies and complete exact-version/license/
      maintenance/platform/transitive/supply-chain evidence; no prohibited framework or `unsafe`
      code exists.
- [ ] Rust production LOC, test/CI LOC, commands, human decisions, persistent families, recovery
      joins, runtime prerequisites, binary size/startup, and synthetic/unequal boundaries are
      reported against the frozen Python and RTS-001 baselines.
- [ ] All five native target cells build, run the complete shared suite and normal lifecycle,
      produce valid credential-free evidence, and aggregate without missing/duplicate target data.
- [ ] The deterministic result is either eligible for the separate maintainer gate or one exact
      stop result; no result selects Rust or authorizes production work.
- [ ] Focused Cargo tests, release build, ordinary full pytest/Ruff, existing Candidate reference
      regressions, dedicated five-target Rust evidence, and Binary Feasibility all pass on the exact
      publication head.
- [ ] Independent TaskCard, implementation, and final exact-head Reviewers return `PASS`; ordinary
      repair loops do not weaken this frozen scope or consume the separate maintainer-fault card.

## Verification

- Local Mac: static JSON/TOML duplicate-key checks, source/manifest/prohibited-dependency scan,
  allowed-path audit, Artifact envelope parse, line counting, and `git diff --check` only. Do not
  run Cargo, Rust compiler/tests/format/lint, pytest, Ruff, or binary execution locally.
- GitHub ordinary CI: full existing Python pytest/Ruff/resource/wheel gates and Candidate reference
  regressions.
- GitHub dedicated native matrix: pinned Cargo build/test/release execution and machine evidence on
  Linux x86_64/arm64, Windows x86_64, and macOS x86_64/arm64.
- Independent review: frozen TaskCard before implementation; exact implementation/fault/fixture/
  dependency/evidence scope before publication; fresh exact PR head after all fixes and closeout.

## Required output

- one removable Rust crate exposing the shared experimental command protocol;
- one focused Rust suite that consumes the existing 14-row fixture;
- one isolated five-target CI evidence lane and aggregate result;
- compiled ImplementationReport and ReviewReport artifacts;
- a later owner-authored closeout that records eligibility or the exact Rust stop result.

<!-- awf-postflight
{
  "allowed_paths": [
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
