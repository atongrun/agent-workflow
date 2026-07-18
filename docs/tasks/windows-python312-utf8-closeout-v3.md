# TaskCard: Close Windows Python 3.12 UTF-8 portability after full-suite evidence

## Goal

Make the complete Agent Workflow suite and resource validation pass on a fresh Windows Python 3.12
checkout without `PYTHONUTF8` in trusted verification children. Preserve the POSIX quoted Git-path
security regression and prove a Windows-valid difficult tracked path reaches the real known-path
secret scan.

## Baseline and Branch

- Repository: `atongrun/agent-workflow`.
- Base: `origin/main` at `f5f6a37f13e118241755c428a3041ae8a2d56915` (PR #13 merge).
- Branch: `codex/windows-python312-utf8-closeout-v3`.
- The exact dispatched TaskCard commit is authoritative. Refresh the remote task branch and prove
  its SHA equals the dispatched commit before execution.
- Use a fresh isolated Windows checkout with Python 3.12. Do not reuse an implementation, checkout,
  commit, or event from a previous portability attempt.

Preserve these evidence branches and their Windows checkouts:

- `codex/windows-python312-utf8` (event 49);
- `codex/windows-python312-utf8-rerun` (event 50);
- `codex/windows-python312-utf8-closeout`;
- `codex/windows-verification-env-gate`;
- `codex/windows-python312-utf8-closeout-v2` (event 73 full-suite failure).

Do not read, consume, acknowledge, requeue, or otherwise modify events `49`, `50`, `51`, `52`, or
`73`. Historical Windows checkouts and the detached dirty postflight worktree are out of scope.

## Verified Prerequisite

PR #13 merged the default-locale verification boundary. Trusted postflight commands use a
credential-free environment with `PYTHONUTF8` removed and `PYTHONIOENCODING=utf-8` retained.
Model/tool processes keep their separate UTF-8 guard.

## Current Portability Gap

Fresh event 73 proved the original resource, CLI, and tracked-path gaps and additionally exposed two
pre-existing Windows-only failures in the required full suite:

1. Production validation opens schemas and YAML/JSON resources without explicit UTF-8.
2. Directly relevant example tests open YAML without explicit UTF-8.
3. `tests/test_cli.py::run_awf` lacks an explicit UTF-8 child-output and parent-decoding contract.
4. The quoted tracked filename regression attempts to create the illegal Windows filename
   `a"b.py`.
5. Unicode path coverage does not prove a tracked Windows-valid Unicode/space path with a
   constructed secret reaches the real per-known-path diff scan.
6. `test_minimal_listener_handler_opencode_return_chain` reuses the `.cmd` model-tool shim as the
   Agent Bus shim. Its JSON-bearing `cmd /c` invocation fails before the test can prove the handler
   return chain. Give the bus a separate deterministic, argument-insensitive success shim without
   changing production routing.
7. `test_dispatch_dry_run_carries_distinct_default_report_paths` passes a native backslash script
   path to Git Bash and decodes captured output using the Windows locale. Pass a Git-Bash-readable
   script path and decode explicitly as UTF-8.

## Allowed Paths

Only these files may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-v3-implementation-report.md` (create)

This TaskCard is frozen once committed and must not be edited by the Executor.

## Required Implementation

- Open production schema and YAML/JSON resources explicitly as UTF-8.
- Open directly relevant example YAML resources explicitly as UTF-8.
- In `run_awf`, copy the environment, remove inherited `PYTHONUTF8`, set child
  `PYTHONIOENCODING=utf-8`, and decode captured output explicitly as UTF-8.
- Keep the quoted-filename regression active where `"` is legal. Skip narrowly on Windows before
  creating the illegal filename, with a filesystem-specific reason.
- Add one Windows-valid tracked path containing Unicode and a space. Commit a safe version, stage
  that exact path with the existing constructed GitHub-token fixture, and assert the real
  `_narrow_secret_scan()` fails. Do not mock path collection or the scanner.
- In the minimal listener-handler test, keep the controlled OpenCode `.cmd` shim for the model-tool
  boundary, but give Agent Bus a distinct deterministic success shim that ignores its arguments and
  does not depend on `.cmd` JSON quoting. Keep the real handler process and event-return chain under
  test.
- In the dispatch dry-run test, invoke Git Bash with a slash-form script path and decode captured
  stdout/stderr explicitly as UTF-8.
- Keep changes literal and local. Do not add an abstraction, production Windows special case, or
  dependency. Preserve plus-prefixed-line and diff-helper regressions.

## Acceptance Criteria

- Fresh Windows Python 3.12 passes the complete suite: no deselected tests, only the intentional
  Windows quoted-filename skip.
- Production resource reads and subprocess output decoding are UTF-8 independent of Windows locale.
- The Windows-valid Unicode/space tracked path fails through the actual NUL-safe known-path scan.
- The two full-suite-only Windows regressions pass without production changes.
- Ruff and resource validation pass with totals `6/6 roles`, `4/4 workflows`, `3/3 examples`.
- Only the five allowed paths differ from this TaskCard commit.
- The ImplementationReport records Python version, trusted `PYTHONUTF8`-absent evidence, all command
  results, changed files, implementation SHA, review result, and remaining risks.

## Required Verification

Run through the trusted runner in the fresh Windows checkout. Do not globally set or prefix
`PYTHONUTF8`.

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
    "src/agent_workflow/validation.py",
    "tests/test_cli.py",
    "tests/test_examples.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-python312-utf8-closeout-v3-implementation-report.md"
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

- Reusing or copying prior portability implementations, commits, checkouts, or event payloads.
- Reading, consuming, ACKing, requeueing, or modifying events `49`, `50`, `51`, `52`, or `73`.
- Resetting, cleaning, deleting, or repairing evidence branches or historical worktrees.
- Production listener, protocol, storage, auth, service, reviewer-routing, Agent Host, UI, or
  dependency changes.
- Manually completing postflight, implementation commit, push, review, or ACK outside the trusted
  runner.

## Closeout Consequence

After fresh Windows acceptance, independent strong review, CI, and PR merge, this branch replaces
the preserved failed portability attempts. Evidence-branch deletion remains a separate retention
decision; routine successful v3 delivery branches may be cleaned after merge.
