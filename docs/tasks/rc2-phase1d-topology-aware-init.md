# RC.2 Phase 1D — Topology-Aware Local Init Selection

## Task ID

RC2-P1D-TOPOLOGY-AWARE-INIT

## Goal

Make normal `awf init` derive local role defaults from the committed `.awf/project.yaml`, while
failing closed when the selected machine cannot satisfy the declared topology.

## Scope

- Require and load the tracked project topology before normal init discovery/mutation.
- Use declared role/tool defaults for locally available roles; `--roles` remains the explicit local
  machine subset.
- Reject a selected unavailable/unsupported declared tool before profile/workspace/binding writes.
- Keep explicit pre-PlanRun model overrides and existing compatibility `awf enroll` behavior.

## Out of Scope

- Implementing missing Provider/Role cells, changing `.awf/project.yaml`, dynamic/online routing,
  machine registry, lifecycle/deinit, or PlanRun/MCP behavior.

## Working Context

- **Base**: `main@9aa88a181ba8ad942c9e6ca3d63133263fb54d1c`
- **Branch**: `codex/rc2-phase1d-topology-aware-init`
- `role-specialized` is currently executable; `uniform-opencode` Architect must remain truthful
  fail-closed until Phase 2 implements that cell.

## Acceptance Criteria

- [ ] Normal init without `.awf/project.yaml` fails before discovery/mutation.
- [ ] Role-specialized local defaults select Pi/OpenCode/Codex exactly.
- [ ] Selected uniform OpenCode Architect fails before mutation; no silent provider fallback.
- [ ] Explicit local role subsets and existing compatibility enroll remain valid.

## Verification Commands

```bash
python -m pytest -q tests/test_cli.py tests/test_facade.py tests/test_project_topology.py
ruff check .
ruff format --check .
git diff --check
```

## Postflight Contract

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/cli.py",
    "tests/test_cli.py",
    "docs/tasks/rc2-phase1d-topology-aware-init.md",
    "docs/tasks/rc2-phase1d-topology-aware-init-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_cli.py", "tests/test_facade.py", "tests/test_project_topology.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
