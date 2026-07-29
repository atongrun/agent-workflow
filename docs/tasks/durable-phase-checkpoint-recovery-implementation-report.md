# Durable Phase Checkpoint Recovery Implementation Report

## Outcome

The v3 trusted coder and reviewer now persist delivery-scoped recovery checkpoints outside the Git checkout.
The checkpoint is written immediately before model invocation and advances only after durable,
independently verifiable boundaries. A duplicate control-plane delivery first replays a prepared
outbox; when no outbox exists it resumes from the last trusted checkpoint instead of restarting the
model or rejecting every replay.

This closes the failure class exposed by proof events #102 and #103. The retained coder delivery
recovered from its trusted commit, reused PR #31, sent the reviewer handoff, and was ACKed without a
second coder invocation. The reviewer delivery then recovered the same completed reviewer process,
sent a validated `PASS` decision, and was ACKed without a second reviewer invocation. Architect
validated and ACKed the decision event. The duplicate, attempt, route, and terminal-state gates
remain intact.

## Durable phases

The checkpoint format is `awf.recovery-checkpoint.v1`. It binds the role, input delivery ID,
canonical input payload hash, source event ID, branch, source commit, and complete original
`awf.pr-provenance.v1` tuple.

Coder phases advance monotonically:

1. `model_not_started`
2. `model_started`
3. `model_completed`
4. `model_imported`
5. `commit_created`
6. `fork_sha_verified`
7. `pr_tuple_verified`
8. `outbox_prepared`
9. `outbox_sent`

An existing checkpoint with different input or provenance fails closed. A backward or skipped
transition fails closed. Repeating an already-recorded phase is allowed only when the supplied facts
are identical.

The reviewer uses the same model phases, then `pr_tuple_verified`, `outbox_prepared`, and
`outbox_sent`; coder-only commit and fork-publication phases are not part of its state graph.

## Recovery behavior

- A failure before `model_started` may retry normal pre-model work.
- `model_started` without `model_completed` is ambiguous. Replay never invokes the model again and
  requires a new explicitly authorized attempt rather than guessing whether the old process ran.
- `model_completed` retains the isolated no-remote workspace and reruns the trusted postflight.
- `model_imported` binds the verified Git tree. Replay restores only that tree to the trusted index.
- A crash between Git commit and checkpoint write is reconciled only when `HEAD^1` equals the frozen
  source commit and `HEAD^{tree}` equals the imported tree.
- `commit_created` requires the live trusted checkout to match both the recorded commit and tree.
- Fork recovery pushes without force, freshly verifies the fork SHA, and records that SHA before
  selecting a PR.
- PR creation and verification are separate from fork publication. Replay reuses or creates one PR,
  then verifies the complete upstream/base and fork/head tuple before recording it.
- A prepared or ambiguous outbox replays its exact payload. A successful replay advances the
  checkpoint to `outbox_sent` before the source handler can complete and be ACKed.
- Reviewer recovery binds the completed process to the same event and role, restores the durable
  no-remote workspace, hashes the exact ReviewReport, revalidates the complete PR tuple, and
  persists its verdict outbox before ACK.

All mismatch paths remain fail closed. Recovery never changes the original TaskCard input, source
commit, branch, repository identities, base tuple, delivery hash, or model choice.

## Legacy proof-event migration

Retained event #102 predates this checkpoint format. Its same-event recovery imported only the
strongest phases present in its append-only handler log, in order:

- successful postflight with a full verified tree ID;
- successful trusted commit with a full commit ID;
- the bounded `fork_push_or_pr_verification_failed` terminal reason.

Because the older combined push/PR boundary did not record a separate remote-verification phase,
the imported checkpoint stopped at `commit_created`. The live runner verified that the persisted
base was an ancestor of current upstream, repushed without force, freshly matched the fork SHA,
reused the one exact open PR, and verified its complete tuple before sending.

Reviewer event #103 also predates reviewer checkpoints. Recovery required an ordered reviewer
`opencode_start` followed by `opencode_exit` with rc=0 in the same event state directory. The
already-generated valid PASS report was atomically moved from the obsolete fixture filename to the
delivery's requested path without changing its bytes. Recovery imported and hashed that same
artifact; a guard proved the reviewer subprocess was not invoked again.

Missing, malformed, reordered, mismatched, cross-role, outside-state, or different-event evidence
is not importable and never permits a model restart.

## Regression coverage

Focused tests cover:

- monotonic checkpoint transitions and immutable provenance binding;
- tool failure followed by same-delivery replay with model invocation count fixed at one;
- exact PR create/verify failure followed by recovery from verified fork SHA without a second model;
- legacy postflight/commit/fork evidence import for the retained-event shape;
- reviewer process-crash, PR-verification failure, send failure, ambiguous invocation, report hash,
  and same-delivery replay paths;
- sent-outbox recovery advancing the checkpoint to `outbox_sent`;
- existing prepared/attempting/ambiguous/sent outbox replay and provenance-drift denial;
- unchanged legacy v1/v2 role behavior.

Current Mac evidence at `a737aed9d5830fd0f600d9a8fdfe5debc1e2e3eb`:

- focused reviewer/coder crash-recovery suites: passed;
- complete suite: `286 passed, 1 skipped`;
- Ruff check and format: passed;
- role/workflow/example validation: 6/6, 4/4, and 3/3 passed.

Fresh Windows Python 3.12 evidence at the exact same commit:

- focused recovery suite: `16 passed`;
- complete suite: `286 passed, 1 skipped`;
- Ruff check and format: passed (`80 files already formatted`).

Independent native review found four initial high-severity checkpoint defects, one later
role-binding defect, and one ambiguous-error-path defect. All were fixed and regression-tested;
the final review reported zero remaining findings. GitHub CI and the final PR are recorded after
publication rather than predeclared here.

## Mandatory next fix: one Python configuration loader

The production configuration path is still split: service wrappers source `dispatch.env`, and the
Windows path has historically depended on Git Bash parsing POSIX shell syntax. This is not an
acceptable long-term cross-platform contract.

After the P0 lifecycle proof, replace shell sourcing with one strict Python loader shared by
listener, dispatch, bootstrap, and service entry points. It must:

- parse one documented cross-platform format without invoking PowerShell or a shell;
- reject duplicate keys, interpolation, commands, malformed quoting, unknown critical fields, and
  insecure paths/permissions;
- validate platform paths and owner-only secret-file access;
- expose only variable names and categorical diagnostics, never credential values;
- have Mac, Linux, and Windows deterministic tests.

This item is mandatory and must not be dropped merely because the #102–#104 lifecycle closes.
