# Agent Tool Compatibility Formal Acceptance Plan

Status: approved by the repository owner for one fresh, serial formal-acceptance run.

## Goal

Prove the newly added Agent Tool adapters through one small, reversible documentation delivery:
Windows OpenCode authors the TaskCard and implements the change; Mac Pi performs the independent
review. The trusted existing PR/CI path remains the only Git and GitHub path.

## One-card scope

- Update the current adapter table in `README.md` to state the proven Architect and Coder coverage.
- Add one concise `Unreleased` changelog entry describing the newly proven adapters and their safety
  boundaries.
- Preserve all existing role semantics, Reviewer behavior, Runtime ownership, and default selections.

## Non-goals

- No Runtime redesign, Agent Bus change, recovery/resume feature, new worker, scheduler, queue,
  migration, release, tag, or manual ACK/requeue.
- Do not edit application code, tests, schemas, or historical evidence during this card.
- Do not merge a pull request without a separate owner authorization.

## Required formal facts

- Architect selection is OpenCode with its exact frozen RoleBinding.
- Coder selection is OpenCode with its exact frozen RoleBinding.
- Reviewer selection is Pi with its exact frozen RoleBinding and read-only tools.
- The Coder runs only in its existing no-remote isolated workspace; trusted code owns import,
  commit, fork push, PR, CI observation, and any terminal action.
- The Architect never writes the trusted repository directly; its output is captured and validated
  by trusted code.

## Acceptance criteria

- One dynamically generated TaskCard binds the exact observed upstream `main`, frozen selections,
  and an allowed-path contract limited to `README.md`, `CHANGELOG.md`, and required artifacts.
- Windows Coder produces a valid ImplementationReport, passes the TaskCard verification commands,
  and publishes exactly one fork branch and PR through trusted code.
- Mac Pi produces a valid read-only ReviewReport against the exact PR head.
- Relevant Architect, Coder, and Reviewer queues return to zero after the completed allowed stage.
- The PR remains a Draft and no merge, tag, release, manual ACK, requeue, resend, or historical
  delivery mutation occurs without a separate owner authorization.

## Verification commands

```bash
python -m pytest -q tests/test_node.py tests/test_facade.py tests/test_plan_loop.py tests/test_awf_plan.py tests/test_awf_role.py tests/test_runtime_provider_renderers.py tests/test_awf_taskcard.py
ruff check src scripts tests
ruff format --check src scripts tests
```
