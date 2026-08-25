# RC.2 Phase 1B — Tracked Project Topology

## Task ID

RC2-P1B-PROJECT-TOPOLOGY

## Goal

Generate, load, and strictly validate the credential-free committed `.awf/project.yaml` topology
for the two RC.2 official profiles.

## Scope

- Define the closed project-topology data model and YAML read/write boundary.
- Support only `uniform-opencode` and `role-specialized` with their frozen role/tool defaults.
- Reject unknown keys, role/tool drift, credentials, network/host data, absolute paths, and
  machine/profile/process/workspace state before any lifecycle or Workflow mutation.
- Provide a narrow CLI operation that writes the project file without selecting online machines.

## Out of Scope

- Platform-local machine bindings, profile creation, listener activation, init/doctor/deinit changes,
  provider matrix expansion, PlanRun override freezing, MCP, and all lifecycle behavior.

## Working Context

- **Repository**: `agent-workflow`
- **Base branch**: `main` at `c87db43654cdd4b01e34aa40bd6b4deec0ff9fc0`
- **Task branch**: `codex/rc2-phase1b-project-topology`
- **Authority**: `docs/plans/v0.4.0-rc.2-productization-plan.md`, sections 2.1–2.4.

## Acceptance Criteria

- [ ] Both official profiles generate one credential-free canonical YAML project file.
- [ ] Loader validation fails closed for malformed, unknown, unsafe, or profile-inconsistent input.
- [ ] No topology API or CLI mutates local bindings, profiles, listeners, state roots, or Agent Bus.
- [ ] Focused project-topology tests, lint, format, and diff gates pass.

## Verification Commands

```bash
python -m pytest -q tests/test_project_topology.py tests/test_cli.py
ruff check .
ruff format --check .
git diff --check
```

## Postflight Contract

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/project_topology.py",
    "src/agent_workflow/cli.py",
    "tests/test_project_topology.py",
    "tests/test_cli.py",
    "docs/tasks/rc2-phase1b-project-topology.md",
    "docs/tasks/rc2-phase1b-project-topology-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_project_topology.py", "tests/test_cli.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
