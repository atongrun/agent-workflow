# RC.2 Phase 1F Implementation Report

## Result

PASS. The disposable acceptance lifecycle now freezes a credential-free manifest before lifecycle
mutation and closes only exact run-owned profile, manager and generated-workspace identities.

## Delivered boundary

- The manifest records canonical authoring and deterministic installed-snapshot identities, profile
  digest, workspace, native manager and manager ID.
- Closeout writes an immutable `FROZEN` evidence record before validation or mutation, then writes a
  separate immutable `CLOSED` record only after exact stop, uninstall, registry/snapshot absence and
  workspace removal are observed.
- Unknown, stale, symbolic, noncanonical, duplicate, dirty or active identities fail closed as
  `CLEANUP_BLOCKED`; no wildcard lifecycle or workspace cleanup is used.
- Managed profiles preserve source-symlink provenance so a symbolic authoring path cannot enter an
  acceptance manifest.

## Verification

- Focused lifecycle/facade/node suite: `116 passed, 1 skipped`.
- Independent L3 lifecycle review: `PASS` after two repair rounds.
- Ruff check, Ruff format check and `git diff --check`: PASS.
- Candidate full suite: `990 passed, 5 skipped`.

## Preserved boundaries

No Agent Bus events, ACK/replay operations, credentials, PlanRun state, release/tag publication,
human deinit behavior or Windows zero-popup behavior changed. Logs, workflow state, outbox/inbox
and retained failure evidence remain outside cleanup.
