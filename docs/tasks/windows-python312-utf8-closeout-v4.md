# TaskCard: Complete Windows Python 3.12 UTF-8 closeout

## Goal

Make the complete Agent Workflow suite and resource validation pass on a fresh Windows Python 3.12
checkout without `PYTHONUTF8` in trusted verification children. Preserve the POSIX quoted-path
security regression and prove a Windows-valid difficult tracked path reaches the real known-path
secret scan.

## Frozen Baseline

- Base: `origin/main` at `f5f6a37f13e118241755c428a3041ae8a2d56915` (PR #13 merge).
- Branch: `codex/windows-python312-utf8-closeout-v4`.
- Refresh the remote task branch and prove its SHA equals the exact dispatched TaskCard commit.
- Use a new isolated Windows checkout and Python 3.12 environment. Do not reuse any earlier
  implementation, checkout, commit, report, or event.

Preserve all earlier portability evidence, including branches/checkouts for events 49, 50, 73,
and 74. Do not read, consume, ACK, requeue, modify, reset, clean, or delete events 49, 50, 51, 52,
73, or 74 or their evidence checkouts.

## Verified Prerequisite

PR #13 made trusted postflight use a credential-free environment with `PYTHONUTF8` removed and
`PYTHONIOENCODING=utf-8` retained. Model/tool processes keep a separate UTF-8 guard.

## Proven Gaps

Fresh Windows failures proved all of the following:

1. Production schema and YAML/JSON reads need explicit UTF-8.
2. Direct example YAML test reads need explicit UTF-8.
3. `tests/test_cli.py::run_awf` needs a child/parent UTF-8 output contract with inherited
   `PYTHONUTF8` removed.
4. `a"b.py` is illegal on Windows; that test must skip before file creation only on Windows.
5. The real secret scanner needs a tracked Windows-valid Unicode/space path regression.
6. `test_minimal_listener_handler_opencode_return_chain` must not reuse any `.cmd` file for its
   Agent Bus success shim. Even a separate `.cmd` shim still fails because production intentionally
   routes `.cmd` through `cmd /c` with JSON arguments.
7. `test_dispatch_dry_run_carries_distinct_default_report_paths` must pass Git Bash an MSYS drive
   path such as `/d/Work/...`, not a native `D:\...` path and not `D:/...`.

## Allowed Paths

Only these files may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-v4-implementation-report.md` (create)

This TaskCard is frozen after commit and must not be edited by the Executor.

## Required Implementation

- Add `encoding="utf-8"` directly to production schema/resource opens and directly relevant example
  YAML test opens. Add no abstraction or dependency.
- In `run_awf`, copy the environment, remove `PYTHONUTF8`, set `PYTHONIOENCODING=utf-8`, and decode
  captured output with explicit UTF-8.
- Keep the quoted tracked-filename regression active on supporting filesystems. Skip narrowly on
  Windows before attempting to create `a"b.py`, with a filesystem-specific reason.
- Add a tracked Windows-valid path containing Unicode and a space. Commit a safe version, stage that
  exact path containing the existing constructed GitHub-token fixture, and assert the real
  `_narrow_secret_scan()` fails. Do not mock path collection/scanning or parse patch headers.
- In `test_minimal_listener_handler_opencode_return_chain`, keep the controlled `.cmd` shim only for
  the OpenCode model-tool boundary. For Agent Bus, create a plain Python script named exactly `send`
  in the handler `cwd`, containing only a deterministic successful exit, and set `AWF_BUS_BIN` to
  `sys.executable`. Production will therefore execute `python.exe send ...`; the script ignores the
  remaining arguments and returns zero. Do not create or use a `.cmd`/`.bat` bus shim and do not
  change production routing.
- In the dispatch dry-run test, convert a drive-qualified script path `X:\rest` to the exact MSYS
  form `/x/rest` (lowercase drive and forward slashes) before invoking Git Bash. Decode captured
  stdout/stderr explicitly as UTF-8. Keep the real shell script under test.
- Preserve plus-prefixed-line, diff-helper, NUL-safe collection, and return-chain regressions.

## Acceptance Criteria

- Fresh Windows Python 3.12 runs the entire suite with no deselection and only the intentional
  Windows quoted-filename skip.
- Both formerly failing full-suite tests pass without production listener/routing changes.
- Ruff passes; resources remain `6/6 roles`, `4/4 workflows`, and `3/3 examples`.
- Exactly the five allowed paths differ from this frozen commit.
- The ImplementationReport records Python version, trusted `PYTHONUTF8`-absent proof, exact command
  results, changed files, implementation SHA, review result, and remaining risks.

## Required Verification

Run all commands through the trusted runner. Do not globally set or prefix `PYTHONUTF8`.

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
    "docs/tasks/windows-python312-utf8-closeout-v4-implementation-report.md"
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

- Any prior implementation/evidence reuse or any action on events 49-52, 73, or 74.
- Repairing, cleaning, resetting, or deleting historical branches/checkouts/worktrees.
- Production Agent Bus/listener/protocol/storage/auth/service/reviewer-routing changes, new
  dependencies, Agent Host, UI, VPS, or real listener configuration changes.
- Manually completing postflight, implementation commit, push, review, or ACK outside the trusted
  runner.

## Closeout

After fresh Windows acceptance, independent strong review, CI, and PR merge, v4 replaces the
preserved failed portability attempts. Evidence deletion remains a separate retention decision.
