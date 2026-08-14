# TaskCard: P0-2 Truthful Lifecycle State Model

## Goal

Replace the ambiguous node-doctor `status: ready` umbrella with orthogonal, machine-readable
`configured`, `installed`, `running`, `connected`, and `dispatch_capable` facts. Each command must
report only what it observed, preserve unknown/stale states, and name one legal next action.

## Frozen managed-start decision

Managed `start` **fails closed when the native installation is absent** and reports this exact
next action:

```text
awf node install --profile <resolved-profile-path>
```

`start` never installs implicitly and must check the native manager install record and definition
before writing desired state. This is the same contract for launchd, systemd, and Task Scheduler.
It is the smallest reversible choice: installation remains an explicit idempotent operation and
`start` cannot silently create or enable native service definitions.

## Scope

- Derive managed `installed` only from a current native-manager install record and matching
  definition; missing evidence is false and drifted/unreadable evidence is stale/unknown.
- Keep `running` bound to the existing profile/process/lease/launch-identity agreement.
- Treat Agent Bus connectivity as a bounded live observation, not installation or running proof.
- Report `dispatch_capable` as false/unknown unless the required current Fast/Deep Preflight proof
  is available. Doctor/status do not manufacture dispatch authority.
- Add the lifecycle facts and one legal next action to doctor JSON/human output and factual node
  status JSON/human output.
- Update lifecycle/readiness documentation, HANDOFF, and an implementation report.

## Out of scope

- Durable installed-profile identity/redesign (P0-3), contract compilation, rework, usability
  facade, binary work, Phase B, or Agent Host.
- Agent Bus Core or any weakening of provenance, checkpoint, outbox, postflight, PR-tuple, business
  ACK, or independent Finding ACK boundaries.
- Any read, ACK, requeue, recovery, redispatch, reuse, or payload access for events 163, 166, or
  173. Verification uses synthetic local state only.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@a84cc3b5cd1d89f2e648a637f9910a527d85892b`
- **Branch**: `codex/truthful-lifecycle-state`
- **Primary files**: `src/agent_workflow/node.py`, `src/agent_workflow/node_service.py`,
  `src/agent_workflow/status.py`, existing lifecycle/status tests, lifecycle/readiness docs.
- **Existing invariants**: installed records and definitions are credential-free; exact listener
  identity remains required; Fast/Deep Preflight is the only dispatch-authority gate.

## Verification level and budget

- **Level B; exactly two new focused tests.**
- Test 1 is table-driven and covers configured/uninstalled, installed/stopped, and running facts
  without a platform matrix or a duplicate state machine.
- Test 2 covers stale listener or missing Preflight evidence, truthful false/unknown output, and one
  legal next action.
- Extend an existing start-order test to assert the frozen uninstalled fail-closed behavior; do not
  add a third standalone test unless the shared fixture cannot express it.
- Reuse `test_node`, `test_node_service`, and `test_status` fixtures. If test growth approaches the
  production diff, consolidate assertions.

## Baseline metrics

- User-authored objects: one node profile and existing runtime files; this package adds none.
- Supported managed path before change: explicit `install`, then explicit `start`; two commands and
  no installation choice. The same two-command path remains, but an invalid direct `start` now
  fails before desired-state mutation with one exact recovery command.
- Current ambiguous point: doctor says `status: ready` even when managed installation, listener,
  and dispatch proof are absent. Target: five independent facts and one ordered next action.
- Elapsed time: not measured; this is not a fresh-environment benchmark.
- Cross-platform behavior: shared contract only; existing installed-wheel CI remains the platform
  gate because adapter rendering is unchanged.

## Acceptance criteria

- [ ] Doctor has no top-level `status: ready` and does not conflate configured with installed,
      running, connected, or dispatch capable.
- [ ] Managed installed truth comes only from the current native install record/definition.
- [ ] Running remains exact profile/process/lease/launch-identity truth.
- [ ] Connected is a bounded live observation.
- [ ] Missing/stale Fast/Deep evidence never yields `dispatch_capable=true`.
- [ ] Human and JSON output preserve false/unknown/stale facts and one legal next action.
- [ ] Managed start is fail-closed before desired-state mutation when uninstalled and names the
      exact install command.
- [ ] Exactly two focused new tests plus existing coverage pass in GitHub CI.
- [ ] An independent review approves the exact PR head before merge.

## Verification

Local Mac: static inspection, changed-file AST/compile checks, JSON parsing where applicable, and
`git diff --check`; do not run Pytest, Ruff, or Rust. GitHub CI owns the full suite and platform
matrix.

## Required output

- `docs/tasks/truthful-lifecycle-state-model-implementation-report.md`
- Necessary lifecycle/readiness/HANDOFF updates, Lore commit series, PR, green CI, independent
  exact-head review, merge, and post-merge `main`/CI verification.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/truthful-lifecycle-state-model.md",
    "docs/tasks/truthful-lifecycle-state-model-implementation-report.md",
    "docs/runtime-node-lifecycle-architecture.md",
    "docs/tasks/node-readiness-snapshot-implementation-report.md",
    "HANDOFF.md",
    "README.md",
    "CHANGELOG.md",
    "src/agent_workflow/node.py",
    "src/agent_workflow/node_service.py",
    "src/agent_workflow/status.py",
    "tests/test_node.py",
    "tests/test_node_service.py",
    "tests/test_status.py",
    "tests/verify_installed_wheel.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_node.py", "tests/test_node_service.py", "tests/test_status.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
