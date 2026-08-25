# RC.2 Phase 1E — Exact Local Deinitialization Implementation Report

## Outcome

`awf deinit --repo <worktree>` now performs a fail-closed removal of one platform-local
`awf.machine-config.v1` binding. It accepts only the deterministic current-worktree binding and
AWF-generated profile/workspace paths derived from that binding. It never reads or migrates a
repository-local legacy machine configuration.

Before any mutation it requires every selected listener to be stopped with known lifecycle
identity, accepts only a current or absent native installation, and requires every generated role
workspace to exist and have an empty Git porcelain status. It then uninstalls only current exact
listeners, re-observes native-install absence, removes the exact authoring profiles and clean
generated workspaces, and finally removes the platform binding. A failed uninstall leaves the
binding and all not-yet-cleaned local files in place for inspection/retry.

The command retains committed `.awf/project.yaml`, Plan and Workflow state, checkpoints,
outbox/inbox, logs, artifacts, and failed evidence. Native `node.uninstall` now removes its exact
installed-profile snapshot only after the manager uninstall succeeds; it does not delete snapshots
after a failed manager operation.

## Verification

- Focused facade/CLI/node-service suite: `119 passed`.
- Complete local suite: `987 passed, 5 skipped`.
- Ruff check/format and `git diff --check`: PASS.
- Independent L2 review initially returned BLOCK for native-definition absence, profile alias, and
  partial-cleanup regression coverage. The bounded repairs added each missing fail-closed guard and
  regression; final focused re-review returned PASS.

## Exclusions

Disposable acceptance lifecycle manifests and automatic closeout, Windows zero-console periodic
reconciliation, real-machine acceptance, provider behavior, and Agent Bus operations remain
separate frozen boundaries.
