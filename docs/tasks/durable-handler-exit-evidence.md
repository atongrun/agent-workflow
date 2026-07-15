# TaskCard: Persist trusted handler exit evidence

## Goal

Make the trusted Agent Workflow runner leave enough local evidence to distinguish model completion
from handler completion even when the listener's SSH stream disappears. Prove the smallest
listener -> handler -> OpenCode-return boundary with a controlled subprocess before any UTF-8 task
is dispatched again.

This is a narrow observability repair. It does not resume event 50, reuse its Windows checkout,
change Agent Bus, or add a host, service, UI, log platform, or verdict-routing feature.

## Baseline and task branch

- Base: `origin/main` at `5194ac98d0a4cb480c45cfcd2004aa5409a459e9`.
- Task branch: `codex/p0-durable-handler-exit-evidence`.
- Event 50 and every historical Windows proof checkout remain untouched.

## Allowed implementation paths

1. `scripts/awf_listen.py`
2. `scripts/awf_role.py`
3. `tests/test_awf_role.py`
4. `docs/tasks/durable-handler-exit-evidence-implementation-report.md`

Do not add dependencies. Do not record tokens, complete environments, command lines containing
payloads, or private-key paths.

## Required behavior

- `build_handler()` passes the Agent Bus event ID to `awf_role.py`.
- Every CLI-invoked role handler writes under an OS state directory outside the Git checkout:
  - Windows: `%LOCALAPPDATA%\\agent-workflow\\runs\\event-<id>\\`
  - POSIX: `$XDG_STATE_HOME/agent-workflow/runs/event-<id>/`, falling back to
    `~/.local/state/agent-workflow/runs/event-<id>/`.
- The run directory contains append-only `handler.log` records and an atomically replaced
  `result.json`.
- Evidence covers `handler_start`, `opencode_start` (PID, cwd, time), `opencode_exit`
  (return code and duration), `postflight_start/pass/fail`, `commit`, `push`,
  `remote_sha_verified`, `review_event_sent`, and `handler_exit` when those phases occur.
- After an interrupted SSH connection, `result.json` still identifies the event, role, handler
  PID, latest phase, OpenCode PID/return code, and whether postflight started.
- A controlled fake OpenCode subprocess proves that a real child PID and return code cross the
  model-process boundary into durable evidence. No UTF-8 implementation is redispatched.

## Acceptance criteria

1. Listener handler construction contains exactly one `--event-id {id}` pair.
2. State-path tests cover Windows, POSIX XDG, and POSIX fallback selection without writing into a
   repository.
3. Durable writes produce parseable JSON after every phase and preserve an append-only phase log.
4. A real controlled subprocess proves both zero and non-zero OpenCode return codes, child PID,
   cwd, duration, and `postflight_started=false` before trusted postflight begins.
5. Handler success and failure both produce `handler_exit` evidence with an exit code.
6. Existing process-boundary, postflight, push/remote-SHA, and reviewer tests remain green.

## Live Windows return gate

Completed on 2026-07-15 with a fresh, isolated Windows checkout at merged
`main@df6f4947f28596176f107b5a615424bf1db925b2` and a controlled `.cmd` fake OpenCode
subprocess that returned zero without modifying the checkout.

- A reviewer listener subscribed to the unique probe event type
  `probe:awf-handler-return-20260715-2300` and received fresh event `51`.
- The listener launched the trusted handler, which launched the fake OpenCode child and wrote
  `%LOCALAPPDATA%\\agent-workflow\\runs\\event-51\\handler.log` plus atomic `result.json`.
- Durable evidence recorded a real child PID and cwd, `opencode_rc=0`, a non-negative duration,
  `postflight_started=false`, `last_phase_before_exit=opencode_exit`, and `handler_rc=0`.
- The Agent Bus server recorded event `51` as `acked` only after handler success, with
  `retry_count=0` and no `last_error`.
- After the listener and its SSH session exited, a separate Windows SSH process read the same
  durable files successfully. The isolated checkout remained clean at the exact merged SHA.
- No UTF-8 task was redispatched, and no event 49/50 or historical/proof checkout was modified,
  reset, cleaned, copied, committed, pushed, or deleted.

## Verification commands

```text
python -m pytest tests/test_awf_role.py -q
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m awf validate
```

## Out of scope

- Redispatching the UTF-8 implementation or changing its five preserved files.
- Commit, push, copy, cherry-pick, reset, clean, or deletion in event 50's Windows checkout.
- Agent Bus protocol or server changes.
- Agent Host, service/UI work, centralized logging, review verdict routing, or new dependencies.

## ImplementationReport

Create `docs/tasks/durable-handler-exit-evidence-implementation-report.md` with the final changed
files, evidence schema and privacy boundary, exact verification results, review result, deviations,
and known gaps.

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf_listen.py",
    "scripts/awf_role.py",
    "tests/test_awf_role.py",
    "docs/tasks/durable-handler-exit-evidence-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "tests/test_awf_role.py", "-q"],
    ["{python}", "-m", "ruff", "check", "scripts/awf_listen.py", "scripts/awf_role.py", "tests/test_awf_role.py"],
    ["{python}", "-m", "ruff", "format", "--check", "scripts/awf_listen.py", "scripts/awf_role.py", "tests/test_awf_role.py"]
  ]
}
-->
