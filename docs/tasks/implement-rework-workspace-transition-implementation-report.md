# ImplementationReport: P0-5 Implement-to-Rework Workspace Transition

## Outcome

Trusted v3 rework now continues in the initial coder-owned durable model workspace. The runner
advances that workspace only after the implementation tree and trusted commit agree, records the
transition separately from immutable invocation identity, and restores it for rework only through
an exact same-run ledger/checkpoint/provenance/Git lineage.

## Production changes

- Recovery checkpoints accept an optional paired workspace-lineage delivery/checkpoint digest in
  immutable identity. Normal implement/reviewer checkpoints remain compatible and omit it.
- A stable Git-control digest excludes only HEAD and semantic index, the two fields intentionally
  changed by the trusted transition. Every other credential-free Git control file must remain
  exact before and after the transition.
- After exact model-tree import and trusted commit creation, the runner verifies commit parent and
  tree, fetches that one local commit object into the existing no-remote workspace, advances its
  detached HEAD, removes transient fetch/reflog state, requires a clean tree/no remotes, and stores
  the resulting manifest in the coder checkpoint.
- Fresh v3 rework finds exactly one authorized implement/coder event in the same RunLedger, binds
  the complete implement checkpoint digest into its own checkpoint, and requires completed
  outbox handoff, branch, current commit, verified PR tuple, imported tree, workspace path under the
  same state root, and exact post-transition manifest before the provider starts.
- Existing same-delivery recovery remains authoritative after a rework checkpoint exists, so a
  completed or ambiguous model call is never repeated. Existing control-plane route/stage/rework
  budget logic remains unchanged; Agent Bus carries no workspace path or new payload field.

## Proportional verification

- One real disposable Git fixture proves the trusted commit advances the same workspace while
  preserving the stable control digest, clean tree, exact commit/manifest, and no-remotes boundary.
- One synthetic implement -> review -> `REQUEST_CHANGES`/rework ledger fixture creates the complete
  implement checkpoint lineage, restores the exact same workspace, and proves Git-control drift
  stops before the representative rework provider callback.
- Existing same-delivery recovery matrix tests retain their exactly-once model policy across every
  checkpoint boundary; existing control-plane tests retain stage, duplicate, and one-rework budget
  authority.
- Local Mac checks are limited to changed-file `compileall` and `git diff --check`; GitHub CI owns
  Pytest, Ruff, and cross-platform verification.

## Compatibility and rollback

- Agent Bus routes/payloads, native listener templates, delivery hashes, provenance tuples,
  business outbox/inbox/ACK ordering, and Finding ACK remain unchanged.
- v1/v2 compatibility paths retain fresh-workspace behavior because only trusted v3 routes have
  durable PR checkpoints capable of proving cross-delivery lineage.
- Rollback is a clean package revert before any new live run. No retained delivery, payload,
  credential, or remote business state is used by this package or its tests.

## Evidence

- Base: `main@c39383e37733d8a0e96b4810ea437be7e2ddd548`
- Branch: `codex/implement-rework-transition`
- Local static checks: changed-file `compileall` and `git diff --check` passed.
- Exact PR head, CI, independent review, fresh parallel-overlap/mergeability gate, merge, and
  post-merge main CI remain auditable in the package PR.
