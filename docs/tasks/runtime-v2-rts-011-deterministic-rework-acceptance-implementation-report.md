# RTS-011 Disposable Deterministic Rework Acceptance Report

Status: **PASS**

Date: 2026-08-20

TaskCard: [`runtime-v2-rts-011-deterministic-rework-acceptance.md`](runtime-v2-rts-011-deterministic-rework-acceptance.md)

Executable acceptance head: `2868486263aaf35814719fb9ab085a5787359408`

Pull request: [#101](https://github.com/atongrun/agent-workflow/pull/101)

## Result

The current Python reference completed the bounded RTS-011 scenario in one disposable pytest-owned
run:

```text
implement -> review REQUEST_CHANGES -> rework -> review PASS -> terminal completed
```

The scripted provider started exactly four real child processes: one implement, one rework and two
reviews. Both review inputs remained at `attempt=1`; the final ledger recorded `attempts=4`,
`reworks=1`, and stage attempts `implement=1/review=2/rework=1`. A second review input at
`attempt=2` remained illegal.

This is the deterministic reference acceptance required by RTS-011. It is not a real provider,
GitHub provenance, Agent Bus protocol, cross-host, or business acceptance.

## Joined production paths

The fixture calls the shipped Python reference rather than implementing a test-only Workflow:

- `RunLedger.initialize`, `pre_invocation_gate`, `recover`, and terminal persistence;
- recovery-checkpoint creation, monotonic phase advancement and `recovery_model_policy`;
- durable no-remote model workspace preparation, trusted delta import, commit transition and exact
  implement-to-rework checkpoint/workspace/commit/PR/Git-manifest restoration;
- `recover_completed_model_checkpoint` from a durable `opencode_start -> opencode_exit(rc=0)` log
  after a fresh `RunEvidence` instance is created for the same event and state root;
- production ReviewReport parsing/normalization for `REQUEST_CHANGES` and `PASS`;
- production outbox preparation/delivery, inbox completion/dedupe and architect terminal handler.

The rework provider count remains one across recovery. A drifted lineage digest fails before the
provider starts. A same-delivery duplicate after rework authorization changes no provider count and
creates no checkpoint, outbox, or inbox identity. Identical terminal replay leaves the ledger
sequence unchanged.

## Ordering evidence

For each of implement, review 1, rework and review 2, the test instruments the production durable
primitives and validates:

```text
outbox_prepared
  -> synthetic_send
  -> outbox_sent
  -> source inbox completed
  -> handler success observed
  -> synthetic ACK observed
```

For the terminal consumer it validates:

```text
terminal ledger + summary durable
  -> architect inbox completed
  -> handler success observed
  -> synthetic ACK observed
```

The ACK observer is deliberately synthetic. Agent Bus still owns real delivery/retry/ACK truth;
this fixture proves only the Workflow-side ordering required before the external success ACK.

## Synthetic and external boundaries

Synthetic:

- provider intelligence and generated report content;
- PR number and GitHub/API/CI provenance inside the disposable run;
- transport send and ACK observation;
- event IDs and timestamps.

Real but disposable/local:

- child subprocess starts and exits;
- Git repositories, commits, indexes and no-remote model workspaces under pytest temporary roots;
- RunLedger, checkpoint, outbox, inbox, RunEvidence and summary files under a temporary canonical
  state root;
- production parser, lineage, recovery, persistence and terminal functions.

No live/retained event, queue, listener, provider credential, GitHub write, remote Git write,
service, production/default/release/migration or destructive surface was read or changed.

## Review and CI evidence

The frozen TaskCard passed independent review before implementation. Implementation Review 1 first
returned `REQUEST_CHANGES`: the fixture used the nonexistent action `reviewer.rework`. The fix used
the production route name `reviewer.request_changes`, corrected the deterministic-failure schema,
kept reviewer imports in separate disposable trusted clones, and added explicit duplicate identity
assertions. The same independent Reviewer then returned `PASS` with zero findings.

An independent Candidate-promotion Reviewer then examined the owner closeout diff, verified the
live PR head and both Actions runs, parsed the matrix with duplicate-key rejection, resolved all 39
case outcomes and evidence IDs, and returned `PASS` with zero findings. It confirmed CG-1/CG-2 are
retained as closed regressions, CG-3 through CG-8 and all open questions remain visible, and
RTS-020 is only the next eligible disposable comparison slice.

The first ordinary CI run `32300975839` failed only `ruff format --check` on two expressions. The
exact formatter diff was applied in `2868486`; no behavior changed. On that exact executable head:

- ordinary CI run [`32301184219`](https://github.com/atongrun/agent-workflow/actions/runs/32301184219)
  passed every job;
- Ubuntu Python 3.11 collected 654 tests: `649 passed, 5 skipped`; Ruff check passed and all 186
  files were formatted;
- Windows Python 3.12 completed `643 passed, 11 skipped`, then the PowerShell and Git Bash executor
  suites each passed 23/23; Ruff check and format passed;
- installed-wheel Ubuntu, Windows and macOS jobs passed; macOS runtime passed;
- Binary Feasibility run
  [`32301184171`](https://github.com/atongrun/agent-workflow/actions/runs/32301184171)
  passed Linux x86_64/arm64, macOS x86_64/arm64, Windows x86_64 and aggregate.

## Contract correction

RTS-011 closes former gap `CG-1` / `F-AUTH-004`: an authorized rework unlocks exactly one
additional review-stage slot without raising the per-delivery attempt limit, and the complete
two-review loop now has executable restart/lineage/handoff/terminal evidence.

No new fundamental safety invariant was discovered. The acceptance reinforces existing separate
facts: authorization, provider process evidence, trusted local effects, downstream intent, inbox,
terminal and external ACK are not one state. The remaining documented gaps and open questions are
not waived; in particular authorization-before-checkpoint, compatibility-route recovery, local
effect reconciliation, terminal causal joins, reserved terminal labels and cross-host adoption
remain later-phase inputs.
