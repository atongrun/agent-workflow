# TaskCard: P0-2 Truthful Lifecycle State Model

## Goal

Replace the ambiguous node `status=ready` projection with five orthogonal machine facts:
`configured`, `installed`, `running`, `connected`, and `dispatch_capable`. Human and JSON output
must preserve false, unknown, and stale observations and name exactly one legal next action.

## Frozen managed-start behavior

Managed start has one supported path on launchd, systemd, and Task Scheduler:

```text
awf node install --profile <profile>
-> awf node start --profile <profile>
```

`install` remains explicit and idempotent. `start` does not create or rewrite a native definition.
When the installed record/definition is missing, every manager fails with the exact
`awf node install --profile <profile>` next action. This is the smallest reversible choice and
preserves the existing separation between configuration and native lifecycle mutation.

## Scope

- `doctor` proves profile/configuration, selected tool, and workspace readiness; it reports live
  Bus connectivity separately rather than folding it into configuration readiness.
- Managed `installed` is derived only from the native install record and its definition digest.
- `running` keeps the existing conjunctive profile/process/lease/launch-identity agreement.
- `connected` is a bounded live Agent Bus health or queue observation and never implies running.
- `dispatch_capable` is true only when current Fast validation accepts the bound Deep proof;
  missing or stale proof remains false/unknown/stale and directs the operator to Preflight.
- `doctor` and `node status`, in human and JSON form, expose the five facts and one legal next
  action without reading payloads or mutating any lifecycle.

## Out of Scope

- Durable installed-profile snapshots/exact-stop redesign (P0-3), compiled contracts (P0-4),
  implement-to-rework repair (P0-5), causal status/facade work, binary packaging, Phase B, Agent
  Host, or Agent Bus Core changes.
- Any weakening of provenance, checkpoint, outbox, postflight, PR tuple, handler-success ACK, or
  business/Finding ACK separation.
- Any read, ACK, requeue, recovery, redispatch, reuse, or payload access for events 163, 166, 173,
  or another retained business event.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Exact baseline**: `origin/main@a84cc3b5cd1d89f2e648a637f9910a527d85892b` (includes P0-1 PR #81)
- **Task branch**: `codex/p0-2-truthful-lifecycle-state`
- **Primary code**: `src/agent_workflow/node.py`, `src/agent_workflow/node_service.py`,
  `src/agent_workflow/status.py` and their existing tests.

## Verification level and budget

- **Level B**; add two or at most three focused tests.
- One table-driven regression covers configured/uninstalled, installed/stopped, and running facts
  without a state-by-platform matrix.
- One representative missing/stale Preflight regression verifies truthful output and the legal
  next action.
- One compact manager-parameterized regression may lock the explicit install prerequisite.
- Reuse existing fixtures and assert observable facts; do not copy the lifecycle or Preflight
  state machines into tests. If test growth approaches production growth, simplify first.

## Baseline metrics

- Supported managed path: two commands and zero human choices (`install`, then `start`).
- User-authored objects: unchanged; one node profile plus existing owner/runtime artifacts.
- Existing misleading boundary: doctor can say `ready` while the native definition is absent.
- Target boundary: `configured=true`, `installed=false`, one exact install action, before start.
- Elapsed time: not measured; this is not a fresh-machine benchmark.
- Platform proof: reuse installed-wheel Linux/Windows/macOS CI because manager execution behavior
  is unchanged.

## Acceptance criteria

- [ ] No umbrella `status=ready` remains in the readiness report.
- [ ] All five lifecycle facts have explicit provenance and truthful current/false/unknown/stale
      semantics.
- [ ] Managed installation is derived from the install record plus native definition, never from
      doctor or listener state.
- [ ] Running retains exact bound identity semantics; connected is bounded live observation.
- [ ] Dispatch capability is true only after current Fast validation accepts Deep proof.
- [ ] Human and JSON output name one legal next action.
- [ ] Uninstalled managed start names the exact install command consistently for all managers.
- [ ] GitHub CI is green and independent review approves the exact PR head.

## Verification

Local Mac: static inspection, AST/JSON parsing and `git diff --check` only. Pytest, Ruff, full
suite, installed-wheel and platform verification belong to GitHub CI.

## Required output

- `docs/tasks/truthful-lifecycle-state-model-implementation-report.md`
- Necessary lifecycle/readiness/HANDOFF/README/CHANGELOG updates, Lore commit, PR, green CI,
  independent approval, merge, and post-merge verification.

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
