# TaskCard: P0-5 Implement-to-Rework Workspace Transition

## Task ID

AWF-USABILITY-P0-5

## Goal

Carry one coder-owned durable model workspace from a completed implementation through trusted
postflight, commit/push/PR, reviewer `REQUEST_CHANGES`, and the single authorized rework without
confusing expected trusted Git evolution with model-side identity drift.

## Frozen contract

- The initial coder delivery owns the durable model workspace. Agent Bus carries no new lineage,
  local workspace path, or Git metadata; the existing same-run ledger supplies the unique opaque
  implement delivery ID used to locate the coder checkpoint.
- The implementation checkpoint keeps its immutable invocation input unchanged and separately
  records the exact trusted transition from dispatched commit/tree to the committed implementation
  commit/tree plus the resulting credential-free workspace Git-manifest digest.
- Only trusted runner code may advance the no-remote workspace to the verified implementation
  commit after the imported tree and trusted commit agree. The transition must not add a persistent
  remote, reflog, hook, credential helper, or mutable source binding.
- Reviewer review/rework delivery payloads and transport semantics remain unchanged.
  `REQUEST_CHANGES` authorizes no workspace by itself.
- Rework resolves exactly one prior authorized implement/coder event from the same RunLedger and
  reuses its workspace only when that checkpoint is complete and matches branch/current PR
  tuple/current commit/imported tree plus the durable Git manifest. Missing or ambiguous lineage,
  or any disagreement, fails before provider invocation.
- Same-delivery recovery continues to replay checkpoint/outbox evidence and never invokes a
  completed or ambiguous model call again. Rework remains bounded by the existing RunLedger budget.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@c39383e37733d8a0e96b4810ea437be7e2ddd548`
- **Branch**: `codex/implement-rework-transition`
- **Prerequisite**: P0-4b PR #86, exact-head PASS and post-merge main CI `31856178174` green.
- **Primary files**: `scripts/awf_role.py`, focused role/control-plane tests, and narrow
  operator/runtime documentation.
- **Parallel boundary**: P1-1a exclusively owns `src/agent_workflow/node_service.py`,
  `scripts/awf_executor.py`, `tests/test_node_service.py`, and `tests/test_awf_executor.py`; this
  package must not modify them.

## Scope

- Resolve the unique prior implement delivery from the existing same-run ledger without changing
  Agent Bus payloads.
- Persist and validate the trusted implementation commit/tree/workspace-manifest transition.
- Restore the exact transitioned workspace for one authorized rework before its provider starts.
- Cover replay and representative lineage/Git mismatch fail-closed behavior with disposable local
  fixtures only.

## Out of scope

- Status/log/Feedback work, P1-1a files, facade work, Agent Bus transport changes, Phase B, Agent
  Host, DAGs, provider registries, or model routers.
- Any weakening of provenance, delivery hash, checkpoint, outbox, postflight, PR tuple,
  handler-success ACK, or business/Finding ACK separation.
- Any read, ACK, requeue, recovery, redispatch, reuse, or payload access for events 163, 166, 173,
  or any retained business event. Tests use synthetic repositories, event IDs, and deliveries.

## Verification level and budget

- **Level B, promoted to one Level C synthetic proof; target two new focused tests, maximum three.**
- One synthetic repository proof executes implement fixture -> trusted commit/transition fixture ->
  reviewer `REQUEST_CHANGES` fixture -> one rework fixture and records exactly one implement and one
  rework provider invocation.
- Replay of each completed delivery must not invoke its provider again.
- One table-driven lineage/current-commit/Git-manifest mismatch must fail before provider
  invocation; existing tests retain repository, branch, budget, duplicate, and PR-tuple invariants.
- Local Mac verification remains compile/static/diff only; GitHub CI owns Pytest, Ruff, and
  cross-platform execution.

## Acceptance criteria

- [ ] Initial immutable invocation identity remains unchanged while trusted Git evolution is stored
      as separately named checkpoint facts.
- [ ] The model workspace advances only after trusted imported-tree/commit checks and remains
      credential-free, no-remote, and exact-manifest bound.
- [ ] Reviewer and `REQUEST_CHANGES` payloads remain unchanged; lineage is recovered from the
      existing same-run ledger and checkpoint records.
- [ ] Rework restores the same workspace only after exact unique-ledger/checkpoint/PR/current-
      commit/Git validation and otherwise fails before provider invocation.
- [ ] Synthetic implement -> review -> one rework invokes providers exactly once each; completed
      same-delivery replay invokes neither again.
- [ ] Two or three focused tests plus the full CI matrix pass; an independent reviewer approves the
      exact PR head before merge.
- [ ] Fresh pre-merge main/parallel-PR file comparison proves no P1-1a overlap.

## Required output

- `docs/tasks/implement-rework-workspace-transition-implementation-report.md`
- Minimal code/docs/tests, Lore commit series, PR, green CI, exact-head independent review, fresh
  mergeability/parallel-overlap gate, merge, post-merge main/CI proof, and short-branch cleanup.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/implement-rework-workspace-transition.md",
    "docs/tasks/implement-rework-workspace-transition-implementation-report.md",
    "docs/runtime-execution-architecture.md",
    "HANDOFF.md",
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "scripts/awf_role.py",
    "tests/test_awf_role.py",
    "tests/test_control_plane.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_awf_role.py", "tests/test_control_plane.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
