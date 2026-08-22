# Phase 5-01 Independent L2 Boundary ReviewReport

## Verdict

`PASS` after one bounded L2 repair and focused re-review.

## Initial finding

The first exact-candidate review at `abde5b6` returned one P1 `REQUEST_CHANGES`: role profiles were
replaced one-by-one before `.awf/machine.json`, so a later file-write failure could leave old/new
profile digests split from the machine binding. Workspace cleanup did not restore those files.

## Repair assessment

Repaired head `d9f470c` stages and validates every profile and machine config before commit. The
recoverable batch:

1. moves each exact predecessor to a same-filesystem unique backup;
2. replaces all targets from staged files;
3. loads and validates the complete final machine binding before accepting it;
4. on any error, deletes only files committed by this invocation and restores predecessors in
   reverse order; and
5. removes only invocation-created workspaces/staging while preserving unknown or pre-existing
   paths.

The four table-driven injected cases cover fresh and `--replace` state crossed with reviewer-profile
and machine-config failure. Fresh cases leave no profiles/config/workspaces. Replace cases restore
all watched files byte-for-byte and `load_machine` resolves the original model bindings. No staging
or backup file remains. Focused re-review returned `PASS` with no residual finding.

## Boundary assessment

- Static onboarding matrix advertises only Pi Architect, OpenCode Coder and
  OpenCode/Pi/Codex Reviewer.
- One Agent Tool installation may serve multiple exact role bindings. Same explicit Coder/Reviewer
  model is legal and receives only an informational warning.
- `tool-default` is persisted in machine config while the profile uses empty `model` and renderers
  omit model flags. Explicit opaque refs are syntax-bounded and rendered unchanged; AWF does not own
  provider authentication, configuration, catalogs or fallback.
- Machine config binds exact profile digest, workspace, tool, model selection, state root and
  Finding state. Roles cannot share a workspace.
- Pi Architect is a real closed renderer using read-only tools. Its stdout helper validates before
  create-only persistence and returns a non-authorizing `ArtifactFact`; it has no application,
  Store, journal, transport, listener or Workflow transition integration.
- Agent Bus capability is proven from local structured-listener help before health/event work;
  version text alone is not authority.
- Finding is absent by default from prompts/capture/status and remains an explicit profile-driven
  Phase A opt-in. No Runtime authority field was added.
- No Host, scheduler, registry, plugin framework, TaskCard execution, model call, business event,
  Runtime default/adoption, migration, release or Phase 5-02 behavior was introduced.

## Evidence

- TaskCard product/architecture Review: `REQUEST_CHANGES`, repaired `8ba54c1`, focused `PASS`;
  owner model-selection clarification `7a0abb2`, focused `PASS`.
- Local focused suite: `470 passed, 2 skipped`.
- Local full suite: `913 passed, 5 skipped`.
- Ruff, format, compileall, resource validation and diff check: PASS.
- Fresh installed wheel: PASS; wheel SHA-256
  `a9d44e394df6bc68a1f306b56d949a64213e89b289ca21f318499609f8f2d9b5`.
- Exact repaired-head ordinary CI `32574488604`: PASS, including Windows recovery/configuration and
  all three installed-wheel jobs.
- Exact repaired-head Binary Feasibility `32574488742`: PASS across all native/Rust cells and both
  aggregates.

## Next boundary

Phase 5-01 may close as a reviewed candidate. PR #121 remains Draft for owner integration. The only
next legal milestone is a separately frozen Phase 5-02 fresh `awf run <TaskCard>` production
integration. This Review does not authorize starting it.

<!-- awf-review-report
{
  "verdict": "PASS",
  "critical": 0,
  "high": 0,
  "medium": 0,
  "low": 0,
  "closed_high": 1,
  "candidate": "d9f470c",
  "focused_tests": "470 passed, 2 skipped",
  "full_tests": "913 passed, 5 skipped",
  "ci_run": "32574488604",
  "binary_run": "32574488742",
  "phase_5_02": "NOT_STARTED"
}
-->
