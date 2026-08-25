# RC.2 Phase 1G — Windows Zero-Console Managed Lifecycle

## Task ID

RC2-P1G-WINDOWS-ZERO-POPUP

## Goal

Make the exact Windows Task Scheduler reconcile action and its listener descendants run without a
visible console, while preserving the existing InteractiveToken, exact identity and stop/uninstall
contracts.

## Scope

- Use the installed venv's exact `pythonw.exe` for the Task Scheduler action on Windows.
- Use `CREATE_NO_WINDOW` for Windows console descendants spawned by the reconcile/listener path.
- Refuse managed installation if the exact no-console interpreter cannot be proved.
- Add render and lifecycle regressions; prove multiple one-minute triggers, exact stop/uninstall and
  zero remaining run-owned tasks on the existing Windows acceptance machine.

## Exclusions

No PowerShell/VBS wrapper, hidden-UI flag, Windows Service, login-policy change, wildcard task or
process cleanup, Agent Bus/ACK behavior, credentials, release or retained-event operation.

## Acceptance

- [ ] Task Scheduler XML uses an exact venv `pythonw.exe` on Windows and retains InteractiveToken.
- [ ] Every reconcile/listener console descendant is created with no visible console on Windows.
- [ ] Missing/no-match `pythonw.exe` fails before native task creation.
- [ ] Existing macOS/Linux and exact Task Scheduler stop/uninstall contracts remain green.
- [ ] Fresh Windows acceptance records several one-minute triggers, zero visible CMD/console windows,
  and zero run-owned Scheduled Tasks after closeout.

## Verification

```bash
python -m pytest -q tests/test_node.py tests/test_node_service.py tests/test_facade.py
ruff check src/agent_workflow/node.py src/agent_workflow/node_service.py tests/test_node.py tests/test_node_service.py
ruff format --check src/agent_workflow/node.py src/agent_workflow/node_service.py tests/test_node.py tests/test_node_service.py
git diff --check
```
