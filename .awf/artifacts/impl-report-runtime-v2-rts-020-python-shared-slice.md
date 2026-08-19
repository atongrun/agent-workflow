# Implementation Report: RTS-020 Python Shared Disposable Slice

## Summary

Added a removable repository-local Python experiment under `experiments/runtime-v2-python/`.
The slice implements `run`, `status`, and `stop` as an experiment protocol only; it is not the
installed `awf` command surface and is not production/default/release/migration evidence.

The normal path compiles an immutable `RunSpec`, creates a prepared `InvocationJournal` before
RunStore authorization, launches one scripted implement child process, validates/imports its allowed
delta into a trusted no-remote disposable Git clone, launches one scripted PASS reviewer, revalidates
the exact trusted Git identity, and records terminal completion. Duplicate completed `run` is
idempotent and does not add provider, Git, or terminal effects.

## Boundary statement

Real disposable/local evidence:

- structured Python child-process argv with no shell;
- atomic JSON state envelopes with checksums;
- one `RunStore` writer for workflow phase, authorization, handoff intent, terminal and local stop;
- one `InvocationJournal` API for prepared records, launch intent, process observation, result,
  Artifact validation and completion facts;
- no-remote local Git workspaces and trusted commit/tree revalidation;
- deterministic fault injection, exact rerun and duplicate checks.
- checksum-valid identity-drift rejection for RunStore, RunSpec and InvocationJournal bindings;
- phase evidence joins for implement result/commit, review result and completed terminal status;
- exact authorization set/content validation before phase projection or continuation;
- credential-minimized child environment with a sentinel-secret regression.

Synthetic evidence:

- implementer and reviewer intelligence;
- delivery/downstream-intent observation;
- identifiers and timestamps outside local state identity;
- provider, transport, ACK, PR, CI, GitHub and release-shaped facts.

The stop command is explicitly unequal lifecycle evidence: the slice has no native manager, no
service lease and normally no long-lived process. It only records an exact local stop after proving
no invocation is active.

## Baseline comparison against RTS-001

- Authority domains represented: immutable run intent, workflow stage/authorization/terminal,
  invocation journal, provider process observation, trusted local Git effect and read-only status.
- Authority domains excluded: Agent Bus transport, real provider selection, GitHub/PR/provenance,
  release/default wiring, service lifecycle, retained delivery, cross-host state adoption and ACK.
- Persistent record families: one per-run `runspec.json` authority record, one per-run `run.json`
  authority/intent record, one per-invocation journal record, one provider-count evidence file and
  disposable Git repositories as external observations. No checkpoint/outbox/inbox duplicate
  authority exists in the experiment.
- Eight recovery decisions join only `runspec.json`, `run.json`, the relevant invocation journal,
  provider-count evidence and trusted Git HEAD/tree/worktree facts.
- Normal human decisions: one `run`, optional read-only `status`, optional exact-slice `stop`.
  Fault support actions remain owner diagnosis/preserve-evidence actions and are not hidden by
  status.
- Remaining complexity belongs to packaging/distribution, lifecycle manager semantics, real
  provider compatibility, GitHub/provenance, Bus ACK observation, cross-host state and migration.
- The slice does not cover real business parity, rework, transport resend, PR tuple verification,
  remote Git, retained payload recovery or installed CLI UX.

Class/file/record count reduction is not claimed as PASS by itself. The PASS claim is limited to
retaining the Candidate fault outcomes and owner boundaries inside a smaller disposable Python
baseline.

## Measurements

- Experiment production nonblank/noncomment LOC: `runner.py` 1380, provider fixture 74.
- Fixture/test LOC: shared JSON fixture 300 lines, focused pytest module 636 nonblank/noncomment
  lines.
- Direct dependencies: Python standard library, repository test dependency `pytest`, local `git`
  executable.
- Platform gates exercised locally: Python compile, duplicate-key fixture validation, direct
  runner smoke covering normal path and all 14 machine fault rows.
- Platform gates not exercised locally: focused pytest, full pytest, Ruff and cross-platform CI.
  The Mac boundary for this task remains no local pytest/Ruff.

## Independent review status

Independent review of `aa315f5f847f89cb3bb2ebec46d9ccf8fd4aca7b` returned `REQUEST_CHANGES`
with four HIGH findings and one MEDIUM finding. This follow-up fixes:

- constant-true prohibited assertions by replacing them with machine-readable fixture assertions and
  concrete state/effect checks;
- checksum-valid RunSpec, RunStore and InvocationJournal identity drift before provider/mutation;
- review-stage `prepared`/`launch_intent`/`started`/durable-result recovery semantics;
- `stop` denial for corrupt, unreadable or identity-invalid journals without writing;
- credential-minimized provider child environment and duplicate-key state/artifact fail-closed
  handling.

The third independent review of `b4adae5673e01687c1827bc0f2cd942968e516ae` returned `PASS` with
zero findings. GitHub CI and final publication-head review remain separate gates.

Second independent review of `5de57901bc2bf2bf6c9f7939ebb51b6b051985f6` also returned
`REQUEST_CHANGES` with one HIGH finding and one MEDIUM finding. This follow-up fixes:

- implement-result and implement-committed journal/artifact drift joins before status or
  continuation;
- review-result and completed-terminal journal/artifact drift joins before SAFE/TERMINAL projection;
- exact phase-required authorization set/content validation, including erased and duplicate auth
  failures;
- one-for-one prohibited-effect mapping to concrete assertion codes, including absent journal,
  launch/started state, exact journal IDs, handoff exactness and rerun/provider-count stability;
- manual Python line wrapping for changed lines over 100 columns.

## Verification at implementation time

- `compile()` for `experiments/runtime-v2-python/runner.py`,
  `tests/fixtures/runtime_v2_shared_slice_provider.py` and
  `tests/test_runtime_v2_rts020_python_slice.py`: PASS
- duplicate-key JSON fixture validation with `object_pairs_hook`: PASS, 8 top-level cases
- direct helper smoke in temporary Git repositories: PASS, normal terminal plus 14 fixture rows
- expanded direct smoke: PASS, status byte-readonly snapshots, exact stop, authorized-prepared
  recovery, ambiguous no-replay, result/effect recovery, state drift, Git drift, review-stage
  durable-result recovery, launch argv drift, presence join, duplicate-key state/artifact and
  sentinel-secret child env checks
- second-review direct helper smoke: PASS, adds implement/review/terminal evidence drift,
  authorization erasure/duplicate, duplicate pre-start exact-state and prohibited-effect mapping
  guard checks
- local pytest/Ruff: intentionally not run on Mac per task boundary

<!-- awf-implementation-report
{
  "summary": "Add a removable Python Runtime v2 shared slice with one RunStore writer, one InvocationJournal API, real local Git/child-process evidence and deterministic Candidate fault coverage.",
  "changed_files": [
    "experiments/runtime-v2-python/README.md",
    "experiments/runtime-v2-python/runner.py",
    "tests/fixtures/runtime_v2_shared_slice_cases.json",
    "tests/fixtures/runtime_v2_shared_slice_provider.py",
    "tests/test_runtime_v2_rts020_python_slice.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-020-python-shared-slice.md",
    ".awf/artifacts/review-report-runtime-v2-rts-020-python-shared-slice.md"
  ],
  "commands": [
    "compile() for changed Python files",
    "duplicate-key JSON fixture validation with object_pairs_hook",
    "direct helper smoke in temporary Git repositories",
    "expanded direct smoke for recovery/no-replay/status-readonly/identity-drift/credential-env checks"
  ],
  "tests": [
    "Static compile PASS",
    "Fixture duplicate-key validation PASS",
    "Direct normal-path and fault smoke PASS after REQUEST_CHANGES fixes"
  ],
  "source_revision": "b4adae5673e01687c1827bc0f2cd942968e516ae",
  "review_status": "independent implementation review PASS after two REQUEST_CHANGES repair rounds",
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
