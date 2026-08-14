# P0-3 Durable Profile Identity and Exact Stop Implementation Report

## Outcome

Managed lifecycle identity now belongs to an installed credential-free profile snapshot, not the
continued existence of its authoring file. Native definitions, install records, desired state,
process evidence, and listener leases converge on the durable snapshot. Exact source/name registry
bindings let ordinary lifecycle commands resolve it after the source moves or disappears.

Exact stop remains fail closed. The existing manager identifier, definition digest, installed
profile path/digest, role, repository, state-root binding, launch identity, live PID/lease, and
Windows process-creation identity gates remain conjunctive. No PID-only, role-only, process-name,
queue, or model fallback was introduced.

## Changed files and simplifications

- `src/agent_workflow/node.py` adds one small content-addressed snapshot and exact registry path.
  Managed install stages that identity; all later lifecycle commands share one installed resolver.
  Registry aliases are explicit and removed by exact binding rather than filesystem scanning.
- Managed upgrade accepts new authoring contents only when name, role, repository, state root, and
  lifecycle ownership are unchanged. Identity replacement is deliberately an uninstall/install.
- `src/agent_workflow/node_service.py` records both original-source provenance and installed
  snapshot identity while rendering every manager action from the installed profile.
- Three focused tests cover the costly boundaries: delete the temporary authoring file and prove
  installed status/exact stop, then corrupt the installed process identity and prove no Windows,
  systemd, or launchd manager command is issued.
- README, lifecycle architecture, CHANGELOG, HANDOFF, and the frozen TaskCard describe the same
  runtime/authoring split. No new dependency, schema, manager, daemon, or migration layer was added.

## Verification

Allowed local Mac gates:

- Python compilation/AST parsing of changed Python modules and the focused test file — passed.
- `git diff --check` and TaskCard allowed-path inspection — passed.
- Static review confirmed definitions receive the installed snapshot and the wrong-identity test
  observes zero manager signals.
- Independent pre-merge review found that systemd/launchd previously signaled their exact manager
  before checking process/lease identity. The shared exact-listener gate now runs first for stop,
  restart, upgrade-stop, and uninstall; a table-driven regression proves zero native calls on
  drift.

Per the frozen Level B contract, local Pytest, Ruff, Rust, and platform service managers were not
run. GitHub CI owns the full suite, format/lint gates, and installed-wheel platform matrix. Final
exact-head CI, independent review, mergeability, and post-merge evidence are recorded on the PR.

## Remaining risks

- Pre-P0-3 managed definitions do not silently migrate. They report stale and require the explicit
  upgrade path so a missing legacy authoring profile cannot be guessed or rebound.
- Content-addressed snapshots are immutable by identity: any on-disk mutation changes validation or
  digest evidence and fails closed. The package does not add OS-specific ACL management for these
  credential-free files.
- Fresh post-SSH platform lifecycle proof is reserved for final milestone acceptance; this package
  reuses the existing native CI matrix and changes only the profile path fed to each adapter.
