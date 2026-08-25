# RC.2 Phase 1C — Platform-Local Machine Binding

## Task ID

RC2-P1C-PLATFORM-MACHINE-BINDING

## Goal

Move new normal machine binding state out of the tracked repository into a platform-local,
repository-keyed path while retaining `.awf/machine.json` as a read-only compatibility source.

## Scope

- Derive one deterministic platform-local machine binding path from the exact resolved repository
  worktree identity.
- Make normal init write only that path.
- Load the platform binding, or the legacy repository-local binding only when the platform binding
  is absent; conflicting dual bindings fail closed.
- Preserve the existing machine-config schema, atomic rollback, profile, workspace, and lifecycle
  behavior.

## Out of Scope

- Machine-config schema migration, profile/lifecycle changes, deinit, topology-to-binding selection,
  online discovery, listener behavior, Agent Bus operations, or removal of compatibility reading.

## Working Context

- **Repository**: `agent-workflow`
- **Base branch**: `main` at `575a91199038b5f9dc03be437154973a087a639a`
- **Task branch**: `codex/rc2-phase1c-platform-machine-binding`
- **Inputs**: RC.2 plan section 2.1 and merged Phase 1B topology boundary.

## Acceptance Criteria

- [ ] New init never writes `.awf/machine.json`.
- [ ] Platform binding paths are deterministic, private-path-free in their directory key, and
  different for different resolved worktrees.
- [ ] Legacy-only binding remains readable; dual binding ambiguity fails closed.
- [ ] Existing exact profile/workspace/rollback/lifecycle tests remain unchanged and pass.

## Verification Commands

```bash
python -m pytest -q tests/test_facade.py tests/test_cli.py tests/test_plan_loop.py
ruff check .
ruff format --check .
git diff --check
```

## Postflight Contract

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/facade.py",
    "tests/test_facade.py",
    "tests/test_cli.py",
    "tests/test_plan_loop.py",
    "docs/tasks/rc2-phase1c-platform-machine-binding.md",
    "docs/tasks/rc2-phase1c-platform-machine-binding-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_facade.py", "tests/test_cli.py", "tests/test_plan_loop.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
