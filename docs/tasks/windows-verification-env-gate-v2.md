# TaskCard: Isolate default-locale verification from runner UTF-8 mode

## Goal

Make trusted postflight verification commands run with `PYTHONUTF8` absent while preserving UTF-8
console output and the existing UTF-8 guard for model/tool processes. This is a prerequisite for,
not a substitute for, the Windows Python 3.12 portability closeout.

## Baseline and Branch

- Repository: `atongrun/agent-workflow`.
- Base: `origin/main` at `7b1bb290140e4c0db4efe314eed469dde99510ca`.
- Branch: `codex/windows-verification-env-gate-v2`.
- This TaskCard supersedes the unmergeable v1 prerequisite TaskCard. The v1 branch required the
  complete Windows suite even though that suite contains the downstream portability failures this
  prerequisite exists to unblock. Preserve v1 as failure evidence; do not merge, reset, or delete
  it during v2.
- This TaskCard is frozen after creation.

## Current Verified Gap

`scripts/awf_listen.py` forces `PYTHONUTF8=1` for listener and handler reliability.
`scripts/awf_role.py::child_env()` also supplies it to children. Because `run_verifications()` uses
`model_env()`, deterministic postflight commands cannot exercise Windows default-locale behavior.

The merged baseline also has separate known Windows portability failures, including an illegal
quoted filename regression and locale-dependent resource reads. Those belong only to the later
portability TaskCard. They must not be pulled into this prerequisite or used to require a circular
full-Windows-suite pass before the prerequisite can merge.

## Allowed Paths

Only these files may change after this TaskCard commit:

1. `scripts/awf_role.py`
2. `tests/test_awf_role.py`
3. `docs/tasks/windows-verification-env-gate-v2-implementation-report.md` (create)

## Required Implementation

- Add a dedicated environment helper for trusted verification commands.
- Derive it from credential-stripped `model_env()`, remove `PYTHONUTF8`, and retain
  `PYTHONIOENCODING=utf-8`.
- Use it only from `run_verifications()`.
- Preserve the existing model/tool environment behavior.
- Test the helper contract, prove `run_verifications()` selects it, and run one real Python child
  from a parent with `PYTHONUTF8=1`; the child must observe `PYTHONUTF8` absent and
  `PYTHONIOENCODING=utf-8`.
- No listener changes, dependencies, generic locale framework, or portability implementation.

## Acceptance Criteria

- Local full suite, Ruff, resource validation, allowed-path scan, secret scan, and diff checks pass.
- Windows Python 3.12 reports external `PYTHONUTF8` absent.
- On Windows, the four directly related tests pass, including the real child-process boundary.
- On Windows, Ruff check and format pass for the two changed Python files.
- The complete Windows suite and resource validation are explicitly deferred to the downstream
  portability TaskCard; known baseline failures are neither fixed nor accepted here.

## Required Verification

Local integration verification:

```text
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
```

Fresh Windows focused verification with external `PYTHONUTF8` absent:

```text
py -3.12 --version
python -m pytest -q tests/test_awf_role.py -k "model_env_strips_tokens or verification_env_strips_credentials_and_pythonutf8 or run_verifications_uses_verification_env or verification_child_runs_without_pythonutf8"
python -m ruff check scripts/awf_role.py tests/test_awf_role.py
python -m ruff format --check scripts/awf_role.py tests/test_awf_role.py
```

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf_role.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-verification-env-gate-v2-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_awf_role.py", "-k", "model_env_strips_tokens or verification_env_strips_credentials_and_pythonutf8 or run_verifications_uses_verification_env or verification_child_runs_without_pythonutf8"],
    ["{python}", "-m", "ruff", "check", "scripts/awf_role.py", "tests/test_awf_role.py"],
    ["{python}", "-m", "ruff", "format", "--check", "scripts/awf_role.py", "tests/test_awf_role.py"]
  ]
}
-->

## Forbidden Work

- Editing `scripts/awf_listen.py`, portability files, Agent Bus, services, protocol, auth, storage,
  or the frozen v1/portability TaskCards.
- Reading, consuming, acknowledging, requeueing, or modifying events `49`, `50`, `51`, or `52`.
- Modifying or deleting historical evidence branches/checkouts, v1 evidence, or the dirty detached
  postflight worktree.
- Dispatching the portability closeout before this prerequisite is merged and a replacement
  portability TaskCard is frozen from the new main baseline.
