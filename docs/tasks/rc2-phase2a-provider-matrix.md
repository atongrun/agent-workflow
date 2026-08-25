# RC.2 Phase 2A — Closed Provider/Role Matrix

## Task ID

RC2-P2A-PROVIDER-MATRIX

## Goal

Implement the nine Pi/OpenCode/Codex × Architect/Coder/Reviewer provider-rendering and selection
cells over the existing Workflow authority boundaries.

## Scope

- Extend the closed runtime provider renderers and validated provider selections to all nine cells.
- Keep Architect read-only and semantic-output-only; Coder writable only in the existing isolated
  model workspace; Reviewer read-only with the existing strict ReviewReport boundary.
- Wire the existing operations Coder dispatch to the newly rendered Codex and Pi coder cells.
- Parse the common Architect semantic payload and assemble trusted TaskCard authority facts before
  the existing create-only persistence boundary.
- Add deterministic argv/input/environment/permission/failure conformance for every cell.

## Provider comparison

- **Codex:** reuse the current non-interactive `exec` renderer; adapt sandbox to `read-only` for
  Architect/Reviewer and `workspace-write` for Coder; reject session resume and Git authority.
- **Pi:** reuse current no-session, no-approve, no-extension renderer flags; adapt only Coder's
  bounded write-tool allowlist; reject provider-owned publication and continuation.
- **OpenCode:** reuse current `run --dir` structured invocation; adapt Architect to closed semantic
  JSON output; reject built-in Plan/Build defaults and session-as-truth.
- **r4 candidate:** adapt only pure renderer, selection and coder-dispatch fragments; reject its
  old scripts/Plan/lifecycle/recovery changes. No wholesale transplant.

## Exclusions

- Architect milestone/terminal-decision expansion beyond the existing closed decision contracts,
  MCP/status, provider session resume, generic registry/plugin framework, Git/PR/merge/ACK/replay
  changes, real provider smoke, README support claims, topology E2E and release work.

## Acceptance

- [ ] Every Provider/Role selection has one closed renderer and deterministic conformance.
- [ ] Invalid provider/role/options fail before process start.
- [ ] Architect is read-only; Coder receives only the isolated writable workspace; Reviewer is
  read-only and retains current report handling.
- [ ] Existing selection integrity, recovery, artifact, Git and ACK boundaries are unchanged.
- [ ] Coder dispatch supports exactly Codex/OpenCode/Pi without a new workflow engine.

## Verification

```bash
python -m pytest -q tests/test_runtime_provider_renderers.py tests/test_runtime_core_contracts.py tests/test_runtime_architect.py tests/test_node.py tests/test_facade.py tests/test_plan_loop.py tests/test_awf_role.py tests/test_awf_plan.py
ruff check src/agent_workflow/runtime src/agent_workflow/node.py src/agent_workflow/facade.py src/agent_workflow/plan_loop.py src/agent_workflow/operations/awf_role.py tests
ruff format --check src/agent_workflow/runtime src/agent_workflow/node.py src/agent_workflow/facade.py src/agent_workflow/plan_loop.py src/agent_workflow/operations/awf_role.py tests
git diff --check
```

## Postflight Contract

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/rc2-phase2a-provider-matrix.md",
    "docs/tasks/rc2-phase2a-provider-matrix-implementation-report.md",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/architect.py",
    "src/agent_workflow/runtime/renderers.py",
    "src/agent_workflow/node.py",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/plan_loop.py",
    "src/agent_workflow/cli.py",
    "src/agent_workflow/operations/awf_role.py",
    "src/agent_workflow/operations/awf_plan.py",
    "src/agent_workflow/operations/awf_taskcard.py",
    "tests/test_runtime_provider_renderers.py",
    "tests/test_runtime_core_contracts.py",
    "tests/test_runtime_architect.py",
    "tests/test_node.py",
    "tests/test_facade.py",
    "tests/test_plan_loop.py",
    "tests/test_awf_role.py",
    "tests/test_awf_plan.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_provider_renderers.py", "tests/test_runtime_core_contracts.py", "tests/test_runtime_architect.py", "tests/test_node.py", "tests/test_facade.py", "tests/test_plan_loop.py", "tests/test_awf_role.py", "tests/test_awf_plan.py"],
    ["ruff", "check", "src/agent_workflow/runtime", "src/agent_workflow/node.py", "src/agent_workflow/facade.py", "src/agent_workflow/plan_loop.py", "src/agent_workflow/operations/awf_role.py", "tests"],
    ["ruff", "format", "--check", "src/agent_workflow/runtime", "src/agent_workflow/node.py", "src/agent_workflow/facade.py", "src/agent_workflow/plan_loop.py", "src/agent_workflow/operations/awf_role.py", "tests"]
  ]
}
-->
