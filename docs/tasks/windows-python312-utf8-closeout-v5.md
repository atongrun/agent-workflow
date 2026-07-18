# TaskCard: Complete Windows Python 3.12 UTF-8 closeout v5

## Goal

Complete the Windows Python 3.12 UTF-8 portability fix on a fresh checkout. Preserve the POSIX
quoted-filename regression, and prove that a staged, tracked, Windows-valid Unicode-and-space path
containing the constructed token fixture reaches the real secret scanner.

## Frozen Baseline

- Base: `origin/main` at `f5f6a37f13e118241755c428a3041ae8a2d56915` (PR #13 merge).
- Branch: `codex/windows-python312-utf8-closeout-v5`.
- The dispatched SHA must equal this TaskCard commit exactly.
- Use a new isolated Windows checkout and Python 3.12 environment. Do not reuse prior implementation
  commits, reports, events, or checkouts.

Preserve all earlier portability evidence. Do not read, consume, ACK, requeue, modify, reset, clean,
or delete events 49, 50, 51, 52, 73, or 74 or their evidence branches/checkouts. Event 75/76 and the
v4 branch are also preserved as failed-review evidence.

## Allowed Paths

Only these files may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-v5-implementation-report.md` (create)

This TaskCard is frozen after commit and must not be edited by the Executor.

## Required Implementation

- Add `encoding="utf-8"` directly to production schema/resource opens and directly relevant example
  YAML test opens. Add no abstraction or dependency.
- In `tests/test_cli.py::run_awf`, copy the environment, remove `PYTHONUTF8`, set
  `PYTHONIOENCODING=utf-8`, and decode captured output explicitly as UTF-8.
- Keep the quoted tracked-filename regression active on supporting filesystems. Skip only on Windows,
  before attempting to create `a"b.py`, with a filesystem-specific reason.
- Add a tracked Windows-valid path containing both Unicode and a space. Commit a safe version, write
  the existing constructed GitHub-token fixture into that exact path, then execute
  `run("git", "add", name, cwd=repo)` for that exact path before asserting the real
  `_narrow_secret_scan()` raises `SystemExit(1)`. The post-secret `git add` is mandatory: an
  unstaged-only regression does not satisfy this card. Do not mock path collection/scanning or parse
  patch headers.
- In `test_minimal_listener_handler_opencode_return_chain`, keep a controlled `.cmd` shim only for
  the OpenCode model-tool boundary. For Agent Bus, create a plain Python script named exactly `send`
  in the handler cwd, exclude it locally from Git status, and set `AWF_BUS_BIN` to `sys.executable`.
  Production must execute `python.exe send ...`; do not create a `.cmd`/`.bat` bus shim or change
  production routing.
- In the dispatch dry-run test, locate Git Bash explicitly and convert drive-qualified script and repo
  paths to exact MSYS form (`X:\rest` to `/x/rest`, lowercase drive and forward slashes). Decode
  captured stdout/stderr explicitly as UTF-8. Keep the real shell script under test.
- Preserve plus-prefixed-line, diff-helper, NUL-safe collection, and return-chain regressions.
- The ImplementationReport must contain the final implementation SHA (not `Pending`), Python version,
  trusted `PYTHONUTF8`-absent proof, exact command results, changed files, review status, and risks.

## Acceptance Criteria

- A fresh Windows Python 3.12 checkout runs the entire suite with no deselection and only the narrow
  Windows quoted-filename skip.
- The two former Windows full-suite failures pass without production listener/routing changes.
- The Unicode-and-space secret test stages the secret-bearing exact path after the safe commit.
- Ruff passes; resources remain `6/6 roles`, `4/4 workflows`, and `3/3 examples`.
- Exactly the five allowed paths differ from this frozen commit.

## Required Verification

Run all commands through the trusted runner. Do not globally set or prefix `PYTHONUTF8`.

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
    "docs/tasks/windows-python312-utf8-closeout-v5-implementation-report.md"
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

- Any prior implementation/evidence reuse or any state-changing action on preserved events.
- Repairing, cleaning, resetting, or deleting historical evidence branches/checkouts/worktrees.
- Production Agent Bus/listener/protocol/storage/auth/service/reviewer-routing changes, dependencies,
  Agent Host, UI, VPS, or real listener configuration changes.
- Manually completing postflight, implementation commit, push, review, or ACK outside the trusted
  runner.

## Closeout

After fresh Windows acceptance, independent strong review, CI, and PR merge, v5 is the accepted
closeout. Evidence deletion remains a separate retention decision.
