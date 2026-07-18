# TaskCard: Complete Windows Python 3.12 UTF-8 closeout v7

## Goal and Baseline

Complete the Windows Python 3.12 UTF-8 portability fix on a fresh checkout. Base is `origin/main`
at `f5f6a37f13e118241755c428a3041ae8a2d56915`; branch is
`codex/windows-python312-utf8-closeout-v7`. The dispatched SHA must equal this frozen TaskCard
commit. Do not reuse any earlier implementation, report, event, branch, or checkout.

Preserve all prior evidence. Do not read, consume, ACK, requeue, modify, reset, clean, or delete
events 49-52 or 73-78, their branches, or their checkouts.

## Allowed Paths

Only these five paths may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-v7-implementation-report.md` (create)

Do not edit this TaskCard.

## Exact Required Edits

- Add `encoding="utf-8"` to the two existing production resource opens in
  `src/agent_workflow/validation.py` and the existing YAML open in `tests/test_examples.py`.
- In `tests/test_cli.py::run_awf`, copy `os.environ`, remove `PYTHONUTF8`, set
  `PYTHONIOENCODING=utf-8`, pass that env, and explicitly decode with `encoding="utf-8"`.
- Narrowly skip `test_secret_scan_quoted_tracked_filename` on Windows before `a"b.py` creation.
- In `test_minimal_listener_handler_opencode_return_chain`, retain `.cmd` only for the model-tool
  shim. At normal function indentation create a UTF-8 Python file named exactly `send` in the
  executor cwd, append `send\n` to `.git/info/exclude`, and set `AWF_BUS_BIN=sys.executable`.
- Import `shutil`. Modify only the existing
  `test_dispatch_dry_run_carries_distinct_default_report_paths`. Locate Git for Windows
  `usr/bin/bash.exe` from the Git executable/common Program Files locations, with PATH fallback.
  Convert a resolved `D:\rest` path to exact `/d/rest` form, including the slash after the drive.
  Invoke the explicit Bash with converted script/repo paths. Capture bytes and decode both stdout
  and stderr using UTF-8 with `errors="replace"`; assigning the stderr decode to `_` is acceptable.
  Preserve the existing distinct default report-path assertions. Add no second dispatch test.
- Add a real secret-scan regression with a Windows-valid Unicode-and-space tracked filename. Exact
  order: safe write; add exact name; commit; write constructed `_GITHUB_TOKEN`; add exact name again;
  assert real `_narrow_secret_scan(str(repo))` raises `SystemExit(1)`. Do not mock scanning.
- Preserve all plus-line, diff-helper, NUL-safe, and return-chain regressions. Add no dependency and
  change no production listener/routing code.
- Create the v7 ImplementationReport with Python version, trusted `PYTHONUTF8`-absent proof, exact
  results, five changed paths, and risks. State that the trusted runner assigns the commit after the
  report and records its exact SHA in durable evidence/review payload. Review is pending at creation.

## Acceptance

- Fresh Windows Python 3.12 full suite has no deselection and only the quoted-filename skip.
- Former listener-return and dispatch-path failures pass.
- The secret-bearing Unicode-and-space exact path is staged after the safe commit.
- Ruff and resource validation pass: `6/6`, `4/4`, `3/3`.
- Exactly the five allowed paths differ from this frozen commit.

## Trusted Verification

Do not globally set or prefix `PYTHONUTF8`.

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
    "docs/tasks/windows-python312-utf8-closeout-v7-implementation-report.md"
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

## Forbidden and Closeout

No historical evidence action; no Agent Bus/server/listener/protocol/auth/service changes; no new
dependency, VPS, Agent Host, or UI work; no manual postflight/implementation commit/push/review/ACK.
After fresh acceptance, independent strong review, CI, and PR merge, v7 is the accepted closeout.
