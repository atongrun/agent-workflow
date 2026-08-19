# RTS-001 Runtime v2 Semantic Contract Draft — Implementation Report

Status: **TaskCard PASS; PR CI gate green**

## 1. Outcome and basis

RTS-001 extracted the current Python operations Runtime into a language-neutral Draft without
changing production behavior. The evidence basis is
`main@0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2`; execution is on
`codex/runtime-v2-rts-001`. Owner-authored plan/Review inputs were first preserved without Runtime
source changes in evidence commit `6556ea6`.

The work is documentation/static only. No provider/model was invoked, no Agent Bus payload or
retained event was read, and no queue, service, remote repository, release, migration, lifecycle,
default, production, or destructive action was performed.

## 2. Delivered artifacts

- `docs/runtime-v2-semantic-contract.md` — `awf.semantic-contract.v1`, maturity `Draft`;
- `docs/testing/runtime-v2-fault-matrix.md` — human-readable coverage and current-gap index;
- `docs/testing/runtime-v2-fault-matrix.json` — 39 machine-readable fault cases;
- `docs/testing/runtime-v2-authority-record-inventory.md` — six authority domains, 28 persistent
  record families, derived views, recovery joins, multiplicity, and external truth boundaries;
- `docs/tasks/runtime-v2-semantic-contract-draft.md` — frozen TaskCard and postflight scope;
- this implementation report.

The owner-provided 2026-08-18 Review remains byte-for-byte untouched during RTS-001. Its observed
SHA-256 is `29e8cb586dc5a8014e702bc4859e5f4938e43781649d801930d80690cafe89f3`.

## 3. Decisions captured, not implementation choices

- The proposed `prepared / started / completed / failed / ambiguous` invocation enum is rejected
  as a complete model. Authorization, process observation, provider result, Artifact validation,
  trusted local effects, Git/GitHub provenance, outbox, inbox, handler outcome, transport ACK and
  Workflow terminal remain orthogonal facts.
- RunLedger is the current Workflow transition authority. Recovery checkpoint, outbox, inbox,
  lifecycle identity, Artifact evidence and external systems keep distinct owners.
- Agent Bus ACK, provider process/result, Git/GitHub and OS-manager observations remain external
  truth; a local store cannot make those effects atomic.
- Automatic recovery is limited to exact same-identity paths. Ambiguous provider state,
  conflicting terminal, incompatible provenance/state, historical delivery and destructive
  migration remain owner-only decisions.
- Runtime v2 language, store, physical Coordinator topology, CLI and migration remain hypotheses
  for later evidence gates.

## 4. Current reference gaps preserved as faults

The Draft does not hide current Python gaps:

1. `rework -> review` is not authorized by the current gate, and the default per-stage budget does
   not permit the two reviews required by RTS-011 (`CG-1`, `F-AUTH-004`).
2. The handler-rebuilt context packet appears to omit the compiled RunContract SHA that `awf run`
   bound into the initial packet (`CG-2`, `F-RUN-003`).
3. Durable checkpoint coverage differs across compatibility routes/providers.
4. Run authorization may become durable before a worker checkpoint exists; the consumed attempt
   cannot be erased after a later failure.
5. Some provider-result/import write windows lack exact reconciliation fixtures.
6. Terminal causal lineage is a multi-record join, not one atomic transition.
7. Shipped handlers do not produce terminal `failed`, `cancelled`, or `rejected` transitions.
8. Local durable worker state has no safe cross-host adoption protocol.

These gaps are evidence for scoped correctness TaskCards. RTS-001 does not fix or waive them.

## 5. Verification evidence

Local validation is intentionally documentation/static only under the TaskCard and Mac execution
policy.

Machine-readable validation:

```text
python3 -m json.tool docs/testing/runtime-v2-fault-matrix.json
PASS

custom standard-library validation
matrix_ok cases=39 outcomes=11 evidence=23 duplicate_keys=0
```

The custom validation rejected duplicate object keys, required exact format/maturity, proved unique
case IDs, required a legal next action/prohibited actions/evidence for every case, and resolved all
expected outcomes and evidence IDs against the semantic contract.

Repository-relative path/link checks passed. `git diff --no-index --check /dev/null <file>` passed
for every untracked RTS-001 artifact; the final staged diff must rerun ordinary
`git diff --check` and changed-path audit before commit.

No pytest, Ruff, provider, queue, service, remote-node, release or migration command was run.

## 6. Changed-path audit

RTS-001-owned paths are limited to:

- `docs/runtime-v2-semantic-contract.md`;
- `docs/testing/runtime-v2-fault-matrix.md`;
- `docs/testing/runtime-v2-fault-matrix.json`;
- `docs/testing/runtime-v2-authority-record-inventory.md`;
- `docs/tasks/runtime-v2-semantic-contract-draft.md`;
- `docs/tasks/runtime-v2-semantic-contract-draft-implementation-report.md`;
- later gate-status updates to `docs/plans/runtime-v2-development-plan.md`, `HANDOFF.md`, and
  `ROADMAP.md` after independent PASS.

The owner-provided Review and adversarial double review are evidence inputs, not modified RTS-001
outputs. They remain outside the TaskCard's mutable path set.

## 7. Independent review history

### Review 1 — `FAIL`

The independent Reviewer found one blocking issue: this implementation report did not yet exist,
so the required output and reviewer-evidence acceptance criterion could not be satisfied. It found
no unmapped known production fault boundary in the semantic/fault content. Its checks reported 39
unique cases, 11 outcomes, 23 resolved evidence IDs, valid JSON, valid repository-relative paths,
and no trailing whitespace in the untracked RTS documents.

Remediation: add this report with deliverables, exact validation evidence, changed-path audit,
limitations and preserved review history, then rerun independent review against the complete
artifact set.

### Review 2 — `PASS`

After remediation, the independent Reviewer returned exact `PASS` with zero findings against the
complete artifact set and current source/test evidence. It independently confirmed:

- all required outputs are present;
- 39 unique JSON cases, 11 declared outcomes and 23 resolved evidence IDs;
- exact top-level keys, duplicate-key rejection, valid repository-relative links/paths and clean
  whitespace checks;
- the 2026-08-18 Review SHA matches the preserved value above;
- `CG-1`/`F-AUTH-004` and `CG-2`/`F-RUN-003` match current source;
- no unmapped known production fault boundary and no production/external mutation.

The Reviewer identified the TaskCard/plan/HANDOFF/ROADMAP edits after PASS as closeout bookkeeping,
not a remaining finding.

## 8. Limitations and next gate

- Maturity remains `Draft`; this is neither a production ABI nor migration authority.
- The matrix is descriptive/static. RTS-011 must convert the relevant boundaries into executable
  two-review/rework fault-injection evidence.
- Historical business PASS evidence predates final remediation and cannot satisfy RTS-010.
- No implementation language, store, Coordinator topology or product CLI decision has been made.

RTS-001 is closed at Draft maturity. The execution plan may advance to the first next TaskCard whose
entry criteria are satisfied. Production/default/release/migration/destructive actions remain
separately gated.

## 9. PR and CI closeout evidence

PR [#96](https://github.com/atongrun/agent-workflow/pull/96) targets `main@0ed7812`. Its exact reviewed
semantic TaskCard commit is `021e054`; the branch also carries this later evidence-only closeout.
The ordinary CI suite passed on the semantic commit: Ubuntu tests, Windows tests/recovery,
macOS runtime, and installed-wheel jobs on Ubuntu, Windows and macOS. Four of five native binary
matrix jobs also passed.

The remaining `native-macos-arm64` job failed in workflow run `32270007734` on all three bounded
attempts. Each attempt reached the unchanged `Build the three native candidates` step and failed
before evaluating this documentation diff with the same external response:

```text
httpx.HTTPStatusError: Client error '403 rate limit exceeded'
for url 'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest'
```

The final attempt is `run_attempt=3`, job `96126310333`, head
`021e05400b501c64e9e21b24a311d025dc5b329f`. The same Binary Feasibility workflow was green on
current `main@0ed7812` in run `32048522567`, and the other four target cells passed on this PR.
This was classified `EXTERNAL_BLOCKED`, not a Runtime/contract regression. The evidence-only closeout
commit `c9130a9` then triggered fresh runs `32271264491` (ordinary CI) and `32271264460` (Binary
Feasibility) without another manual retry. Both completed green: all five native target cells,
`aggregate-go-no-go-input`, the ordinary cross-platform tests/runtime jobs, and all three
installed-wheel jobs passed. The external block is therefore cleared while its three failed
attempts remain preserved above.

Legal next action: independently review the final evidence-only status update, require its exact
head CI to remain green, then merge PR #96. Do not modify the frozen RTS-001 scope or start RTS-010
live execution before repository integration closes.
