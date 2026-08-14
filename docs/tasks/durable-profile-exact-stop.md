# TaskCard: P0-3 Durable Profile Identity and Exact Stop

## Goal

Make every managed node installation own a credential-free immutable profile snapshot in the
durable application configuration directory. Native service definitions and subsequent lifecycle
commands must use that installed identity, so moving or deleting the authoring profile cannot make
safe status or exact stop impossible.

## Frozen identity contract

- `awf node install` validates the authoring profile, atomically writes one immutable snapshot
  beneath the platform AWF configuration directory, and records its digest, original source,
  installed snapshot path, and native definition digest.
- Native launchd, systemd, and Task Scheduler definitions reference only the installed snapshot.
- Managed `start`, `status`, `logs`, `stop`, `restart`, `upgrade`, `uninstall`, and supervisor
  reconcile resolve the current installed snapshot. They do not require the original authoring
  file to remain present.
- Resolution accepts only an exact installed registry binding for the requested source or profile
  name. A missing, ambiguous, malformed, moved-without-binding, or digest-mismatched registry fails
  closed and names a legal reinstall/upgrade action; it is never repaired by scanning arbitrary
  files.
- `upgrade` preserves the installed identity when no new authoring profile is available. When a
  present authoring profile is intentionally supplied, it may create a new immutable snapshot only
  after the old installed identity has passed the exact stop/upgrade-target gate.
- Exact stop remains conjunctive: manager identifier, installed profile path and digest, role,
  repository, state-root binding, launch identity, process PID/creation identity where supported,
  and live listener lease must agree. No PID-only, role-only, process-name, or broad kill fallback
  is allowed.

## Scope

- Add a small installed-profile registry/snapshot helper using the existing atomic-write and
  schema/semantic validation paths.
- Bind install records, desired state, process/lease evidence, manager definitions, and lifecycle
  actions to the installed snapshot identity.
- Preserve legacy session profiles and pre-P0-3 managed installations through an explicit
  fail-closed compatibility/upgrade diagnosis; do not silently rewrite native definitions.
- Surface fixed-role contention with incumbent profile identity and the one legal exact stop/drain
  action, without secrets.
- Update lifecycle architecture, README, CHANGELOG, HANDOFF, and an ImplementationReport.

## Out of scope

- Contract compiler, manifest-class UX, implement-to-rework, causal status redesign, facade,
  structured Agent Bus handler contract, binary work, Phase B, Agent Host, DAG, provider registry,
  or model router.
- Any Agent Bus Core behavior or weakening of provenance, delivery-hash, checkpoint, business
  outbox, Feedback Outbox, postflight, PR tuple, handler-success ACK, or business/Finding ACK
  separation.
- Any read, ACK, requeue, recovery, redispatch, reuse, or payload access for events 163, 166, 173,
  or any other preserved business delivery. Verification uses temporary files and fake managers.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@4fad8ea1e89f85da1221baa059cbf5916e81702c`
- **Branch**: `codex/durable-profile-exact-stop`
- **Primary files**: `src/agent_workflow/node.py`, `src/agent_workflow/node_service.py`, existing
  node/service tests, installed-wheel verification, lifecycle documentation.
- **Existing invariants**: P0-1 canonical state-root binding and P0-2 truthful lifecycle facts are
  prerequisites and must remain unchanged in meaning.

## Verification level and budget

- **Level B; target two new focused tests, maximum three.**
- Test 1 installs a managed profile from a temporary authoring path, proves the rendered native
  definition and install record reference the durable snapshot, deletes the authoring file, then
  proves installed resolution plus status/exact stop through the snapshot.
- Test 2 mutates the highest-cost identity signal (installed snapshot digest or process-creation /
  launch binding) and proves stop refuses before any manager signal or broad kill.
- Extend existing adapter rendering/installed-wheel assertions only where their production output
  changes. Do not add one test per manager or identity field.

## Baseline metrics

- User-authored objects: one node profile; target remains one. The installed snapshot and registry
  are generated and credential-free.
- Supported managed path remains explicit `install` then `start`; no new human choice or flag.
- Current failure point: after a temporary authoring profile disappears, CLI profile loading fails
  before installed status/stop can prove the manager/process/lease identity. Target: resolve the
  immutable installed snapshot locally with zero Bus/model mutation.
- Elapsed time: not measured; this is not the fresh-machine benchmark.
- Cross-platform behavior: shared registry/snapshot contract plus existing manager rendering
  matrix; no new per-OS test matrix unless adapter-specific production output changes.

## Acceptance criteria

- [ ] Install atomically creates a durable immutable credential-free profile snapshot and registry
      binding with original source, profile digest, and native definition digest.
- [ ] Every native definition references the installed snapshot, not the authoring path.
- [ ] Managed status, stop, restart, upgrade, uninstall, and reconcile remain usable after the
      authoring profile is deleted or moved through an exact installed binding.
- [ ] Exact stop still requires every existing manager/profile/role/repo/state-root/launch/process/
      lease identity signal; wrong identity refuses without a manager signal or broad kill.
- [ ] Fixed-role contention identifies the incumbent credential-free profile binding and legal
      exact stop/drain action.
- [ ] Legacy/session behavior remains explicit and fail closed; no silent state or definition
      migration occurs.
- [ ] Two focused tests (at most three) plus existing coverage pass in GitHub CI.
- [ ] Independent review approves the exact PR head before merge.

## Verification

Local Mac: static inspection, changed-file AST/compile checks, JSON parsing where applicable, and
`git diff --check`; do not run Pytest, Ruff, Rust, or local platform service managers. GitHub CI
owns the full suite and installed-wheel platform matrix.

## Required output

- `docs/tasks/durable-profile-exact-stop-implementation-report.md`
- Necessary lifecycle/HANDOFF/README/CHANGELOG updates, Lore commit series, PR, green CI,
  independent exact-head review, fresh mergeability gate, merge, and post-merge `main`/CI proof.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/durable-profile-exact-stop.md",
    "docs/tasks/durable-profile-exact-stop-implementation-report.md",
    "docs/runtime-node-lifecycle-architecture.md",
    "HANDOFF.md",
    "README.md",
    "CHANGELOG.md",
    "src/agent_workflow/node.py",
    "src/agent_workflow/node_service.py",
    "tests/test_node.py",
    "tests/test_node_service.py",
    "tests/verify_installed_wheel.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_node.py", "tests/test_node_service.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
