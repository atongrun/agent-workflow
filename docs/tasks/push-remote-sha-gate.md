# TaskCard: Verify the pushed remote SHA before reviewer handoff

## Goal

Close the trusted coder runner's remaining fail-closed gap. A coder event may reach the reviewer
only after the implementation commit has been pushed and a freshly read `origin/<branch>` resolves
to exactly the local `HEAD` commit.

This is a narrow runner-contract repair. It does not change Agent Bus, introduce a runtime/host,
route reviewer verdicts, or implement the pending Windows UTF-8 task.

## Baseline and task branch

- Base: `origin/main` at `ca98a63b93983b7c867e42a498eee8820ba70fbc`.
- Task branch: `codex/p0-push-remote-sha-gate`.
- The TaskCard is committed before implementation and must not be edited by the executor.

## Allowed implementation paths

Only these files may change after the TaskCard commit:

1. `scripts/awf_role.py`
2. `tests/test_awf_role.py`
3. `docs/tasks/push-remote-sha-gate-implementation-report.md`

Do not store, print, or document credential values. Do not change Windows credential configuration
in this repository.

## Required behavior

### Push and remote verification

- Keep the existing postflight, staging, and commit order.
- A non-zero `git push` must fail before any `task:awf-review` event.
- After a zero push result, refresh or directly read the exact remote task branch. Do not trust a
  stale remote-tracking ref left from checkout.
- Resolve both local `HEAD` and the freshly refreshed `origin/<branch>` as commits.
- A missing remote ref, an unreadable ref, a failed refresh/read, or a remote SHA different from
  local `HEAD` must fail before any review event.
- Only the exact equality `origin/<branch> == HEAD` permits the existing review event. The event's
  `commit` field must be that verified SHA.

### `AWF_NO_PUSH`

`AWF_NO_PUSH=1` must not announce a cross-machine review handoff or return successful handler
completion that could ACK the coder event. Make this path fail closed before `send_event`. Local
experimentation that intentionally skips a remote push is not remote completion and must use a
separate non-event workflow rather than this trusted coder handler.

### Implementation shape

- Prefer one small helper with explicit failure outcomes over adding a new abstraction.
- Reuse the existing `git` / `git_out` helpers and repository conventions.
- Do not add dependencies.
- Keep all credentials outside model subprocesses and logs exactly as today.

## Acceptance criteria

Regression tests must prove all of the following:

1. Push returns non-zero -> no review event.
2. Push returns zero but the refreshed remote ref is missing/unreadable -> no review event.
3. Push returns zero but refreshed `origin/<branch>` differs from `HEAD` -> no review event.
4. Push returns zero and refreshed `origin/<branch>` equals `HEAD` -> exactly one review event whose
   commit is the verified SHA.
5. `AWF_NO_PUSH=1` -> no review event and no successful cross-machine handler completion.
6. Existing postflight, report, process-boundary, and reviewer behavior remains green.

## Verification commands

Run from the repository root:

```text
python -m pytest tests/test_awf_role.py -q
python -m ruff check scripts/awf_role.py tests/test_awf_role.py
python -m ruff format --check scripts/awf_role.py tests/test_awf_role.py
```

## Out of scope

- Agent Bus server/client/schema/service changes.
- Agent Host, runtime, UI, new handoff abstractions, or new dependencies.
- Reviewer verdict routing or ACK redesign.
- Windows UTF-8 implementation or reuse of event 49 / commit `ca96f87`.
- Resetting, cleaning, deleting, or modifying any historical Windows checkout.
- Manual pushes or fabricated review events used as completion evidence.

## ImplementationReport

Create `docs/tasks/push-remote-sha-gate-implementation-report.md` with the final changed-file list,
contract behavior, exact commands/results, deviations, and known verification gaps.

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf_role.py",
    "tests/test_awf_role.py",
    "docs/tasks/push-remote-sha-gate-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "tests/test_awf_role.py", "-q"],
    ["{python}", "-m", "ruff", "check", "scripts/awf_role.py", "tests/test_awf_role.py"],
    ["{python}", "-m", "ruff", "format", "--check", "scripts/awf_role.py", "tests/test_awf_role.py"]
  ]
}
-->
