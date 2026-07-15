# TaskCard: Windows Python 3.12 UTF-8 portability final rerun

## Goal

Make Agent Workflow resource validation and its regression suite pass on Windows Python 3.12
without an externally configured `PYTHONUTF8` variable. Preserve the postflight secret scanner's
quoted-Git-path coverage on POSIX and add a Windows-valid tracked-path regression through the same
NUL-safe known-path scan.

## Fixed baseline and execution environment

- Repository: `atongrun/agent-workflow`.
- Base branch: `main`.
- Task branch: `codex/windows-python312-utf8-rerun`.
- The exact dispatched TaskCard commit is authoritative. Before OpenCode starts, the trusted
  runner must fetch the task branch and prove its refreshed remote SHA equals that commit.
- Execute only in a fresh Windows checkout created for this event. Do not reset, clean, delete, or
  modify any historical checkout, including prior task5, task7, and task8 evidence.
- Do not reuse, cherry-pick, copy, or manually push any prior failed implementation or commit.
- Use Windows `py -3.12` / Python 3.12. The complete verification must run with `PYTHONUTF8`
  absent from the process environment.
- Process only the newly dispatched Agent Bus event. Do not process or revive old events.

## Evidence behind this task

Prior clean Windows Python 3.12 verification without `PYTHONUTF8` isolated these portability
gaps:

1. `src/agent_workflow/validation.py` reads UTF-8 JSON schemas and YAML/JSON resources without an
   explicit encoding.
2. `tests/test_examples.py` reads YAML without an explicit encoding.
3. `tests/test_cli.py::run_awf` captures text without making the child output and parent decoder
   agree on UTF-8.
4. `tests/test_awf_role.py::test_secret_scan_quoted_tracked_filename` creates a filename containing
   `"`, which Windows filesystems reject. Existing Unicode-path coverage does not prove that a
   tracked Unicode/space path reaches the per-known-path secret scan.
5. The production postflight scanner already uses NUL-delimited Git paths and scans each known
   path with `--no-textconv`, `--no-ext-diff`, and `--`; it must not be redesigned.

## Allowed paths

Only these files may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-portability-rerun-implementation-report.md` (create)

This TaskCard is frozen by its dispatched commit and must not be edited by the implementer.

## Required implementation

### 1. Explicit UTF-8 resource reads

- Make schema and YAML/JSON production reads in `validation.py` explicitly use UTF-8.
- Make the directly relevant YAML test helper explicitly use UTF-8.
- Give the CLI subprocess test helper an explicit UTF-8 output/decoding contract that does not
  depend on inherited `PYTHONUTF8` state.
- Keep the changes local and literal. Do not add an encoding abstraction, locale framework,
  dependency, or unrelated rewrite.

### 2. Portable postflight path coverage

- Keep `test_secret_scan_quoted_tracked_filename` active where the filesystem permits `"`.
  Skip it narrowly on Windows before creating the invalid filename, with a filesystem-specific
  reason. Do not weaken its POSIX assertion.
- Add one portable tracked-path regression using a Windows-valid difficult path containing
  Unicode and/or spaces. Commit a safe version, modify or stage that exact path with the existing
  constructed GitHub-token fixture, and assert `_narrow_secret_scan()` fails.
- Exercise real Git path collection and the real per-known-path tracked diff scan. Do not mock the
  path list, parse a human-readable patch header, replace the scanner, or add Windows-only
  production logic.
- Preserve the existing plus-prefixed-line and diff-helper regressions.

### 3. Minimal report

Create the implementation report with the files changed, why each change is required, exact
Windows Python version, proof that `PYTHONUTF8` was absent, exact verification results, remaining
risks, and final implementation commit SHA if available.

## Acceptance criteria

- Production schema/resource reads are UTF-8 regardless of Windows locale.
- CLI test output encoding and parent decoding agree without external `PYTHONUTF8`.
- POSIX retains the quoted-path regression; Windows never attempts the illegal filename.
- A Windows-valid tracked Unicode/space path containing a secret is rejected through the actual
  NUL-safe known-path scan.
- Windows Python 3.12 passes the full pytest suite, Ruff check, Ruff format check, and resource
  validation with `PYTHONUTF8` absent.
- No dependency or out-of-scope feature is added.
- Only the five allowed paths differ from this dispatched TaskCard commit.

## Forbidden work

- Any prior task8 implementation, commit, patch, checkout, or branch content.
- Push-handoff or remote-SHA gate changes.
- Reviewer verdict routing, Agent Host, Agent Bus abstractions, services, UI, policy engines,
  idempotency/claim/lease work, plugins, or generic encoding frameworks.
- Resetting, cleaning, or deleting any checkout; handling old queue events; or manually completing
  a failed postflight, push, review-event, or ACK chain.

## Required verification

Run these through the trusted runner in this exact environment. `PYTHONUTF8` must be absent; do
not prefix commands with `PYTHONUTF8=1` or set it globally.

```text
py -3.12 --version
python -m pytest -v
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
```

Expected totals are `6/6 roles`, `4/4 workflows`, and `3/3 examples`.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/validation.py",
    "tests/test_cli.py",
    "tests/test_examples.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-python312-utf8-portability-rerun-implementation-report.md"
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
