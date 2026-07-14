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
- Windows OpenCode v1.17.13 parser smoke: without the boundary, the prompt failed as
  `File not found: parser-bad`; with `--`, parsing advanced to the expected
  `Model not found: invalid-provider/invalid-model` failure.
- Windows Python 3.12.10 on isolated checkout
  `D:\Work\AI\01_Project\agent-workflow-opencode-boundary-task6`: the five selected OpenCode
  adapter tests passed, Ruff check passed, and both changed Python files passed Ruff format.
- The complete Windows `tests/test_awf_role.py` run produced `73 passed, 1 failed`; its sole
  failure was the already documented, out-of-scope `a"b.py` filename that Windows forbids. That
  regression is the blocked UTF-8 TaskCard's work and was not mixed into this prerequisite.

## Remaining risks

The implementation changes only argv construction. Final confidence depends on GitHub CI
completing successfully. Full-tree formatting remains a known baseline issue in unchanged
`scripts/awf_listen.py`; the files in this TaskCard are formatted. The complete Windows role-test
file will remain red on the known invalid quoted filename until the separate UTF-8 TaskCard lands.

## Final commit

Implementation commit: `1cf3800718bca3421b94fb6fa5c6cc4b03db4f64`.
