# Implementation Report: Windows Python 3.12 UTF-8 Closeout v4

## Python Version

```
Python 3.12.10
```

## Trusted `PYTHONUTF8`-absent Proof

Verified via `test_verification_child_runs_without_pythonutf8` assertion:
- Child process confirms `PYTHONUTF8` is not in environment
- `PYTHONIOENCODING=utf-8` is retained for UTF-8 output

## Changes Made

### 1. `src/agent_workflow/validation.py`
- Added `encoding="utf-8"` to `open()` calls in `_load_schema()` and `_parse_yaml_or_json()`
- No abstraction or dependency added per TaskCard requirement

### 2. `tests/test_examples.py`
- Added `encoding="utf-8"` to `open()` call in `_load_yaml_file()`

### 3. `tests/test_cli.py`
- Added `import os`
- Modified `run_awf()` to copy environment, remove `PYTHONUTF8`, set `PYTHONIOENCODING=utf-8`, decode with explicit `encoding="utf-8"`, and pass the custom `env`

### 4. `tests/test_awf_role.py`

#### a. `test_secret_scan_quoted_tracked_filename` — Windows skip
- Added `if os.name == "nt": pytest.skip('a"b.py is illegal on Windows')` before file creation

#### b. `test_minimal_listener_handler_opencode_return_chain` — Agent Bus shim
- Kept `.cmd`/script shim (`fake_tool`) only for `AWF_OPENCODE_BIN` (model-tool boundary)
- Created plain Python script named `send` in handler `cwd` (executor dir) with `sys.exit(0)`
- Excluded `send` via `.git/info/exclude` to keep worktree clean
- Set `AWF_BUS_BIN` to `sys.executable` so production runs `python.exe send ...`

#### c. `test_dispatch_dry_run_carries_distinct_default_report_paths` — MSYS path
- Added `_git_bash()` helper to locate Git Bash reliably (derives from `git` location, checks common paths, falls back to `shutil.which`)
- Added `_msys_path()` helper to convert `D:\path` → `/d/path` for Git Bash
- Converted both the dispatch script path and the repo path to MSYS form
- Captured binary output and decoded as UTF-8 with `errors="replace"`

#### d. `test_secret_scan_windows_valid_unicode_space_path` — New regression test
- Creates a tracked path `my secret café.txt` (Unicode + space)
- Commits safe version, stages GitHub token fixture
- Asserts `_narrow_secret_scan()` raises `SystemExit(1)` — no mocking of path collection or scanning

## Command Results

| Command | Result |
|---------|--------|
| `py -3.12 --version` | Python 3.12.10 |
| `python -m pytest -v` | 162 passed, 1 skipped (intentional Windows quoted-filename) |
| `python -m ruff check .` | All checks passed |
| `python -m ruff format --check .` | 14 files already formatted |
| `python -m agent_workflow.cli validate roles` | 6/6 passed |
| `python -m agent_workflow.cli validate workflows` | 4/4 passed |
| `python -m agent_workflow.cli validate examples` | 3/3 passed |

## Changed Files

```
src/agent_workflow/validation.py
tests/test_awf_role.py
tests/test_cli.py
tests/test_examples.py
docs/tasks/windows-python312-utf8-closeout-v4-implementation-report.md
```

All 5 changes are within the TaskCard's allowed paths. No production listener/routing, Agent Bus, protocol, storage, auth, or service changes were made.

## Implementation SHA

Pending commit.

## Review Result

Pending independent review.

## Remaining Risks

- The `_git_bash()` heuristic relies on common Git for Windows install paths. Alternative Git Bash installations (e.g., portable, Scoop, Chocolatey) may need path additions.
- The MSYS path conversion assumes drive-letter paths on Windows. Non-drive paths (UNC paths, network shares) are not handled but are not used in tests.
- The `.git/info/exclude` approach for the `send` script is local-only (not committed), so a fresh clone would not have the exclusion. This is acceptable because the `send` script is only created during the test, not during production.
