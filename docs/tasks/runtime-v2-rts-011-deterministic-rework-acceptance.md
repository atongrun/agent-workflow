# TaskCard: RTS-011 Disposable Deterministic Rework Acceptance

## Task ID

runtime-v2-rts-011-deterministic-rework-acceptance

## Goal

Prove that the current Python reference completes the full bounded RTS-011 loop with fresh
disposable state and scripted no-model providers:

```text
implement -> review REQUEST_CHANGES -> rework -> review PASS -> terminal
```

This is an acceptance fixture, not production functionality. It must join the already-tested
control-plane gate to the real checkpoint, outbox, inbox, local Git/workspace-lineage and terminal
code paths in one auditable scenario. It must not create a parallel Workflow state machine merely
to make the test pass.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@463c195c1404331e690c99a0865debb21e0b67c1`
- **Task branch**: `codex/runtime-v2-rts-011-deterministic-rework-acceptance`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 1 / RTS-011
- **Prerequisite**: PR #100 / review-loop gate integrated at the base above
- **Contract faults**: `CG-1`, `F-AUTH-004`, and the restart/outbox/terminal fault families named
  by the Runtime v2 fault matrix

RTS-010 is accepted. The source prerequisite now permits one authorized rework to unlock exactly
one follow-up review while both review inputs remain at `attempt=1`. Repository truth identifies
this disposable acceptance as the next active gate.

## Fresh isolated identities

The fixture must create all state beneath pytest-owned temporary directories and use identities
unique to this TaskCard:

- disposable local Git repository and no-remote durable model workspace;
- disposable canonical state root;
- run ID `task-runtime-v2-rts-011-deterministic-rework-acceptance`;
- branch `codex/runtime-v2-rts-011-deterministic-rework-acceptance`;
- distinct synthetic event, source-event, delivery and payload-hash identities for implement,
  review 1, rework, review 2 and terminal;
- one synthetic PR provenance tuple bound to the disposable local commits;
- one isolated scripted-provider counter/result file;
- one isolated deterministic transport/ACK observer.

No identity, file, repository, queue, listener, credential or payload from a retained or live run
may be read, reused or operated.

## Real and synthetic boundary

Real in this acceptance:

- `RunLedger` authorization, transition counters, context packet and terminal write;
- production recovery-checkpoint validation and monotonic phase transitions;
- production outbox preparation/delivery state and inbox completion/dedupe;
- real child subprocess starts/exits for all four scripted provider invocations;
- real disposable local Git commits, durable no-remote model workspace, manifest hashing and exact
  implement-to-rework workspace-lineage restoration;
- production ReviewReport parsing/normalization and the role-handler ordering being asserted.

Synthetic and explicitly not a production claim:

- provider intelligence and report content;
- GitHub PR/API/CI observations and the PR number in the provenance tuple;
- Agent Bus delivery and ACK. A deterministic external observer may accept the production
  `send_event` boundary and record ACK only after handler success. This proves Workflow ordering,
  not Agent Bus protocol compatibility or a real transport ACK;
- event timestamps and identifiers.

The acceptance artifact must label every synthetic boundary. It may not call synthetic ACK a real
Agent Bus ACK, and it may not infer external GitHub or provider truth from local files.

## Frozen semantics

1. The provider subprocess counter ends at exactly implement=1, rework=1, review=2, total=4.
2. Review 1 emits a valid normalized `REQUEST_CHANGES` report with deterministic failure evidence,
   routes exactly one rework intent and does not terminalize the run.
3. A same-delivery duplicate/redelivery before the rework provider starts is rejected/replayed by
   the production durable gates. It changes no checkpoint/outbox/inbox identity and starts no
   additional provider.
4. Rework binds the unique prior authorized implement delivery, its `outbox_sent` checkpoint
   digest, durable workspace, trusted commit, synthetic exact PR tuple, imported tree and trusted
   Git manifest. A drifted lineage is denied before provider start.
5. The rework provider starts once and leaves a durable successful process result while its
   checkpoint is `model_started`. A fresh handler/evidence object for the same event and state root
   recovers that result to `model_completed` and continues without a second subprocess start.
6. Review 2 is a distinct delivery at input `attempt=1`, emits a valid normalized `PASS`, routes
   exactly one ready intent and permits terminal completion. Input attempt 2 remains illegal.
7. Final ledger counters are exactly attempts=4, reworks=1, stage attempts implement=1/review=2/
   rework=1, and terminal state completed/reason review_passed.
8. Every outgoing intent is durable as `outbox_prepared` before the synthetic send, becomes
   `outbox_sent` before source inbox completion, and handler success is observed before synthetic
   ACK. Duplicate completion is idempotent and conflicting reuse fails closed.
9. Terminal ledger and summary are durable before architect inbox completion and handler success;
   the synthetic terminal ACK is observed only afterward. Terminal replay starts no provider and
   does not advance ledger sequence.
10. The test instruments production role-handler/primitives for the ordering under assertion.
    Direct primitive calls are permitted for disposable fixture setup, but the acceptance may not
    substitute a test-only transition/checkpoint/outbox/inbox/terminal implementation.
11. A machine-readable in-test acceptance record names the identities, subprocess counts, ordered
    effects, terminal facts and synthetic boundaries and validates itself before the test passes.

## Frozen model-writable scope

- `tests/test_runtime_v2_rts011_acceptance.py`
- `tests/fixtures/runtime_v2_scripted_provider.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-011-deterministic-rework-acceptance.md`
- `.awf/artifacts/review-report-runtime-v2-rts-011-deterministic-rework-acceptance.md`

The committed TaskCard is frozen owner intent and is not model-writable. If this acceptance exposes
a production defect, preserve the first failing evidence and stop implementation under this card;
the owner must freeze a separate narrow remediation TaskCard before production source changes.

After the acceptance and compiled ReviewReport pass, the owner may add
`docs/tasks/runtime-v2-rts-011-deterministic-rework-acceptance-implementation-report.md` and make
gate-status-only updates to `docs/runtime-v2-semantic-contract.md`,
`docs/testing/runtime-v2-fault-matrix.md`, `docs/plans/runtime-v2-development-plan.md`,
`HANDOFF.md`, and `ROADMAP.md`. Those owner closeout paths are outside the model-write allowlist.

## Out of scope

- Production or retained repository, provider, event, delivery, queue, listener, service, state
  root, credential, payload or ACK access.
- A real provider call, GitHub write, remote Git write, Agent Bus process, network connection,
  native service, release, default switch, migration or destructive cleanup.
- Manual ACK, requeue, redispatch, replacement delivery, historical read or ambiguous recovery.
- Runtime source changes, attempt/rework-budget changes, route/payload/schema changes, a new store,
  Coordinator, scheduler, provider abstraction, dependency or CI workflow.
- Claiming a real-business, real-provider, cross-host or real-Agent-Bus acceptance.
- Beginning Phase 2 before the RTS-011 closeout and semantic-contract Candidate update pass.

## Acceptance criteria

- [ ] Fresh disposable identities and the real/synthetic boundary are explicit and self-validated.
- [ ] Exactly four real scripted-provider subprocess starts/exits occur: 1 implement, 1 rework and
      2 reviews.
- [ ] One production-ledger sequence reaches implement/review/rework/review with both reviews at
      input `attempt=1` and exact attempts/reworks/stage counters.
- [ ] Review 1 is normalized `REQUEST_CHANGES`; review 2 is normalized `PASS`; their durable routes
      are rework then ready with no premature terminal.
- [ ] Same-delivery duplicate/redelivery before rework does not invoke a provider or change durable
      input identity.
- [ ] Exact prior implement delivery/workspace/commit/synthetic PR/checkpoint/Git-manifest lineage
      is restored for rework; drift denies before provider start.
- [ ] Restart after the durable successful rework provider result resumes the same checkpoint and
      does not invoke the provider again.
- [ ] Production outbox/inbox and terminal paths prove the required ordering; synthetic ACKs occur
      only after handler success and remain labeled synthetic.
- [ ] Terminal replay is idempotent and starts no provider.
- [ ] The focused test, full pytest/Ruff suite, ordinary cross-platform CI and Binary Feasibility
      pass on the exact publication head.
- [ ] Independent implementation Reviewer and final exact-head Reviewer return `PASS`.
- [ ] No live/external Runtime state, network, credential, production/default/release/migration or
      retained delivery is read or changed.

## Verification

- Run the focused acceptance test and its scripted provider on GitHub CI.
- Run the full repository pytest/Ruff suite and existing control-plane/recovery regressions.
- Run changed-file `compileall`, `git diff --check`, Artifact contract compilation and changed-path
  audit locally; Mac does not run pytest/Ruff.
- Independently review the frozen TaskCard before implementation, the implementation before
  publication, and the exact PR head after all closeout evidence is committed.

## Required output

- one focused executable acceptance fixture using the existing Python reference boundaries;
- one no-model scripted-provider child executable;
- compiled ImplementationReport and ReviewReport artifacts;
- a later owner-authored credential-free acceptance implementation report;
- gate-status-only semantic contract/fault matrix/plan/HANDOFF/ROADMAP updates after pass.

<!-- awf-postflight
{
  "allowed_paths": [
    "tests/test_runtime_v2_rts011_acceptance.py",
    "tests/fixtures/runtime_v2_scripted_provider.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-011-deterministic-rework-acceptance.md",
    ".awf/artifacts/review-report-runtime-v2-rts-011-deterministic-rework-acceptance.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_v2_rts011_acceptance.py"],
    ["{python}", "-m", "pytest", "-q"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
