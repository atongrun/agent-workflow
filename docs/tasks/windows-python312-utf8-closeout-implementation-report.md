# ImplementationReport: Windows Python 3.12 UTF-8 closeout

## Baseline and Commits

- Frozen TaskCard commit: `815bd3120a8040f9ddaf3c4a2a990ba650742a7d`.
- Local implementation commit: `0f6d9451d85d8b53170ed20e715a087b58783edf`.
- The ImplementationReport is committed separately so the implementation SHA remains stable.
- The remote task branch remains frozen at the TaskCard commit pending explicit push and live
  Windows authorization.

## Changed Files

- `src/agent_workflow/validation.py`
- `tests/test_cli.py`
- `tests/test_examples.py`
- `tests/test_awf_role.py`
- `docs/tasks/windows-python312-utf8-closeout-implementation-report.md`

No path outside the five frozen TaskCard allowed paths changed after the TaskCard commit.

## Delivered Behavior

- Production JSON-schema and YAML/JSON resource reads now declare `encoding="utf-8"`.
- The directly relevant example-resource helper also reads YAML as UTF-8.
- The CLI subprocess helper removes inherited `PYTHONUTF8`, sets child
  `PYTHONIOENCODING=utf-8`, and decodes captured output explicitly as UTF-8.
- The quoted tracked-filename regression remains active on filesystems that support `"` and skips
  only on Windows, before attempting to create the illegal filename.
- A committed safe `café secret.py` fixture is staged with the existing constructed GitHub-token
  fixture and rejected by the real NUL-safe delta collection plus per-known-path tracked diff scan.
  The test does not mock paths, parse patch headers, or add Windows-only production behavior.

## Local Verification

The local verification environment used Python `3.12.13`. `PYTHONUTF8` was explicitly absent from
the verification process (`PYTHONUTF8_PRESENT False`). A controlled subprocess reported UTF-8
stdout and round-tripped non-ASCII text successfully.

- Focused changed-area regression: `20 passed`.
- Full suite: `161 passed`.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: `14 files already formatted`.
- `python -m agent_workflow.cli validate roles`: `6/6 passed`.
- `python -m agent_workflow.cli validate workflows`: `4/4 passed`.
- `python -m agent_workflow.cli validate examples`: `3/3 passed`.
- `git diff --check`: passed.

The verification used a temporary isolated environment with only the repository's declared
runtime and development dependencies. It did not connect to Agent Bus, Windows, a VPS, a listener,
or any historical event.

## Fresh Windows Acceptance Gate

This section is intentionally pending; local macOS evidence is not a substitute for the required
fresh Windows proof. After explicit authorization, the trusted runner must use a fresh isolated
Windows checkout at the exact pushed task-branch SHA and record:

1. Exact output of `py -3.12 --version` (the Windows Python version is not yet claimed).
2. Independent proof that `PYTHONUTF8` is absent from the verification process.
3. `python -m pytest -v` passing the full suite, including a Windows skip for only the quoted
   filename test and a pass for the Unicode/space tracked-path secret scan.
4. `python -m ruff check .` and `python -m ruff format --check .` passing.
5. Resource validation totals of `6/6 roles`, `4/4 workflows`, and `3/3 examples`.
6. A clean postflight result with exactly the five allowed paths and all seven frozen commands.
7. The exact final pushed implementation/report SHA and remote-SHA equality evidence.

Until those fields are appended from the real trusted-runner output, Windows acceptance remains
unproven and this task is not ready for merge.

## Review and Remaining Risks

- Local strong review found no scope, encoding-contract, path-safety, or scanner-bypass defect.
- Independent review and fresh Windows Python 3.12 acceptance remain required.
- The Windows default-locale path is the central residual risk; only the real environment can prove
  that no implicit locale-dependent read or subprocess decode remains.
- No event was dispatched, read, consumed, acknowledged, or requeued. Historical events `49`,
  `50`, `51`, and `52`, their two evidence branches, the historical Windows checkouts, and the
  detached dirty postflight worktree were not modified or deleted.
- No remote branch was updated, and no push, PR, merge, branch deletion, VPS change, listener
  operation, or Agent Bus change was performed.
