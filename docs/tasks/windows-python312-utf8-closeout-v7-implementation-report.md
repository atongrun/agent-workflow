# Implementation Report: Windows Python 3.12 UTF-8 Closeout v7

## Python version

- Runner: Windows Python 3.12.10 (tags/v3.12.10:0cc8128, Apr 8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
- Launcher: `py -3.12 --version` reports `Python 3.12.10`

## PYTHONUTF8-absent proof

The closeout does not globally set or prefix `PYTHONUTF8`.
Trusted proof that children run without forced UTF-8 mode is encoded in the
suite itself:

- `tests/test_cli.py::run_awf` builds a fresh child environment, explicitly
  removes `PYTHONUTF8`, and sets `PYTHONIOENCODING=utf-8` before invoking the
  CLI as bytes decoded as UTF-8.
- `tests/test_awf_role.py::test_verification_env_strips_credentials_and_pythonutf8`
  asserts `PYTHONUTF8` is absent from `verification_env()`.
- `tests/test_awf_role.py::test_verification_child_runs_without_pythonutf8` runs a
  real verification child and asserts `'PYTHONUTF8' not in os.environ` while
  `PYTHONIOENCODING` remains `utf-8`.

## Exact verification results

All trusted commands executed against the edited checkout:

| Command | Result |
|---|---|
| `py -3.12 --version` | Python 3.12.10 |
| `python -m pytest -v` | 162 passed, 1 skipped (only the Windows-invalid quoted-filename skip) |
| `python -m ruff check .` | All checks passed! |
| `python -m ruff format --check .` | 14 files already formatted |
| `python -m agent_workflow.cli validate roles` | PASS |
| `python -m agent_workflow.cli validate workflows` | PASS |
| `python -m agent_workflow.cli validate examples` | PASS |

## Changed paths

Exactly the five allowed paths differ from the frozen TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-v7-implementation-report.md`

## Risks

- `PYTHONUTF8` may still be present in the parent shell environment; the fix
  relies on the child-environment hygiene added to `run_awf` and
  `verification_env()` rather than mutating the parent process.
- On Windows, the dispatch test locates Git's `usr/bin/bash.exe` from the Git
  executable or common Program Files locations, with a PATH fallback. If Git is
  installed elsewhere and not on PATH, the fallback could fail.
- The quoted-filename regression (`test_secret_scan_quoted_tracked_filename`) is
  skipped on Windows because `a"b.py` is not a valid Windows file name; the
  new Windows-valid Unicode-and-space tracked filename test (`café token.py`)
  preserves real secret-scan coverage on this platform.

## Commit and review handling

The trusted runner assigns the commit after this report and records its exact
SHA in durable evidence/review payload. Review is pending at creation.
