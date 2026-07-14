# OpenCode file-array boundary implementation report

## Files changed

- `scripts/awf_role.py`
- `tests/test_awf_role.py`
- `docs/tasks/opencode-file-array-boundary-implementation-report.md`

## Argv contract

Before this change, the executor and OpenCode reviewer appended the prompt directly after the
last OpenCode option. Because OpenCode v1.17.13 parses `--file` as an array option, the no-model
form `-f <card> <prompt>` could consume the prompt as a second file path.

Both adapters now finish assembling the existing `--dir`, optional `-f`, and optional `-m`
options, then append the literal `--` followed by the prompt as the single final positional
message. The TaskCard remains the sole `-f` value and model selection remains an `-m` option.

## Verification

- Focused adapter tests: `74 passed` on macOS with Python 3.11.15.
- Full pytest suite: `108 passed` on macOS with Python 3.11.15.
- Ruff check: passed.
- Ruff format check for the two changed Python files: passed. The requested full-tree format
  check also ran and reported only the unchanged `scripts/awf_listen.py` from `origin/main`; that
  pre-existing, out-of-scope file was not modified.
- Resource validation: `6/6 roles`, `4/4 workflows`, and `3/3 examples` passed.
- Independent strong review: approved with no findings; its focused rerun also passed all 74
  adapter tests, Ruff check, Ruff format check, and `git diff --check`.
- Windows OpenCode v1.17.13 parser smoke: completed before implementation; `--` advanced beyond
  file parsing to the expected invalid-model failure. Windows focused tests remain pending.

## Remaining risks

The implementation changes only argv construction. Final confidence depends on the required
Windows focused test run and CI completing successfully. Full-tree formatting remains a known
baseline issue in unchanged `scripts/awf_listen.py`; the files in this TaskCard are formatted.

## Final commit

Pending leader commit.
