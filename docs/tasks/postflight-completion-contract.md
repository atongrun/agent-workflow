# TaskCard: Postflight completion contract

## Objective

Add one fail-closed postflight gate to the trusted coder runner. The TaskCard must carry explicit
allowed-change paths and focused verification commands. The runner freezes that contract before
the model starts, then independently validates the resulting worktree after the model succeeds and
produces its ImplementationReport, before any `git add`, commit, push, or reviewer event.

## Working Context

- Repository: the runner-provided `agent-workflow` checkout.
- Base branch: `main` at `9724d6c04bbe5c4e6898e2ba7a54aacba5ef8ddf`.
- Task branch: `codex/postflight-completion-contract`.
- Dispatched task commit: the exact commit in the Agent Bus event; the trusted runner verifies it
  against `origin/codex/postflight-completion-contract` before OpenCode starts.
- Do not reset, clean, stash, delete branches, or process queued Agent Bus events yourself.
- `scripts/awf_role.py` is the trusted runner. OpenCode is an untrusted child process. Git writes,
  push, Agent Bus send, and credentials remain runner-owned.
- Handler exit status is the ACK boundary: a non-zero exit leaves the implementation event
  unacknowledged.
- Existing process-boundary, checkout-sync, ImplementationReport, and reviewer-event failure
  behavior is already covered by `tests/test_awf_role.py` and must not regress.

## Machine-Readable Postflight Contract

The runner implementation introduced by this task must read this exact JSON object from the
`awf-postflight` marker below. Keep the representation deliberately narrow: repository-relative
allowed paths and shell-free argv commands. `{python}` means the Python executable running
`awf_role.py`, so the same card works with `.venv/bin/python` on POSIX and
`.venv\Scripts\python.exe` on Windows.

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf_role.py",
    "templates/artifacts/task-card.md",
    "tests/test_awf_role.py",
    "docs/tasks/postflight-completion-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_awf_role.py"],
    ["{python}", "-m", "ruff", "check", "scripts/awf_role.py", "tests/test_awf_role.py"],
    ["{python}", "-m", "ruff", "format", "--check", "scripts/awf_role.py", "tests/test_awf_role.py"]
  ]
}
-->

## Allowed Changes

Modify only:

1. `scripts/awf_role.py`
2. `templates/artifacts/task-card.md`
3. `tests/test_awf_role.py`
4. `docs/tasks/postflight-completion-implementation-report.md` (create as the required report)

This TaskCard is already present on the dispatched branch and must not be rewritten. Do not modify
`scripts/awf-dispatch.sh` or `scripts/awf_listen.py`: the TaskCard remains the contract source and
the Agent Bus event remains a pointer to it.

## Required Implementation

### 1. TaskCard postflight fields

- Update `templates/artifacts/task-card.md` with a small machine-readable `awf-postflight` JSON
  block containing non-empty `allowed_paths` and `verification_commands` arrays.
- Use repository-relative forward-slash paths. Paths name exact files; do not add glob or general
  policy semantics.
- Each verification command is a non-empty argv string array, executed without a shell.
- Support `{python}` only as the whole first argv element, replacing it with `sys.executable`.
- Missing, malformed, empty, duplicate, absolute, drive-qualified, or parent-traversing paths;
  malformed commands; or extra contract keys are deterministic handler failures.
- Parse and freeze the contract before starting OpenCode. Do not reread it after model execution;
  the TaskCard is deliberately absent from `allowed_paths`, and model edits to it must fail the
  final changed-path gate rather than change the frozen contract.
- Keep parsing local to the trusted runner; do not add a schema, dependency, plugin, or general
  policy layer.

### 2. Focused-verification gate

- After the model succeeds and the ImplementationReport exists, execute every frozen TaskCard
  verification argv in order, from the repository root, without a shell.
- Use the credential-stripped model subprocess environment because the commands execute code and
  tests modified by the untrusted model. Keep closed stdin and existing UTF-8 behavior.
- Stop at the first failure and return non-zero. Successful commands must all run again even if
  OpenCode reports that it already ran them.
- Verification may itself create files, so run it before collecting the final Git delta and before
  path/artifact checks. Log argv safely without environment values or file content.

### 3. Changed-path and temporary-artifact gates

- After the model succeeds and the existing ImplementationReport gate passes, collect all actual
  tracked, deleted, renamed, and untracked worktree paths before staging.
- Fail if the set is empty or any changed path is not one of `allowed_paths`.
- Fail on obvious temporary configuration or execution artifacts even if accidentally listed as
  allowed. Keep the denylist short and explicit: secret-bearing `.env` variants (but not documented
  example templates), editor swap/backup files, OS metadata, Python/cache directories, coverage
  files, log/PID files, local virtual environments, and dependency/build output directories.
- Do not reset, clean, delete, quarantine, or otherwise mutate a failing worktree.

### 4. Narrow secret gate

- Inspect added content from tracked diffs and complete content of untracked regular files.
- Fail on high-confidence direct credential exposure: private-key headers, credential-bearing URLs,
  and established token/key prefixes or shapes suitable for a focused regression test.
- Report only the affected repository-relative path and detector label. Never print the matched
  credential value or matching source line.
- Do not inspect unchanged history, call a network service, add entropy analysis, or expand this
  into a supply-chain/security scanner. Placeholder words such as `token`, `secret`, and test
  fixture values must not fail by themselves.

### 5. Diff gate

- Run `git diff --check` through the existing shell-free subprocess boundary and fail on non-zero.
- Do not stage, commit, push, or send the reviewer event on failure.

### 5. Coder ordering and fail-closed behavior

The successful coder sequence must be:

1. exact checkout preflight;
2. parse and freeze the TaskCard postflight contract;
3. OpenCode execution;
4. ImplementationReport existence gate;
5. rerun every frozen focused verification command;
6. collect the final Git delta and enforce allowed paths, artifact denylist, narrow secret scan, and
   `git diff --check`;
7. `git add`, commit, optional push;
8. `task:awf-review` send;
9. return zero so the current event may be ACKed.

Any postflight failure must occur before step 7 and raise/return non-zero. Reviewer behavior and
verdict routing are unchanged.

## Focused Regression Tests

Add focused tests, using temporary repositories and monkeypatch/fakes where appropriate, that
prove:

1. A valid contract parses and freezes before the model starts, normalizes forward-slash
   repo-relative exact paths, replaces `{python}`, and runs verification commands in order without
   a shell on POSIX and Windows-style filesystem inputs; later TaskCard edits cannot change it.
2. Missing/malformed contract data and unsafe path/command forms fail closed.
3. Modified, deleted, renamed, and untracked paths are included; one out-of-scope path fails before
   `git add`, commit, push, or `send_event`.
4. Each explicit temporary/config/artifact category is rejected, with documented example templates
   allowed where intended.
5. High-confidence secret fixtures in tracked added lines and untracked files fail without leaking
   the matched value; benign placeholder/test text passes.
6. Verification commands are rerun by the runner before final delta inspection, stop on first
   failure, and a non-zero result prevents every downstream write/event; files created by
   verification remain subject to path/artifact checks; non-zero `git diff --check` also fails.
7. A fully valid postflight reaches the existing commit/push/event path.
8. Existing checkout-sync, subprocess credential/DEVNULL, report, and fail-closed event tests keep
   passing.

Tests must not contact a real Agent Bus, GitHub, OpenCode, Codex, or external secret scanner.

## Acceptance Criteria

- TaskCard format explicitly carries exact allowed paths and shell-free focused verification argv.
- The trusted coder runner independently enforces path scope, temporary-artifact, narrow direct
  secret, `git diff --check`, and focused command gates before its first `git add`.
- Any failure is non-zero and leaves the worktree untouched by cleanup; no commit, push, review
  event, or ACK-success return is reached.
- Focused tests cover success plus each failure class and preserve Windows/POSIX behavior.
- Only the four allowed output files differ from the dispatched TaskCard commit.
- Focused pytest and Ruff checks pass.

## Verification Commands

The executor runs these, and the trusted runner must independently rerun the same three commands
from the machine-readable contract before staging:

```text
{python} -m pytest -q tests/test_awf_role.py
{python} -m ruff check scripts/awf_role.py tests/test_awf_role.py
{python} -m ruff format --check scripts/awf_role.py tests/test_awf_role.py
```

The trusted runner also executes `git diff --check` as its own mandatory gate before those commands.

## ImplementationReport

Create `docs/tasks/postflight-completion-implementation-report.md` containing:

- summary of the implementation and exact gate ordering;
- files changed;
- exact verification commands and results;
- focused test count;
- any deviations or unresolved failures;
- starting event commit and final local commit if available.

The existing trusted runner verifies this file exists before starting postflight.

## Stop Conditions

- Stop and report if preflight finds a dirty historical checkout, unpushed local commits, missing
  task branch, or event/remote commit drift. Do not repair that checkout.
- Stop and report if satisfying an acceptance criterion requires a file outside Allowed Changes.
- Do not repair infrastructure, rotate credentials, modify Agent Bus, or touch old queued events.
- Do not auto-reset/clean model output after any failure.

## Explicitly Out of Scope

- Reviewer verdict routing or reviewer behavior changes.
- Agent Host or another runtime abstraction.
- Agent Bus source, protocol, event shape, deployment, retries, idempotency, claims, leases, ACK
  implementation, or queue cleanup.
- Service management, logs, status, UI, dashboards, plugins, dependencies, or a generic policy
  engine.
- Full secret/supply-chain scanning, dependency scanning, history scanning, SBOM, signing, or
  provenance.

## Deterministic Review Rework (single pass)

Strong review rejected the first implementation commit. Apply only the five deterministic fixes
below; do not redesign the postflight contract or expand the detector set.

1. **Cover the full HEAD delta.** Current `_narrow_secret_scan()` and `git diff --check` inspect
   only unstaged changes. A model can stage an allowed file containing a token-shaped value and
   trailing whitespace, after which both gates return success. Make secret scanning and whitespace
   checking cover staged plus unstaged changes relative to `HEAD`. Add regressions for staged
   tracked and staged new files.
2. **Use one NUL-safe path snapshot.** Current text porcelain + `shlex` parsing drops the
   destination of a quoted rename and leaves Unicode paths as Git escape sequences. The untracked
   secret scan separately reparses the raw quoted path and can skip a file with spaces. Replace
   those paths with one NUL-delimited Git snapshot that covers staged/unstaged tracked paths and
   untracked non-ignored files, returns both sides of a rename (using `--no-renames` is acceptable),
   and is reused by the allowed-path, artifact, and untracked-content gates. Add spaced rename,
   spaced untracked-secret, and Unicode path regressions.
3. **Match artifact categories at any depth.** Reject `.env` variants by basename and local
   environment/cache/dependency/build directories by path component, while preserving the three
   documented `.env.example` / `.env.template` / `.env.sample` exceptions. Add nested regressions
   such as `config/.env.production`, `web/node_modules/pkg/index.js`, and
   `pkg/build/output.o`.
4. **Fail closed on unreadable untracked regular files.** Do not silently catch and skip read
   errors. Report only the repository-relative path plus a safe `unreadable-file` label; never file
   content or exception text. Add a mocked read-error regression so it behaves consistently on
   Windows and POSIX.
5. **Reject an empty executable before OpenCode.** `verification_commands: [[""]]` is malformed
   and must fail during contract parsing. Do not broaden `{python}` semantics beyond the original
   card.

Also make the implementation self-hosting: token/key fixtures in `tests/test_awf_role.py` must be
constructed from fragments so the new postflight secret gate does not reject its own uncommitted
test diff. After fixing, update the existing ImplementationReport with the rework findings, exact
final commands/counts, and the new final local commit if available.

The rework is accepted only if the new runner itself parses the frozen contract, reruns the three
focused commands, scans the final uncommitted delta, passes `git diff HEAD --check` (or equivalent
complete-delta check), and only then reaches commit/review-event handling.
