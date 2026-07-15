# ImplementationReport: Durable handler exit evidence

## Changed files

- `scripts/awf_listen.py`
- `scripts/awf_role.py`
- `tests/test_awf_role.py`
- `docs/tasks/durable-handler-exit-evidence-implementation-report.md`

The branch also contains the separately committed TaskCard
`docs/tasks/durable-handler-exit-evidence.md`. No event 50 or historical Windows checkout was
read, modified, copied, committed, reset, cleaned, or deleted.

## Durable evidence contract

- `build_handler()` passes the Agent Bus `{id}` placeholder as the required positive
  `--event-id` argument.
- The handler creates `handler.log` and atomically replaces `result.json` below:
  - Windows: `%LOCALAPPDATA%\\agent-workflow\\runs\\event-<id>\\`
  - POSIX: `$XDG_STATE_HOME/agent-workflow/runs/event-<id>/`
  - POSIX fallback: `~/.local/state/agent-workflow/runs/event-<id>/`
- Every log entry contains only UTC time, event ID, role, phase, and phase-specific non-secret
  evidence. The aggregate result contains no token, environment dump, command payload, or
  private-key path.
- The tracked OpenCode boundary uses a real `Popen` so `opencode_start` is flushed with PID and
  cwd before waiting. `opencode_exit` is flushed with the real return code and monotonic duration
  immediately after return, before postflight starts.
- If `communicate()` is interrupted, the handler kills and waits for the child before recording
  `opencode_exit`; it does not leave a running child while claiming exit.
- Coder evidence records postflight start/pass/fail, commit attempt/completion, push start, exact
  remote SHA verification, reviewer-event success, and final handler exit. Success and failure
  both retain `last_phase_before_exit` plus `handler_rc`.

## Minimal listener -> handler -> OpenCode-return proof

`test_minimal_listener_handler_opencode_return_chain` renders the command produced by
`awf_listen.build_handler()` with controlled event fields and executes that command as a real
child handler process. The real reviewer handler checks out a temporary local Git remote, invokes
a controlled fake OpenCode executable that returns zero without changing code, sends through a
controlled fake Agent Bus executable, and exits.

The test then reads the OS-state directory outside the temporary checkout and proves:

- `handler_exit=0`
- `last_phase_before_exit=opencode_exit`
- a child PID different from the test process
- `opencode_rc=0`
- `postflight_started=false`

Separate controlled subprocess cases prove both `rc=0` and `rc=7`, duration persistence, and
kill+wait+actual-rc evidence when communication is interrupted.

## Live Windows listener return probe

The remaining real-machine gate was completed on 2026-07-15 without changing product code or
redispatching the UTF-8 task:

- A fresh isolated Windows clone was pinned to merged
  `main@df6f4947f28596176f107b5a615424bf1db925b2`.
- A controlled `fake-opencode.cmd` outside the checkout performed only `exit /b 0`.
- A reviewer listener subscribed to the unique event type
  `probe:awf-handler-return-20260715-2300`; fresh event `51` was delivered to its real handler.
- The durable run directory was `%LOCALAPPDATA%\\agent-workflow\\runs\\event-51\\`.
- `handler.log` contained, in order: `handler_start`, `opencode_start`, `opencode_exit`,
  `handler_exit`.
- Atomic `result.json` recorded `handler_pid=30768`, `opencode_pid=32512`, `opencode_rc=0`,
  `opencode_duration_seconds=0.047`, `postflight_started=false`,
  `postflight_status=not_started`, `last_phase_before_exit=opencode_exit`, and `handler_rc=0`.
- The listener reported handler exit zero before ACK. A separate read-only query against the
  Agent Bus database confirmed event `51` was `acked`, with delivery at `2026-07-15 14:55:20`
  UTC, ACK at `2026-07-15 14:55:24` UTC, `retry_count=0`, and no `last_error`.
- The listener then exited normally after its bounded idle window. A new SSH process, independent
  of the listener stdout stream, re-read both durable files and all final fields. The isolated
  checkout remained clean at the exact merged SHA.

The reviewer role's current behavior also emitted pending architect event `52`
(`decision:awf-ready`) with `verdict=tool-review-complete`. In this probe that value means only
that the controlled fake process returned zero; it is not a semantic review, approval, or valid
workflow verdict. Event `52` must remain pending and must not be consumed or used to advance a
task. This is existing behavior, not a verdict-routing implementation or a claim that automatic
review routing is safe. Reviewer verdict routing remains the next Agent Workflow P0.

## Verification

The checkout has no local virtual environment, so verification used an existing project virtual
environment outside this worktree without installing dependencies.

```text
python -m pytest tests/test_awf_role.py -q
92 passed in 3.93s

python -m pytest -q
126 passed in 4.77s

python -m ruff check .
All checks passed!

python -m ruff format --check .
14 files already formatted

python -m compileall -q scripts src tests
exit 0

awf validate roles
6/6 passed

awf validate workflows
4/4 passed

awf validate examples
3/3 passed
```

No project type checker is configured. Ruff and `compileall` provide the configured static and
syntax checks.

## Strong review

The first independent review requested changes:

- HIGH: interrupted `communicate()` could orphan OpenCode while recording a false exit.
- MEDIUM: the first proof called `main()` in-process instead of executing the listener-built
  command.
- LOW: CLI examples omitted required `--event-id`.

All three findings were fixed. Final re-review result: **APPROVE**, with no remaining
CRITICAL/HIGH/MEDIUM/LOW findings. The reviewer reran the 92 focused tests, the interruption and
real-chain cases, and Ruff check/format.

## Deviations and known gaps

- The frozen TaskCard listed `python -m awf validate`, but `awf` is a console script rather
  than an importable module and `validate` requires a target. The failed command produced
  `No module named awf`; validation used the repository/CI commands `awf validate roles`,
  `workflows`, and `examples` instead. The original implementation contract, acceptance criteria,
  and postflight block were not rewritten after implementation began; this closeout adds only the
  later live-Windows evidence section to the already-merged TaskCard.
- The original controlled subprocess and POSIX state-path proof ran on macOS. The later live
  Windows event `51` now proves `LOCALAPPDATA`, `.cmd` wrapping, listener delivery, handler return,
  durable evidence, and success-gated ACK on the real executor.
- This proof closes only the no-code handler-return gate. It does not adopt event 50's uncommitted
  implementation, mark UTF-8 complete, or make the workflow a safe automatic loop.
