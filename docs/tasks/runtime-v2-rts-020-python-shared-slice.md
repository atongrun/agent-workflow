# TaskCard: RTS-020 Python Shared Disposable Slice

## Task ID

runtime-v2-rts-020-python-shared-slice

## Goal

Build the first comparative Runtime v2 slice as a disposable, repository-local Python experiment.
One normal `run` command must compile immutable run intent, invoke one scripted implementer, validate
and import its Artifact into a trusted disposable Git repository, invoke one scripted `PASS`
reviewer, and persist terminal completion. Read-only `status` and exact-slice `stop` commands must
use the same state.

This slice asks whether a smaller Python ownership model is credible before considering a native
rewrite. It is not production Runtime v2, a refactor of the current default, or an implementation
choice.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@bc7a7494a7ae9b2b041d5fde2fe5c1280d3f9d78`
- **Task branch**: `codex/runtime-v2-rts-020-python-shared-slice`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 2 / shared slice / RTS-020
- **Contract**: `docs/runtime-v2-semantic-contract.md`, status `Candidate`
- **Fault source**: `docs/testing/runtime-v2-fault-matrix.json`

Phase 1 passed: RTS-010 supplies the real post-remediation business PASS and RTS-011 supplies the
complete disposable deterministic rework acceptance. The Candidate contract is not Frozen.

## Experiment boundary

The implementation must live under `experiments/runtime-v2-python/` and must not be imported by,
delegated to, or selected from the installed production `awf` package. Its command protocol is
logically named `run`, `status`, and `stop`; tests may invoke the experiment runner with Python.
The report must record that this is not yet the installed `awf run/status/stop` surface and therefore
is unequal UX/distribution evidence.

Real but disposable/local:

- Python child-process supervision using structured argv with no shell;
- immutable run-intent compilation and digest checking;
- atomic local state and per-invocation journal writes;
- isolated workspaces and Artifact validation/import;
- trusted local Git commits and exact tree/HEAD revalidation;
- deterministic fault injection, restart and duplicate invocation checks.

Synthetic:

- implementer and reviewer intelligence;
- delivery and downstream-intent observation;
- all identifiers and timestamps;
- any provider, transport, ACK, PR, CI or GitHub-shaped field.

There is no Agent Bus, real provider, GitHub call, service manager, remote Git write, production
state, retained delivery or credential in this slice. No synthetic fact may be reported as real
business, transport, ACK, GitHub, lifecycle or release evidence.

## Frozen architecture budget

1. One immutable compiled `RunSpec` concept owns task/repository/allowed-path/provider-command and
   identity bindings. Source input and compiled digest cannot both become mutable authorities.
2. One logical `RunStore` writer owns Workflow stage, authorized invocation, exact local handoff
   intent and terminal transition. Physical Coordinator deployment remains undecided.
3. One `InvocationJournal` API owns every implement/review process intent, start observation,
   result observation, Artifact validation/import and completion fact. It may create one journal
   instance per invocation, but no second checkpoint/outbox/inbox authority is allowed.
   The journal's non-launching `prepared` record must exist before RunStore authorization is
   committed, so the supported API cannot produce an authorized invocation with no journal. An
   observed/tampered authorization-without-journal state remains owner-required and cannot start a
   provider. Prepared is not launch intent.
4. Provider process, filesystem and Git facts remain external observations. A local transaction
   must not claim atomicity across them.
5. Authorization, process start, result persistence, Artifact validation, trusted Git effect,
   handoff intent and terminal remain separately observable facts; the rejected five-state model
   must not collapse them.
6. Stable run and invocation IDs survive exact rerun. Completed or ambiguous provider invocation
   cannot be repeated.
7. `status` is a pure projection. It must never write state, invoke a provider, repair Git, resume
   work or execute its reported action.
8. `stop` is scoped only to this experiment's exact run identity. Because the shared slice has no
   native manager and normally has no long-lived process, it may only record an exact local stop
   after proving no invocation is active. The report must label this as unequal lifecycle evidence.
9. Use only the Python standard library and existing repository dependencies. No new dependency,
   facade over the production facade, provider registry, scheduler, ORM, async framework, service,
   database, physical Coordinator or generic Workflow engine.
10. The complete experiment must be removable by deleting its experiment/test/artifact files; it
    must not write or migrate production formats.

This card deliberately does not freeze filenames or tables as language-neutral semantics. RTS-021
will compare atomic-file/journal and SQLite behind the observed slice boundary; this task may use
the smallest atomic-file representation needed to make the Python baseline executable.

## Shared normal path

One `run` command must perform without intermediate operator commands:

```text
compile immutable RunSpec
  -> authorize scripted implement invocation
  -> persist launch intent and observe one child process
  -> persist and validate ImplementationReport
  -> import allowed delta into trusted disposable Git and commit
  -> persist exact local review intent
  -> authorize scripted reviewer invocation
  -> persist launch intent and observe one child process
  -> persist and validate normalized PASS ReviewReport
  -> revalidate exact Git/workspace identity
  -> terminal completed
```

The normal-path provider count is exactly implement=1, review=1, total=2. Repeating the same
completed `run` is idempotent and changes no provider, Git or terminal fact. `status` reports the
terminal and one legal next action. `stop` then closes only the exact disposable slice identity.

## Frozen language-neutral fault fixture

`tests/fixtures/runtime_v2_shared_slice_cases.json` is the common Phase 2 case table. It must reject
duplicate JSON keys and contain stable case IDs, injection boundary, expected Candidate normalized
outcome, exactly one legal next action and prohibited actions. The Python test and later candidate
slices must consume this file rather than restating expected outcomes in independent tables.

At minimum it contains:

| Case | Injection | Expected rule |
|---|---|---|
| `S-AUTH-START` | crashes across prepared journal, RunStore authorization, launch intent and process-start observation | explicit subcases prove API ordering; authorization without journal is owner-required; authorized+prepared before launch intent may start once; persisted launch intent without recoverable result is ambiguous |
| `S-START-RESULT` | crash after process start observation but before durable result | `AMBIGUOUS_NO_REPLAY`; preserve evidence and do not invoke again |
| `S-ARTIFACT` | zero exit with missing or invalid Artifact | `HANDLER_FAILURE_NO_ACK`; no trusted import, handoff or terminal |
| `S-RESULT-VALIDATE` | crash after durable result before validation/import | `SAFE_CONTINUE`; rerun skips provider and validates the same result |
| `S-EFFECT-INTENT` | crash after trusted local Git effect before handoff intent | `SAFE_CONTINUE`; revalidate the exact effect and persist one intent |
| `S-DUPLICATE` | identical input before provider start and after terminal completion | pre-start uses exact durable state; completed replay is idempotent; no repeated effect |
| `S-STATE-DRIFT` | corrupt checksum or stale/mismatched RunSpec/journal identity | deny before provider/mutation and require owner diagnosis; no guessed repair |
| `S-GIT-DRIFT` | trusted Git/workspace identity changes after review result and before terminal | `DENY_BEFORE_MUTATION`; terminal remains absent |

The fixture must not redefine Candidate outcome IDs. Where one row covers two observation points,
the machine object must carry explicit subcases and an expected result for each.

`S-AUTH-START` must include at least these machine-readable subcases:

1. prepared journal durable before RunStore authorization: no provider can start until exact
   authorization is committed;
2. RunStore authorization present but the bound journal missing/corrupt: this is unreachable through
   the supported writer API, but injected state yields `OWNER_DECISION_REQUIRED`, no provider start
   and no guessed journal repair;
3. authorization and prepared journal durable before launch intent: exact rerun may start once after
   revalidation;
4. launch intent durable before process-start/result observation: missing exact recoverable result
   evidence yields `AMBIGUOUS_NO_REPLAY`.

The experiment must keep `prepared` distinct from persisted launch intent. Once launch intent is
durable, missing exact recoverable result evidence remains ambiguous even if an OS start observation
was not written; the slice must not use the prepared-state recovery rule to close Candidate OQ-1.

## Status contract

For the normal path and every injected failure, the test must capture a canonical status object
containing at least run identity, observed phase/outcome, blocker owner/source, provider invocation
observation, terminal fact and exactly one `legal_next_action`.

The test snapshots state before and after every `status` call and proves byte-for-byte that status
made no local write. Unknown, corrupt, ambiguous and Git-drift states cannot be promoted to safe
continue.

## Measurement contract

The implementation report must compare the Python slice with the versioned RTS-001 baseline and
state unequal evidence plainly. At minimum record:

- logical authority domains and owners represented or excluded;
- persistent record families with per-run/per-invocation multiplicity and authority/intent/
  evidence/derived/cache classification;
- local files joined for each of the eight recovery decisions;
- normal commands and human decisions; support actions exposed only by faults;
- production nonblank/noncomment LOC for the experiment, fixture/test LOC and direct dependencies;
- platform CI gates and distribution prerequisites actually exercised;
- which remaining complexity belongs to language, compatibility, packaging, lifecycle or external
  truth;
- which current safety boundaries the slice does not yet cover.

Class/file/record count reduction is not itself a PASS. Every claimed simplification must retain
the fault outcome and owner boundary that the removed representation protected.

## Frozen model-writable scope

- `experiments/runtime-v2-python/README.md`
- `experiments/runtime-v2-python/runner.py`
- `tests/fixtures/runtime_v2_shared_slice_cases.json`
- `tests/fixtures/runtime_v2_shared_slice_provider.py`
- `tests/test_runtime_v2_rts020_python_slice.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-020-python-shared-slice.md`
- `.awf/artifacts/review-report-runtime-v2-rts-020-python-shared-slice.md`

The committed TaskCard is frozen owner intent and is not model-writable. If implementation exposes
a current production correctness gap, preserve the failing disposable evidence and stop changes
under this card; the owner must freeze a separate narrow remediation TaskCard before changing
production `src/`, `scripts/`, CLI, schemas or current state formats.

After implementation and compiled ReviewReport pass, owner closeout may add
`docs/tasks/runtime-v2-rts-020-python-shared-slice-implementation-report.md` and make gate-status
updates to the Runtime v2 plan, HANDOFF and ROADMAP. Those paths are outside the model-write scope.

## Out of scope

- Any modification to production `src/`, `scripts/`, schemas, CLI, facade, package entry points,
  current Runtime state formats, Agent Bus integration or CI workflow.
- Any live/retained repository, event, delivery, queue, listener, service, state root, payload,
  credential, ACK, provider, GitHub or remote Git operation.
- Manual ACK/requeue/recovery/redispatch, replacement delivery or historical payload read.
- SQLite implementation or selection; Rust, Go or native launcher work; a physical Coordinator;
  product-boundary ADR; contract Frozen promotion; migration, default, release or destructive work.
- Reusing the current production checkpoint/outbox/inbox graph as the experimental state design, or
  wrapping the current facade and calling the wrapper simpler.
- Claiming installed `awf` UX, native lifecycle, distribution, cross-host, real provider, transport,
  ACK, provenance, rework or business parity from this local PASS-only slice.

## Acceptance criteria

- [ ] Task ID equals the branch leaf and all state/repositories/identities are pytest-owned and fresh.
- [ ] One normal `run` command reaches terminal with exactly one implement and one review child;
      identical completed rerun produces no additional provider, Git or terminal effect.
- [ ] Immutable RunSpec drift fails closed; one RunStore writer and one InvocationJournal API own
      their respective facts without checkpoint/outbox/inbox duplicates.
- [ ] Artifact allowlist, report validation, no-remote workspace import and exact trusted local Git
      effect are real disposable operations.
- [ ] All eight fixture cases execute and match their normalized outcomes, sole legal next action
      and prohibited-effect assertions.
- [ ] `S-AUTH-START` proves the writer orders prepared journal before RunStore authorization,
      injected authorization-without-journal is owner-required/no-start, authorized prepared state
      starts once, and persisted launch intent without recoverable result is ambiguous/no-replay.
- [ ] `S-START-RESULT` proves an observed ambiguous start never invokes the provider again.
- [ ] `S-RESULT-VALIDATE` and `S-EFFECT-INTENT` prove recovery skips the completed provider and
      revalidates exact durable evidence.
- [ ] `S-STATE-DRIFT` and `S-GIT-DRIFT` preserve evidence and write no guessed repair/terminal.
- [ ] Status is byte-for-byte read-only for normal, terminal, failed, corrupt and ambiguous states.
- [ ] Stop is exact-slice-only and is reported as unequal lifecycle evidence.
- [ ] Machine-readable acceptance output and the ImplementationReport contain the complete baseline
      comparison and explicit synthetic/unequal boundaries.
- [ ] No new dependency or production/default/remote/live/retained/migration/release/destructive
      surface is added or used.
- [ ] Focused test, full pytest/Ruff, ordinary cross-platform CI and Binary Feasibility pass on the
      exact publication head.
- [ ] Independent TaskCard, implementation and final exact-head Reviewers return `PASS`.

## Verification

- Run the experiment normal path and all eight fault cases in one focused pytest module on CI.
- Run full repository pytest/Ruff and existing Candidate reference regressions.
- Validate the shared JSON fixture with duplicate-key rejection and resolve its outcome IDs against
  `docs/runtime-v2-semantic-contract.md`.
- Run changed-file compile checks, `git diff --check`, Artifact contract compilation and changed-path
  audit locally. Mac does not run pytest/Ruff.
- Independently review the frozen TaskCard before implementation, the implementation before
  publication, and the final exact PR head.

## Required output

- one removable Python experiment exposing the shared `run/status/stop` command protocol;
- one language-neutral eight-case fixture and one scripted no-model provider;
- one focused executable acceptance suite;
- compiled ImplementationReport and ReviewReport artifacts;
- a later owner-authored measurement/acceptance report.

<!-- awf-postflight
{
  "allowed_paths": [
    "experiments/runtime-v2-python/README.md",
    "experiments/runtime-v2-python/runner.py",
    "tests/fixtures/runtime_v2_shared_slice_cases.json",
    "tests/fixtures/runtime_v2_shared_slice_provider.py",
    "tests/test_runtime_v2_rts020_python_slice.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-020-python-shared-slice.md",
    ".awf/artifacts/review-report-runtime-v2-rts-020-python-shared-slice.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_v2_rts020_python_slice.py"],
    ["{python}", "-m", "pytest", "-q"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
