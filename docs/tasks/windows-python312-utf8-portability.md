# TaskCard: Windows Python 3.12 UTF-8 and portable path regressions

## Goal

Make the current Agent Workflow resource validation and regression suite pass on Windows
Python 3.12 without requiring an externally configured `PYTHONUTF8` variable. Preserve the
postflight secret scanner's quoted-Git-path security coverage on POSIX and add a Windows-valid
portable tracked-path regression that exercises the same NUL-safe known-path scan.

## Fixed baseline and execution environment

- Repository: `atongrun/agent-workflow`.
- Task branch: `codex/windows-python312-utf8`.
- The exact dispatched commit in the Agent Bus event is authoritative. The trusted runner must
  fetch it and verify `origin/codex/windows-python312-utf8` still resolves to that commit before
  OpenCode starts.
- Execute on the isolated Windows checkout already assigned to this handoff. Do not reset, clean,
  or modify any historical checkout. Preserve every unrelated dirty or untracked file.
- Use Windows `py -3.12` / Python 3.12. The full verification must run without setting
  `PYTHONUTF8`; remove it from the verification process environment if it is inherited.
- Do not process old Agent Bus events.

## Evidence behind this task

On Windows Python 3.12.10, a fresh `.[dev]` environment produced `95 passed, 11 failed` without
`PYTHONUTF8`. Ten failures came from default-GBK decoding of UTF-8 YAML or CLI output. With
`PYTHONUTF8=1`, only `test_secret_scan_quoted_tracked_filename` failed because Windows forbids
`"` in filenames.

The current review found:

1. `src/agent_workflow/validation.py` opens JSON schemas and YAML/JSON resources without an
   explicit encoding.
2. `tests/test_examples.py` opens YAML without an explicit encoding.
3. `tests/test_cli.py::run_awf` captures text without an explicit encoding contract.
4. `tests/test_awf_role.py::test_secret_scan_quoted_tracked_filename` creates `a"b.py` on every
   platform. The existing Unicode-path test only checks delta collection; it does not prove a
   tracked Unicode/space path reaches per-known-path secret scanning.
5. The production postflight scanner already obtains NUL-delimited paths and scans tracked
   changes by the known path with `--no-textconv`, `--no-ext-diff`, and `--`; do not redesign it.

## Allowed paths

Only these files may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-portability-implementation-report.md` (create)

This TaskCard is already committed and must not be edited.

## Required implementation

### 1. Explicit UTF-8 resource reads

- Make schema and YAML/JSON production reads in `validation.py` explicitly use UTF-8.
- Make the directly relevant YAML test helper explicitly use UTF-8.
- Make the CLI subprocess test helper use an explicit UTF-8 text contract for captured output;
  ensure the child CLI output and the parent decoder agree without relying on external
  `PYTHONUTF8` state.
- Keep the change local and literal. Do not add an encoding abstraction, locale framework,
  dependency, or broad rewrite of unrelated test file writes.

### 2. Portable postflight path coverage

- Keep `test_secret_scan_quoted_tracked_filename` active on platforms whose filesystems allow a
  double quote. Skip it narrowly on Windows before attempting to create the invalid filename,
  with a reason that describes the filesystem constraint. Do not weaken the assertion on POSIX.
- Add one Windows-valid tracked-path regression using a portable difficult path (Unicode and/or
  spaces). Commit a safe version, modify/stage that exact path with the existing constructed test
  GitHub-token fixture, and assert `_narrow_secret_scan()` fails.
- The test must exercise the real Git path collection and real per-known-path tracked diff scan.
  It must demonstrate the scanner does not parse or trust a human-readable patch header. Do not
  mock the path list, do not replace the scanner, and do not add Windows-only production logic.
- Preserve the existing `++` added-line and diff-helper regressions.

### 3. Minimal regression tests and report

- Add only the smallest tests needed to lock explicit UTF-8 behavior and portable path handling.
- Create the implementation report with: files changed, why each change is necessary, exact
  Windows Python version, confirmation that `PYTHONUTF8` was absent, verification outputs,
  remaining risks, and the final commit SHA if available.

## Acceptance criteria

- Production schema/resource reads are UTF-8 regardless of Windows locale.
- CLI/test helper decoding is explicit and agrees with child output without external
  `PYTHONUTF8`.
- POSIX retains the double-quote Git-path regression.
- Windows never tries to create the illegal quoted filename.
- A Windows-valid tracked Unicode/space path carrying a secret is rejected through the actual
  NUL-safe known-path scan.
- Windows Python 3.12 passes the full suite, Ruff, formatting check, and all resource validation
  without `PYTHONUTF8`.
- No dependency or out-of-scope feature is added.
- Only the five allowed paths differ from the dispatched TaskCard commit.

## Forbidden work

- Push-handoff enforcement or remote-SHA verification changes.
- Reviewer verdict routing, Agent Host, Agent Bus changes, idempotency/claim/lease, services,
  logs/status/UI, policy engines, plugins, or a generic encoding framework.
- Resetting/cleaning any checkout, deleting an unrelated file, handling old queue events, or
  using a Git bundle as handoff.

## Required verification

Run these through the trusted runner in this exact task environment. `PYTHONUTF8` must be absent;
do not prefix the commands with `PYTHONUTF8=1` or set it globally.

```text
py -3.12 --version
python -m pytest -v
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
```

Expected resource totals are `6/6 roles`, `4/4 workflows`, and `3/3 examples`.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/validation.py",
    "tests/test_cli.py",
    "tests/test_examples.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-python312-utf8-portability-implementation-report.md"
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
