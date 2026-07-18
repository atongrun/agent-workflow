# TaskCard: Prove Windows verification without `PYTHONUTF8`

## Goal

Make the trusted postflight runner execute frozen verification commands with `PYTHONUTF8` absent,
while preserving UTF-8 output handling and the existing UTF-8 protection for model/tool processes.
This is the narrow prerequisite for the frozen Windows Python 3.12 UTF-8 closeout.

## Baseline and Branch

- Repository: `atongrun/agent-workflow`.
- Base: `origin/main` at `7b1bb290140e4c0db4efe314eed469dde99510ca`.
- Branch: `codex/windows-verification-env-gate`.
- This TaskCard commit is frozen after creation.

## Current Verified Gap

`scripts/awf_listen.py` sets `PYTHONUTF8=1` for the listener/handler tree. In addition,
`scripts/awf_role.py::child_env()` supplies `PYTHONUTF8=1` to spawned children. The trusted
postflight currently calls `run_verifications()` with `model_env()`, so every verification command
inherits `PYTHONUTF8=1`. This cannot prove the downstream resource and CLI tests pass under the
Windows default locale with the variable absent.

## Allowed Paths

Only these files may change after this TaskCard commit:

1. `scripts/awf_role.py`
2. `tests/test_awf_role.py`
3. `docs/tasks/windows-verification-env-gate-implementation-report.md` (create)

## Required Implementation

- Add one local environment helper for trusted verification commands.
- Start from the existing credential-stripped `model_env()` contract, then remove `PYTHONUTF8`.
- Keep `PYTHONIOENCODING=utf-8` so captured console output remains deterministic.
- Use the new helper only in `run_verifications()`; do not weaken OpenCode/Codex/model process
  UTF-8 handling.
- Extend the existing verification-environment test to prove credentials and `PYTHONUTF8` are
  absent, `PYTHONIOENCODING` remains UTF-8, and `run_verifications()` uses the dedicated helper.
- Keep the change literal and local. No dependencies, listener changes, generic locale framework,
  or TaskCard edits after freeze.

## Acceptance Criteria

- Trusted verification child environments do not contain `PYTHONUTF8` even when the parent or
  listener environment contains it.
- Verification output is still decoded as UTF-8 through `PYTHONIOENCODING=utf-8`.
- Model/tool subprocesses retain their existing UTF-8 environment and credential stripping.
- Windows Python 3.12 executes a real verification child with `PYTHONUTF8` absent.
- Full tests, Ruff, resource validation, allowed-path checks, secret scan, and diff checks pass.

## Required Verification

Run locally and in the fresh Windows prerequisite checkout. Do not set or prefix `PYTHONUTF8` for
the verification process.

```text
py -3.12 --version
python -m pytest -v
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
```

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf_role.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-verification-env-gate-implementation-report.md"
  ],
  "verification_commands": [
    ["py", "-3.12", "--version"],
    ["{python}", "-m", "pytest", "-v"],
    ["{python}", "-m", "ruff", "check", "."],
    ["{python}", "-m", "ruff", "format", "--check", "."],
    ["{python}", "-m", "agent_workflow.cli", "validate", "roles"],
    ["{python}", "-m", "agent_workflow.cli", "validate", "workflows"],
    ["{python}", "-m", "agent_workflow.cli", "validate", "examples"]
  ]
}
-->

## Forbidden Work

- Editing `scripts/awf_listen.py`, Agent Bus, service configuration, protocol/auth/storage, or any
  portability implementation file.
- Reading, consuming, acknowledging, requeueing, or modifying events `49`, `50`, `51`, or `52`.
- Modifying or deleting historical evidence branches, historical Windows checkouts, or the dirty
  detached postflight worktree.
- Dispatching the UTF-8 closeout before this prerequisite is merged and its TaskCard is refrozen
  from the new main baseline.
