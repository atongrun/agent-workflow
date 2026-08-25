# RC.2 Phase 1E — Exact Local Deinitialization

## Task ID

RC2-P1E-EXACT-DEINIT

## Goal

Add a deliberate `awf deinit` boundary that removes only the exact current-project/current-machine
local installation and binding, while retaining all immutable workflow and failure evidence.

## Scope

- Load only the platform-local `awf.machine-config.v1` binding for the resolved worktree.
- Refuse if the binding is absent, legacy, identity-drifted, active, or its AWF-generated workspace
  is dirty.
- Stop and uninstall each exact installed listener, then verify its installation record/native
  definition is absent before removing the platform-local binding.
- Remove only exact clean AWF-generated role workspaces and preserve project topology, Plans,
  checkpoints, outbox/inbox, logs, artifacts, and retained failure evidence.
- Add CLI and facade tests for success, refusal, partial-cleanup preservation, and no wildcard
  lifecycle operation.

## Out of Scope

- Disposable acceptance run manifests/automatic closeout, Windows zero-popup behavior, new
  lifecycle manager abstractions, provider/role support, PlanRun state changes, Agent Bus mutation,
  or migration of repository-local legacy bindings.

## Working Context

- **Base**: `main@6b6a8135f23c7e6d69dffc18d4961a80bc82d66f`
- **Branch**: `codex/rc2-phase1e-exact-deinit`

## Acceptance Criteria

- [ ] `awf deinit` removes only exact, current platform-local bindings, managed installations, and
  clean generated workspaces.
- [ ] Unknown/legacy/active/dirty/identity-drifted state fails closed before destructive cleanup.
- [ ] Partial cleanup retains the binding and names the exact blocker; it never performs wildcard
  task, process, profile, or workspace deletion.
- [ ] Committed `.awf/project.yaml` and all Workflow/Agent Bus/evidence facts are unchanged.

## Verification Commands

```bash
python -m pytest -q tests/test_cli.py tests/test_facade.py tests/test_node_service.py
ruff check .
ruff format --check .
git diff --check
```

## Postflight Contract

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/cli.py",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/node.py",
    "tests/test_cli.py",
    "tests/test_facade.py",
    "tests/test_node_service.py",
    "docs/tasks/rc2-phase1e-exact-deinit.md",
    "docs/tasks/rc2-phase1e-exact-deinit-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_cli.py", "tests/test_facade.py", "tests/test_node_service.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
