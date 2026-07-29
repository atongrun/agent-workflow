# Durable Phase Checkpoint Recovery Implementation Report

## Outcome

The v3 trusted coder now persists a delivery-scoped recovery checkpoint outside the Git checkout.
The checkpoint is written immediately before model invocation and advances only after durable,
independently verifiable boundaries. A duplicate control-plane delivery first replays a prepared
outbox; when no outbox exists it resumes from the last trusted checkpoint instead of restarting the
model or rejecting every replay.

This closes the failure class exposed by proof event #101 and provides a bounded migration path for
retained proof event #102. It does not weaken the control plane's duplicate, attempt, route, or
terminal-state gates.

## Durable phases

The checkpoint format is `awf.recovery-checkpoint.v1`. It binds the role, input delivery ID,
canonical input payload hash, source event ID, branch, source commit, and complete original
`awf.pr-provenance.v1` tuple.

Phases advance monotonically:

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

All mismatch paths remain fail closed. Recovery never changes the original TaskCard input, source
commit, branch, repository identities, base tuple, delivery hash, or model choice.

## Legacy proof-event migration

The retained event #102 predates this checkpoint format. Its same-event recovery may import a
checkpoint only when its append-only handler log contains, in order:

- successful postflight with a full verified tree ID;
- successful trusted commit with a full commit ID;
- freshly verified remote SHA equal to that commit;
- the bounded `fork_push_or_pr_verification_failed` terminal reason.

The imported checkpoint starts at `fork_sha_verified`. Live checkout tree/commit, fork SHA, and PR
tuple checks still run before any downstream send. Missing, malformed, reordered, mismatched, or
different-event evidence is not importable and never permits a model restart.

## Regression coverage

Focused tests cover:

- monotonic checkpoint transitions and immutable provenance binding;
- tool failure followed by same-delivery replay with model invocation count fixed at one;
- exact PR create/verify failure followed by recovery from verified fork SHA without a second model;
- legacy postflight/commit/fork evidence import for the retained-event shape;
- sent-outbox recovery advancing the checkpoint to `outbox_sent`;
- existing prepared/attempting/ambiguous/sent outbox replay and provenance-drift denial;
- unchanged legacy v1/v2 role behavior.

Current Mac evidence:

- focused recovery/outbox suite: `15 passed`;
- role suite: `226 passed, 1 skipped`;
- complete suite: `277 passed, 1 skipped`;
- Ruff check and format: passed;
- role/workflow/example validation: 6/6, 4/4, and 3/3 passed.

Full suite, Ruff, resource validation, Windows deterministic verification, independent review,
live event #102 recovery, GitHub CI, and PR evidence are recorded during closeout rather than
predeclared here.

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

This item is mandatory and must not be dropped merely because event #102 closes.
