# Implementation Report: Postflight completion contract

## Summary

Added a fail-closed postflight gate to the trusted coder runner (`scripts/awf_role.py`). The runner now parses and freezes the `awf-postflight` contract from the TaskCard before the model starts, then independently validates the resulting worktree after the model succeeds and the ImplementationReport gate passes, before any `git add`, commit, push, or reviewer event.

### Exact gate ordering

1. **Preflight checkout** — `fetch_and_checkout` (unchanged)
2. **Parse and freeze postflight contract** — `parse_postflight_contract()` extracts the `awf-postflight` JSON block from the TaskCard HTML comment, validates it, replaces `{python}` with `sys.executable`, and returns a frozen `PostflightContract` object. The card file is deliberately absent from `allowed_paths`, so model edits to it fail the path gate rather than changing the contract.
3. **OpenCode execution** (unchanged)
4. **ImplementationReport existence gate** — `check_report()` (unchanged)
5. **Focused verification rerun** — `run_verifications()` executes every frozen verification command in order via `spawn()` with `model_env()` (credential-stripped). Stops at first non-zero exit.
6. **Delta gates** — `run_postflight_delta_gates()` performs:
   - Empty-change-set rejection
   - `allowed_paths` enforcement (every changed path must be in the frozen contract)
   - Artifact denylist (`.env` variants, editor swap/backup, OS metadata, Python cache, coverage, logs/PIDs, virtual environments, dependency/build output — even if accidentally in `allowed_paths`)
   - Narrow secret scan (private-key headers, credential URLs, GitHub tokens, OpenAI keys, AWS access keys — in tracked diff added lines and untracked files; label-only reporting, never the matched value)
   - `git diff --check` whitespace error detection
7. **git add, commit, optional push** (unchanged)
8. **task:awf-review event send** (unchanged)
9. **return 0** (unchanged)

Any postflight failure (steps 2, 5, 6) raises `SystemExit(1)` before step 7, leaving the worktree untouched and preventing all downstream writes and events.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `scripts/awf_role.py` | Modified | Added `PostflightContract`, `parse_postflight_contract()`, `run_verifications()`, `_collect_delta_paths()`, `run_postflight_delta_gates()`, `_narrow_secret_scan()`, `_path_is_denied()`, denylist constants, secret detectors; integrated into `role_coder()` in the required order. Fixed `git_out()` to use `rstrip` vs `strip` to preserve porcelain leading space. |
| `templates/artifacts/task-card.md` | Modified | Added `awf-postflight` HTML comment block at the end of the template with `allowed_paths` and `verification_commands` JSON structure. |
| `tests/test_awf_role.py` | Modified | Updated 3 existing `role_coder` integration tests to include valid contract blocks and postflight mocks; added 39 new focused regression tests. |
| `docs/tasks/postflight-completion-implementation-report.md` | Created | This file. |

## Verification Commands and Results

```
{python} -m pytest -q tests/test_awf_role.py
59 passed in 9.65s
```

```
{python} -m ruff check scripts/awf_role.py tests/test_awf_role.py
All checks passed (no output).
```

```
{python} -m ruff format --check scripts/awf_role.py tests/test_awf_role.py
All formatting checks passed (no output).
```

## Focused Test Count

**59 total tests** (20 existing + 39 new), all passing.

### New test coverage:

| Category | Tests | What they prove |
|----------|-------|-----------------|
| Contract parsing (valid) | 3 | Valid contract parses, freezes against card edits, `{python}` replacement only at position 0 |
| Contract validation | 11 | Missing block, malformed JSON, non-object, extra keys, empty paths, backslash, absolute, drive-qualified, parent-traversal, duplicate, empty commands, non-string argv |
| Artifact denylist | 1 | Every category rejected, documented examples allowed |
| Delta collection | 4 | Modified, deleted, untracked, renamed files appear in delta |
| Delta gates | 4 | Empty set, out-of-scope path, denied artifact, `git diff --check` |
| Secret scan | 8 | Private key, credential URL, GitHub token, OpenAI key, AWS key in tracked diffs; secret in untracked file; benign placeholders pass; test fixtures pass |
| Verification commands | 3 | Success, stop-on-first-failure, uses `model_env()` |
| Verification-created files | 1 | Files created by verification subject to path/artifact checks |
| Full postflight | 1 | Valid sequence passes all gates (real git repo, real subprocess) |
| Verification failure isolation | 1 | Non-zero verification prevents downstream git writes |

## Deviations

None. Implementation follows the TaskCard exactly.

## Unresolved Failures

None.

## Source Revision

- **Starting event commit:** `5ea111da9c71d860cfa0e7d60d4058877a6875ea` (chore(awf): make trusted postflight executable)
- **Final local commit:** Not yet committed (will be after implementation handoff)
