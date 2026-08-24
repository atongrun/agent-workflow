# RC.2 Phase 1A — Formal Operations Package

## Task ID

RC2-P1A-OPERATIONS-PACKAGE

## Background

RC.2 Phase 1 begins from `origin/main` at `366609d5b09b0721271c39ca72e40d8712f35ad3`.
Production operations are currently force-included from `scripts/` and imported through runtime
`sys.path` mutation in the installed CLI, node, and status paths.  This card is the Phase 1 Terra
canary; it establishes only the formal import boundary needed before topology and lifecycle work.

## Goal

Ship production operations as the installed `agent_workflow.operations` package, without production
runtime `sys.path` mutation or a change to Workflow, Agent Bus, or native lifecycle authority.

## Scope

- Move production Python operations modules and agent adapters under
  `src/agent_workflow/operations/`, using package-relative imports.
- Update production package callers and executable resource wrappers to use the formal package.
- Preserve packaged non-Python operational assets and source-checkout behavior.
- Add focused import and installed-wheel regression coverage.
- Record the implementation and canary evidence in the implementation report.

## Out of Scope

- `.awf/project.yaml`, topology selection, machine bindings, or `init`/`doctor`/`deinit` product
  behavior.
- Native lifecycle semantic changes, run-owned closeout, or the Windows no-console implementation.
- Provider-matrix, MCP, TaskCard semantic-assembly, Workflow, Agent Bus, ACK, retry, or recovery
  changes.

## Working Context

- **Repository**: `agent-workflow`
- **Base branch**: `main`
- **Task branch**: `codex/rc2-phase1a-operations-package`
- **Dispatched task commit**: `6f7d79bf1c5718771c8adb6277bcd563a6f77eb1`
- **Remote baseline**: `origin/main` at `366609d5b09b0721271c39ca72e40d8712f35ad3`
- **Entry points**: `pyproject.toml`, `src/agent_workflow/resources.py`, `cli.py`, `node.py`,
  `status.py`, `scripts/`, and installed-wheel tests.
- **Existing behavior**: operational assets are included in the wheel and source/editable usage
  works; current behavior and authority must remain unchanged.
- **Explicit inputs**: the RC.2 productization plan and this TaskCard.  No AI Memory or retained
  event is required.
- **Project rules**: no tracked `AGENTS.md` exists at the baseline; apply `constitution.md`,
  `HANDOFF.md`, and this frozen card.

## Constraints

- Do not invoke, inspect, ACK, requeue, replay, or resend an Agent Bus business delivery.
- No credential, endpoint, host, absolute personal path, or token may enter versioned files.
- Keep operations imports lazy where current callers rely on that behavior; do not introduce a
  generic framework or new dependency.
- Do not change the observable lifecycle/process, Git/PR, checkpoint/outbox/inbox, or ACK contract.

## Acceptance Criteria

- [ ] Production `agent_workflow` code contains no `sys.path` mutation for importing operations.
- [ ] The production operations Python modules are importable as `agent_workflow.operations.*` from
  an installed wheel outside a source checkout.
- [ ] The installed CLI, node, and status paths import the same package without regressions.
- [ ] Existing resource assets are present and executable where their current contract requires it.
- [ ] Focused package/import tests, full test suite, formatting/lint, and installed-wheel checks pass.
- [ ] An implementation report records commands, results, package migration choices, and the Phase
  1A canary measurements (first-pass result, review findings, rework, wall time, and available
  token/cost evidence).

## Verification Commands

```bash
python -m pytest -q tests/test_cli.py tests/test_node.py tests/test_node_service.py tests/test_facade.py
python -m pytest -q
ruff check .
ruff format --check .
python tests/verify_installed_wheel.py
```

## Rework vs. Escalate

- **Rework locally** only for deterministic test, lint, packaging, or acceptance-criterion failures.
- **Escalate** if package conversion would change a frozen authority/lifecycle boundary, needs a new
  dependency, requires retained-event operation, or cannot preserve source and installed behavior.

## Risks

| Risk | Severity | Mitigation |
|---|---:|---|
| Bare intra-operations imports fail after packaging | High | Convert them to explicit relative imports and verify source plus installed wheel. |
| Script assets lose executable/resource behavior | Medium | Preserve assets and exercise installed-wheel checks. |
| Import migration changes lazy operational edges | Medium | Keep caller imports lazy and run focused CLI/node/status regression tests. |

## Required Output Artifacts

- `docs/tasks/rc2-phase1a-operations-package-implementation-report.md`
- Focused and full verification output recorded in the report.

---

## Planner Self-Check

- [x] Goal is a single concrete deliverable.
- [x] Scope and Out of Scope are explicit and non-overlapping.
- [x] Every Acceptance Criterion is verifiable by a command or observable check.
- [x] Verification commands are real repository commands.
- [x] Working Context permits a fresh executor to start without chat history or AI Memory.
- [x] Base branch and remote baseline are explicit; the task branch will be created from that base.
- [x] This task advances Phase 1 without opening later phases.

---

## Postflight Contract

<!-- awf-postflight
{
  "allowed_paths": [
    "pyproject.toml",
    "src/agent_workflow/operations/",
    "src/agent_workflow/resources.py",
    "src/agent_workflow/cli.py",
    "src/agent_workflow/node.py",
    "src/agent_workflow/status.py",
    "scripts/",
    "tests/",
    "docs/tasks/rc2-phase1a-operations-package.md",
    "docs/tasks/rc2-phase1a-operations-package-implementation-report.md",
    "HANDOFF.md",
    "README.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_cli.py", "tests/test_node.py", "tests/test_node_service.py", "tests/test_facade.py"],
    ["{python}", "-m", "pytest", "-q"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
