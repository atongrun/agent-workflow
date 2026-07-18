# TaskCard: Close Windows Python 3.12 UTF-8 portability

## Goal

Make Agent Workflow resource validation and its regression suite pass on Windows Python 3.12
without an externally configured `PYTHONUTF8` variable. Preserve the postflight scanner's quoted
Git-path coverage on POSIX and prove that a Windows-valid difficult tracked path reaches the same
NUL-safe known-path secret scan.

## Fixed baseline and branch

- Repository: `atongrun/agent-workflow`.
- Base: `origin/main` at `7b1bb290140e4c0db4efe314eed469dde99510ca` (PR #12 merge).
- Task branch: `codex/windows-python312-utf8-closeout`.
- The exact dispatched TaskCard commit is authoritative. Before execution, refresh the remote task
  branch and prove its SHA equals the dispatched commit.
- Use a fresh isolated Windows checkout with Python 3.12. Do not reuse any implementation, checkout,
  commit, or event from the two failed historical attempts.

Historical branches `codex/windows-python312-utf8` and
`codex/windows-python312-utf8-rerun` preserve the frozen TaskCards associated with failed events 49
and 50. They are evidence, not implementation inputs. Do not read or process those events, and do
not reset, reuse, merge, or delete either branch during this task. The detached dirty postflight
self-test worktree is also out of scope.

## Current verified gap

The merged baseline still has all of these portability defects:

1. `src/agent_workflow/validation.py` opens JSON schemas and YAML/JSON resources without an
   explicit encoding.
2. `tests/test_examples.py` opens YAML without an explicit encoding.
3. `tests/test_cli.py::run_awf` uses text-mode subprocess capture without an explicit agreement
   between child output encoding and parent decoding.
4. `tests/test_awf_role.py::test_secret_scan_quoted_tracked_filename` attempts to create `a"b.py`
   on every platform even though Windows forbids that filename.
5. Existing Unicode-path coverage proves only NUL-safe path collection. It does not prove that a
   tracked Windows-valid Unicode/space path containing a constructed secret reaches the real
   per-known-path diff scan and fails closed.

The previous event-50 handler-lifecycle blocker is no longer the implementation blocker: durable
handler evidence, the isolated Windows no-code return gate, and fail-closed semantic reviewer
routing are now present on the baseline. This TaskCard closes the still-unimplemented portability
change; it does not reopen those infrastructure tasks.

## Allowed paths

Only these files may change after this TaskCard commit:

1. `src/agent_workflow/validation.py`
2. `tests/test_cli.py`
3. `tests/test_examples.py`
4. `tests/test_awf_role.py`
5. `docs/tasks/windows-python312-utf8-closeout-implementation-report.md` (create)

This TaskCard is frozen once committed and must not be edited by the Executor.

## Required implementation

### Explicit UTF-8 reads and CLI output

- Open production schema and YAML/JSON resources explicitly as UTF-8.
- Open the directly relevant example YAML test resources explicitly as UTF-8.
- Give the CLI subprocess test helper an explicit UTF-8 output and decoding contract that does not
  rely on inherited `PYTHONUTF8` state.
- Keep the changes literal and local. Do not add an encoding abstraction, locale framework, or
  dependency.

### Portable tracked-path regression

- Keep the quoted-filename regression active where the filesystem permits `"`. Skip it narrowly on
  Windows before attempting to create the illegal filename, with a filesystem-specific reason.
- Add one Windows-valid tracked path containing Unicode and/or spaces. Commit a safe version,
  modify or stage that exact path with the existing constructed GitHub-token fixture, and assert
  `_narrow_secret_scan()` fails.
- Exercise the real Git path collection and real per-known-path tracked diff scan. Do not mock the
  path list, parse human-readable patch headers, replace the scanner, or add Windows-only production
  logic.
- Preserve the existing plus-prefixed-line and diff-helper regressions.

## Acceptance criteria

- Production resource reads use UTF-8 regardless of Windows locale.
- CLI child output and parent decoding agree on UTF-8 without external `PYTHONUTF8`.
- POSIX retains the quoted-path security regression; Windows never creates the illegal filename.
- A Windows-valid difficult tracked path containing a constructed secret is rejected through the
  actual NUL-safe known-path scan.
- Windows Python 3.12 passes the full suite, Ruff checks, and all resource validation with
  `PYTHONUTF8` absent.
- Only the five allowed paths differ from the frozen TaskCard commit.
- The ImplementationReport records the exact Windows Python version, proof that `PYTHONUTF8` was
  absent, commands/results, changed files, final implementation SHA, and remaining risks.

## Required verification

Run through the trusted runner in the fresh Windows environment. `PYTHONUTF8` must be absent from
the verification process; do not set it globally or prefix commands with `PYTHONUTF8=1`.

```text
py -3.12 --version
python -m pytest -v
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
```

Expected resource totals remain `6/6 roles`, `4/4 workflows`, and `3/3 examples`.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/validation.py",
    "tests/test_cli.py",
    "tests/test_examples.py",
    "tests/test_awf_role.py",
    "docs/tasks/windows-python312-utf8-closeout-implementation-report.md"
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

## Forbidden work

- Reusing or copying prior failed implementations, commits, Windows checkouts, or event payloads.
- Reading, consuming, ACKing, requeueing, or otherwise modifying events 49, 50, 51, or 52.
- Resetting, cleaning, deleting, or repairing preserved evidence branches or worktrees.
- Agent Bus protocol/storage/auth changes, reviewer-routing changes, Agent Host, services, UI,
  generic workflow engines, plugins, or new dependencies.
- Dispatching another task or manually completing postflight, push, review, or ACK outside the
  trusted runner.

## Closeout consequence

After this task passes fresh Windows acceptance, independent review, CI, and PR merge, it becomes
the successful mainline replacement for both failed portability TaskCards. Only then may the two
historical UTF-8 branches be proposed for local/remote deletion under a separate explicit gate.
