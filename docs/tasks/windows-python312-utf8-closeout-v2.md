# TaskCard: Complete Windows Python 3.12 UTF-8 portability

## Goal

Make Agent Workflow resource validation and its regression suite pass on Windows Python 3.12
without `PYTHONUTF8` in trusted verification processes. Preserve the POSIX quoted Git-path security
regression and prove a Windows-valid difficult tracked path reaches the real known-path secret scan.

## Baseline and Branch

- Repository: `atongrun/agent-workflow`.
- Base: `origin/main` at `f5f6a37f13e118241755c428a3041ae8a2d56915` (PR #13 merge).
- Branch: `codex/windows-python312-utf8-closeout-v2`.
- The exact dispatched TaskCard commit is authoritative. Before execution, refresh the remote task
  branch and prove its SHA equals the dispatched commit.
- Use a fresh isolated Windows checkout with Python 3.12. Do not reuse an implementation, checkout,
  commit, or event from any previous portability attempt.

The following branches remain evidence and must not be implementation inputs or cleanup targets
during this task:

- `codex/windows-python312-utf8` (event 49);
- `codex/windows-python312-utf8-rerun` (event 50);
- `codex/windows-python312-utf8-closeout` (superseded pre-prerequisite TaskCard);
- `codex/windows-verification-env-gate` (failed circular prerequisite TaskCard).

Do not read, consume, acknowledge, requeue, or otherwise modify events `49`, `50`, `51`, or `52`.
Historical Windows checkouts and the detached dirty postflight worktree are also out of scope.

## Verified Prerequisite

PR #13 merged the default-locale verification boundary. Trusted postflight commands now use a
credential-free environment with `PYTHONUTF8` removed and `PYTHONIOENCODING=utf-8` retained.
A fresh Windows Python 3.12.10 checkout proved the real child-process boundary. Model/tool processes
keep their separate UTF-8 guard.

## Current Portability Gap

The merged baseline still has these bounded defects:

1. `src/agent_workflow/validation.py` opens schemas and YAML/JSON resources without explicit UTF-8.
2. `tests/test_examples.py` opens directly relevant YAML resources without explicit UTF-8.
3. `tests/test_cli.py::run_awf` lacks an explicit UTF-8 child-output and parent-decoding contract.
4. `tests/test_awf_role.py::test_secret_scan_quoted_tracked_filename` creates `a"b.py` on Windows,
   where that filename is illegal.
5. Existing Unicode-path coverage proves NUL-safe collection but not that a tracked Windows-valid
   Unicode/space path with a constructed secret reaches the real per-known-path diff scan.

## Allowed Paths

Only these files may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-v2-implementation-report.md` (create)

This TaskCard is frozen once committed and must not be edited by the Executor.

## Required Implementation

### Explicit UTF-8 reads and CLI output

- Open production schema and YAML/JSON resources explicitly as UTF-8.
- Open directly relevant example YAML test resources explicitly as UTF-8.
- Make the CLI subprocess test helper remove inherited `PYTHONUTF8`, set child
  `PYTHONIOENCODING=utf-8`, and decode captured output explicitly as UTF-8.
- Keep changes literal and local. Do not add an encoding abstraction, locale framework, or
  dependency.

### Portable tracked-path regression

- Keep the quoted-filename regression active where the filesystem permits `"`. Skip narrowly on
  Windows before attempting to create the illegal filename, with a filesystem-specific reason.
- Add one Windows-valid tracked path containing Unicode and a space. Commit a safe version, stage
  that exact path with the existing constructed GitHub-token fixture, and assert
  `_narrow_secret_scan()` fails.
- Exercise real NUL-safe Git path collection and the real per-known-path tracked diff scan. Do not
  mock paths, parse human-readable patch headers, replace the scanner, or add Windows-only
  production behavior.
- Preserve existing plus-prefixed-line and diff-helper regressions.

## Acceptance Criteria

- Production resource reads are UTF-8 regardless of Windows locale.
- CLI child output and parent decoding agree on UTF-8 without inherited `PYTHONUTF8`.
- POSIX retains quoted-path coverage; Windows skips before illegal filename creation.
- A Windows-valid Unicode/space tracked path with a constructed secret fails through the actual
  known-path scan.
- Fresh Windows Python 3.12 passes the full suite, Ruff, and resource validation with
  `PYTHONUTF8` absent from trusted verification children.
- Only the five allowed paths differ from this TaskCard commit.
- The ImplementationReport records exact Windows Python version, explicit environment proof,
  commands/results, changed files, final implementation SHA, strong review, and remaining risks.

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

Expected resource totals remain `6/6 roles`, `4/4 workflows`, and `3/3 examples`.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/validation.py",
    "tests/test_cli.py",
    "tests/test_examples.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-python312-utf8-closeout-v2-implementation-report.md"
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

- Reusing or copying previous portability implementations, commits, checkouts, or event payloads.
- Reading, consuming, acknowledging, requeueing, or modifying events `49`, `50`, `51`, or `52`.
- Resetting, cleaning, deleting, or repairing evidence branches or historical worktrees.
- Agent Bus, listener, protocol, storage, auth, services, reviewer routing, Agent Host, UI, or new
  dependencies.
- Manually completing postflight, commit, push, review, or ACK outside the trusted runner.

## Closeout Consequence

After fresh Windows acceptance, independent strong review, CI, and PR merge, this branch becomes
the successful mainline replacement for the preserved failed portability branches. Evidence-branch
deletion remains a separate evidence-retention decision even though routine v2 delivery branches
may be cleaned after merge.
