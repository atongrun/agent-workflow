# Implementation Report: Postflight completion contract

## Summary

Added a fail-closed postflight gate to the trusted coder runner (`scripts/awf_role.py`). The runner now parses and freezes the `awf-postflight` contract from the TaskCard before the model starts, then independently validates the resulting worktree after the model succeeds and the ImplementationReport gate passes, before any `git add`, commit, push, or reviewer event.

### Deterministic Rework (Round 2)

The first implementation commit was rejected by review. Five deterministic fixes were applied:

1. **Full HEAD delta** — Secret scan and `git diff --check` now inspect staged + unstaged changes (via `git diff HEAD`), not only unstaged.
2. **NUL-safe path snapshot** — `_collect_delta_paths()` uses NUL-delimited git output (`-z`) instead of text porcelain + `shlex`, safely handling spaces, Unicode, and quoted paths. The snapshot is reused by all path-dependent gates.
3. **Artifact match at any depth** — `_is_env_denied()` matches `.env` variants by basename; `_path_is_denied()` matches directory denials (`node_modules/`, `.venv/`, etc.) by path component at any depth.
4. **Fail closed on unreadable untracked files** — The untracked file read loop no longer silently catches all exceptions; an `OSError` fails the gate with a safe `unreadable-file` label.
5. **Reject empty executable** — `parse_postflight_contract()` rejects any empty string in `verification_commands` arrays (e.g., `[""]`).

Trusted integration then closed two review-proven edge cases without another model rework: tracked
files are scanned one path at a time with `--no-textconv --no-ext-diff`, so quoted filenames cannot
lose path attribution and configured diff helpers cannot hide content or execute. Exact artifact
names are denied by basename at any depth. Empty non-executable argv values remain valid.

Self-hosting: token/key test fixtures are constructed from fragments so the postflight secret gate does not reject its own uncommitted test diff.

### Exact gate ordering

1. **Preflight checkout** — `fetch_and_checkout` (unchanged)
2. **Parse and freeze postflight contract** — `parse_postflight_contract()` extracts the `awf-postflight` JSON block from the TaskCard HTML comment, validates it, replaces `{python}` with `sys.executable`, and returns a frozen `PostflightContract` object. The card file is deliberately absent from `allowed_paths`, so model edits to it fail the path gate rather than changing the contract.
3. **OpenCode execution** (unchanged)
4. **ImplementationReport existence gate** — `check_report()` (unchanged)
5. **Focused verification rerun** — `run_verifications()` executes every frozen verification command in order via `spawn()` with `model_env()` (credential-stripped). Stops at first non-zero exit.
6. **Delta gates** — `run_postflight_delta_gates()` performs:
   - Empty-change-set rejection
   - `allowed_paths` enforcement (every changed path must be in the frozen contract)
   - Artifact denylist (`.env` variants at any depth by basename, `node_modules/`/`.venv/`/`__pycache__`/`build/`/etc. at any depth by component, editor swap/backup, OS metadata, Python cache, coverage, logs/PIDs, dependency/build output — even if accidentally in `allowed_paths`)
   - Narrow secret scan (full HEAD diff, staged + unstaged tracked files scanned per NUL-safe known path with textconv/external diff disabled, plus NUL-safe untracked scan; private-key headers, credential URLs, GitHub tokens, OpenAI keys, AWS access keys; label-only reporting, never the matched value; fails closed on unreadable files)
   - `git diff HEAD --check` whitespace error detection (staged + unstaged)
7. **git add, commit, optional push** (unchanged)
8. **task:awf-review event send** (unchanged)
9. **return 0** (unchanged)

Any postflight failure (steps 2, 5, 6) raises `SystemExit(1)` before step 7, leaving the worktree untouched and preventing all downstream writes and events.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `scripts/awf_role.py` | Modified (rework) | `_collect_delta_paths()` uses NUL-delimited Git output. Artifact names and directory patterns match at any depth. `_narrow_secret_scan()` scans tracked files per known path with textconv/external diff disabled and scans untracked paths NUL-safely; unreadable files fail closed. Contract parsing rejects only an empty executable. `run_postflight_delta_gates()` uses `git diff HEAD --check`. |
| `templates/artifacts/task-card.md` | Modified (first round) | Added `awf-postflight` HTML comment block at the end of the template with `allowed_paths` and `verification_commands` JSON structure. |
| `tests/test_awf_role.py` | Modified (rework) | Added focused regression tests for staged deltas, special/Unicode paths, nested artifacts, unreadable files, empty executable handling, whitespace, and disabled diff helpers. Token/key fixtures are fragmented for self-hosting. |
| `docs/tasks/postflight-completion-implementation-report.md` | Updated (rework) | This file — rework findings, updated gate descriptions, final test results. |

## Verification Commands and Results

```
{python} -m pytest -q tests/test_awf_role.py
72 passed
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

**72 total focused tests**, all passing. Full suite: **106 passed**.

### New test coverage (rework round):

| Category | Tests | What they prove |
|----------|-------|-----------------|
| Staged HEAD delta secrets | 2 | Staged tracked file with secret caught; staged new file with secret caught |
| NUL-safe delta paths | 3 | Spaced rename both sides captured; spaced untracked file with secret caught; Unicode path captured |
| Nested artifact denial | 1 | Directory patterns denied at any depth; `.env` variants denied by basename at any depth; documented examples allowed at any depth |
| Unreadable untracked file | 1 | `OSError` on untracked file read fails closed with safe `unreadable-file` label |
| Empty executable rejection | 2 | `[""]` fails contract parsing; an empty non-executable argv value remains valid |
| Quoted paths and diff helpers | 2 | A quoted tracked filename cannot bypass scanning; tracked scans disable textconv and external diff |
| Patch-header distinction | 1 | An added source line beginning with `++` is scanned after the hunk marker |
| Staged whitespace rejection | 1 | Staged trailing whitespace caught by `git diff HEAD --check` |
| Self-hosting fixtures | (pervasive) | All secret-like test strings constructed from fragments; no literal secret in test source |

## Deviations

The trusted integrator applied two deterministic strong-review corrections after the single model
rework. This did not expand the TaskCard scope.

## Unresolved Failures

None.

## Source Revision

- **Starting event commit:** `5ea111da9c71d860cfa0e7d60d4058877a6875ea` (chore(awf): make trusted postflight executable)
- **Windows executor rework commit:** `1a9d922e642f05bbc031fe18545572c9425343f2`
