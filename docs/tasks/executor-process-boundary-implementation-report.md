# ImplementationReport: Executor process boundary and fail-closed handoff

## Summary

Closed four P0 gaps in the trusted role runner (`scripts/awf_role.py`):

1. **Model-process credential boundary** — added `model_env()` that strips `AGENT_BUS_TOKEN`, `AGENT_BUS_AGENT_TOKENS`, and every `AWF_*_TOKEN` from the environment before spawning OpenCode/Codex subprocesses, while preserving PATH, ordinary `AWF_*` config, and UTF-8 settings. All three model adapters (`tool_opencode_exec`, `tool_codex_review`, `tool_opencode_review`) now pass `env=model_env()`.

2. **Closed stdin for non-interactive subprocesses** — modified `spawn()` to set `stdin=subprocess.DEVNULL` when no explicit text input is provided, and added `stdin=subprocess.DEVNULL` to `git_out()`. The Codex reviewer path that sends prompt text via `input=` is unaffected (no `DEVNULL` when `stdin` parameter is provided). The `send_event()` helper also uses `stdin=subprocess.DEVNULL` for its own `subprocess.run` call.

3. **ImplementationReport gate** — added `check_report()` that fails if `--report` is empty or the path is not a regular file. Called in `role_coder()` after the tool succeeds but before `git add`/commit/push/`send_event`, and in `role_reviewer()` after checkout but before any model invocation.

4. **Fail-closed reviewer handoff** — `role_coder()` now checks the boolean result of `send_event()` for `task:awf-review` and calls `die(...)` on failure, producing a non-zero exit so the current implementation event is not ACKed. Successful send still returns 0.

### Deterministic review rework

All five rework items from the deterministic review were applied on top:

1. `send_event()` now passes `stdin=subprocess.DEVNULL` and has a focused assertion at that subprocess boundary.
2. Credential-boundary tests now exercise all three adapter paths (`tool_opencode_exec`, `tool_codex_review`, `tool_opencode_review`) and inspect the env passed to `spawn()`, proving every model path uses the filtered environment. The Codex prompt-input assertion is preserved at the adapter level.
3. Reviewer missing-report coverage is parameterized for both Codex and OpenCode.
4. `check_report()` docstring corrected to state: coder checks after model execution, reviewer checks before model execution.
5. ImplementationReport updated with exact final command results and three-file-change set.

## Files Changed

| File | Change |
|------|--------|
| `scripts/awf_role.py` | Added `model_env()`, `check_report()`. Modified `spawn()`, `git_out()`, `send_event()`, `tool_opencode_exec()`, `tool_codex_review()`, `tool_opencode_review()`, `role_coder()`, `role_reviewer()`. Revert: fixed `check_report()` docstring to reflect coder-vs-reviewer timing. |
| `tests/test_awf_role.py` | Added 10 original + 4 rework regression tests covering all four gaps + existing test preservation. Notable additions: three adapter-boundary credential tests, `send_event()` stdin assertion, parameterized reviewer missing-report (Codex + OpenCode). |
| `docs/tasks/executor-process-boundary-implementation-report.md` | This file. |

## Verification Commands and Results

```bash
.venv\Scripts\python.exe -m pytest -q tests/test_awf_role.py
```
→ 20 passed in 8.57s (5 existing checkout-sync + 10 original + 3 new adapter credential tests + 1 send_event stdin test + 1 parameterized reviewer test variant)

```bash
.venv\Scripts\python.exe -m ruff check scripts/awf_role.py tests/test_awf_role.py
```
→ All checks passed!

```bash
.venv\Scripts\python.exe -m ruff format --check scripts/awf_role.py tests/test_awf_role.py
```
→ 2 files already formatted

```bash
git diff --check
```
→ No whitespace errors

```bash
git status --short
```
→ ```
 M scripts/awf_role.py
 M tests/test_awf_role.py
?? docs/tasks/executor-process-boundary-implementation-report.md
```

```bash
git diff --name-only HEAD
```
→ ```
scripts/awf_role.py
tests/test_awf_role.py
```
(The report file is new/untracked; it will be committed by the trusted runner.)

## Deviations or Unresolved Failures

None. All 20 tests pass, all acceptance criteria are met, and only the three allowed files differ from the dispatched commit (two modified tracked files + one untracked report file).

## Starting Commit

`baea8f9` — `chore(awf): make the next P0 executable across the trust boundary`

## Final Local Commit

Not committed yet (branch policy: trusted runner commits after confirming this report exists).
