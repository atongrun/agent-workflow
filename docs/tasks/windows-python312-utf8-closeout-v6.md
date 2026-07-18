# TaskCard: Complete Windows Python 3.12 UTF-8 closeout v6

## Goal

Make the full suite pass on a fresh Windows Python 3.12 checkout without `PYTHONUTF8` in trusted
verification children. Preserve the POSIX quoted-path regression and prove a staged, tracked,
Windows-valid Unicode-and-space path reaches the real known-path secret scanner.

## Frozen Baseline

- Base: `origin/main` at `f5f6a37f13e118241755c428a3041ae8a2d56915`.
- Branch: `codex/windows-python312-utf8-closeout-v6`.
- The dispatched SHA must equal this TaskCard commit exactly.
- Use a new isolated Windows checkout. Do not reuse any previous implementation, report, event, or
  checkout.

Preserve every earlier portability evidence branch/checkout/event. In particular, do not read,
consume, ACK, requeue, modify, reset, clean, or delete events 49-52, 73-77 or their checkouts.

## Allowed Paths

Only these paths may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-v6-implementation-report.md` (create)

Do not edit this frozen TaskCard.

## Required Implementation

Make only the following bounded edits. Do not add a second dispatch test or rename existing tests.

1. In `src/agent_workflow/validation.py`, add `encoding="utf-8"` to the existing `open(path)` calls
   in `_load_schema` and `_parse_yaml_or_json`.
2. In `tests/test_examples.py::_load_yaml_file`, add `encoding="utf-8"` to its existing open.
3. In `tests/test_cli.py::run_awf`, copy `os.environ`, remove `PYTHONUTF8`, set
   `PYTHONIOENCODING=utf-8`, and pass that env. Keep `text=True` and add `encoding="utf-8"` so
   captured output decodes explicitly.
4. In `test_secret_scan_quoted_tracked_filename`, skip only on Windows before attempting to create
   `a"b.py`; a `pytest.mark.skipif(os.name == "nt", ...)` on that test is acceptable.
5. In `test_minimal_listener_handler_opencode_return_chain`, keep the existing controlled `.cmd`
   only as `fake_tool` for `AWF_OPENCODE_BIN`. After that platform branch, at the test function's
   normal indentation, create `executor / "send"` (exactly `send`, no extension) as UTF-8 Python
   containing a deterministic zero exit. Write `send\n` to `.git/info/exclude` and set
   `AWF_BUS_BIN` to `sys.executable`. Production must run `python.exe send ...`. Do not create any
   bus `.cmd`, `.bat`, or `send.py`.
6. Modify the existing `test_dispatch_dry_run_carries_distinct_default_report_paths`; do not create
   another dispatch test. Import `shutil`. Add a helper that locates Git for Windows Bash by deriving
   `<Git install>/usr/bin/bash.exe` from `shutil.which("git")`, checking the common Program Files
   paths, then falling back to `shutil.which("bash")`. Add a helper converting drive paths to exact
   MSYS form: `D:\rest` becomes `/d/rest`. Invoke that explicit Git Bash executable with converted
   script and repo paths. Capture bytes and decode both streams with UTF-8 plus `errors="replace"`.
   Keep the existing assertions for distinct default implementation/review report paths.
7. Add one secret regression using a Windows-valid filename containing Unicode and a space. The
   exact sequence is mandatory: write safe content; `git add` exact name; commit; write the existing
   constructed `_GITHUB_TOKEN` fixture; run `git add` on that exact name again; assert the real
   `_narrow_secret_scan(str(repo))` raises `SystemExit(1)`. Do not mock scanning/path collection.
8. Preserve plus-prefixed-line, diff-helper, NUL-safe, and return-chain regressions.
9. Create the ImplementationReport with Python version, `PYTHONUTF8`-absent verification proof,
   exact command results, five changed paths, and remaining risks. The implementation commit is
   created by the trusted runner after the report is written, so record that the exact SHA is in the
   durable run evidence/review payload rather than inventing a self-referential SHA. Independent
   review is pending until after the trusted commit.

## Acceptance Criteria

- Fresh Windows Python 3.12 full suite: no deselection, only the narrow quoted-filename skip.
- Former listener-return and dispatch-path failures pass without production routing changes.
- Unicode-and-space secret test stages the secret-bearing exact path after the safe commit.
- Ruff passes; resource results are `6/6`, `4/4`, and `3/3`.
- Exactly the five allowed paths differ from this frozen commit.

## Required Verification

Run all seven commands through the trusted runner. Do not globally set or prefix `PYTHONUTF8`.

```text
py -3.12 --version
python -m pytest -v
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
```

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/validation.py",
    "tests/test_cli.py",
    "tests/test_examples.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-python312-utf8-closeout-v6-implementation-report.md"
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

## Forbidden Work

- Reusing or changing any earlier evidence.
- Production Agent Bus/listener/protocol/storage/auth/service/reviewer-routing changes, dependencies,
  Agent Host, UI, VPS, or real listener configuration changes.
- Manual postflight, implementation commit, push, review, or ACK outside the trusted runner.

## Closeout

After fresh Windows acceptance, independent strong review, CI, and PR merge, v6 is the accepted
closeout. Evidence deletion remains a separate retention decision.
