# TaskCard: Executor process boundary and fail-closed handoff

## Objective

Close the four proven P0 gaps in the trusted role runner: keep Agent Bus credentials out of
model subprocesses, give non-interactive subprocesses a closed stdin, require an
ImplementationReport before commit/push/review, and fail the coder handler when the reviewer
event cannot be sent so Agent Bus does not ACK the current implementation event.

## Working Context

- Repository: the runner-provided `agent-workflow` checkout.
- Base branch: `main`.
- Task branch: `codex/executor-process-boundary`.
- The runner synchronizes the exact event commit before OpenCode starts. Do not reset, clean,
  stash, delete branches, or process any queued event yourself.
- `scripts/awf_role.py` is a trusted runner. Model tools are untrusted child processes. Git,
  push, Agent Bus send, and real credentials stay owned by the runner.
- Handler exit status is the ACK boundary: exit 0 lets the listener ACK the current event;
  non-zero leaves it unacknowledged.

## Baseline Findings

1. `child_env()` copies the complete parent environment and every model adapter uses it, so
   `AGENT_BUS_TOKEN`, `AGENT_BUS_AGENT_TOKENS`, and `AWF_*_TOKEN` reach model processes.
2. `spawn()` passes `input=None` for OpenCode, which inherits the listener/handler stdin. That
   handle is not reliably readable on Windows.
3. `role_coder()` stages, commits, pushes, and announces review without proving the requested
   ImplementationReport exists. `role_reviewer()` also starts review without that report.
4. `role_coder()` ignores a false result from `send_event()` and returns 0, allowing the
   implementation event to be ACKed even though the reviewer handoff was lost.
5. The current focused suite has five checkout-sync tests and passes before this change.

## Allowed Changes

Modify only:

1. `scripts/awf_role.py`
2. `tests/test_awf_role.py`
3. `docs/tasks/executor-process-boundary-implementation-report.md` (create as the required
   ImplementationReport after implementation and verification)

The TaskCard itself is already present on the dispatched branch and must not be rewritten.

## Required Implementation

### 1. Model-process credential boundary

- Add a small, explicit environment builder for model subprocesses.
- Start from the existing inherited child environment so PATH, platform variables, ordinary
  `AWF_*` configuration, and UTF-8 settings keep working.
- Remove `AGENT_BUS_TOKEN`, `AGENT_BUS_AGENT_TOKENS`, and every environment key matching
  `AWF_*_TOKEN` before invoking OpenCode or Codex.
- Use that filtered environment for all three model adapters: OpenCode executor, Codex reviewer,
  and OpenCode reviewer.
- Do not remove credentials from the trusted Agent Bus send path or change listener/bootstrap
  configuration.

### 2. Closed stdin for non-interactive subprocesses

- Any subprocess launched by `awf_role.py` that receives no explicit text input must use
  `stdin=subprocess.DEVNULL` instead of inheriting the handler's stdin.
- Preserve the Codex reviewer path that intentionally receives prompt text through `input=`.
- Keep argv execution shell-free except for the existing Windows `.cmd`/`.bat` wrapper.

### 3. ImplementationReport gate

- Add one reusable existence gate for the report path carried by `--report`.
- An empty report argument or a path that is not a regular file is a handler failure.
- In `role_coder()`, run the gate after the model returns success but before `git add`, commit,
  push, or the reviewer event.
- In `role_reviewer()`, run the same gate after checkout but before invoking any review tool or
  announcing readiness.
- This card requires existence only. Do not add content/schema validation, diff/path postflight,
  done-marker semantics, or review verdict routing.

### 4. Fail-closed reviewer handoff

- `role_coder()` must check the boolean result of the existing `send_event()` call for
  `task:awf-review`.
- If sending fails because configuration is missing or the Agent Bus CLI returns non-zero, the
  coder handler must return non-zero (or raise the existing non-zero `SystemExit`). It must not
  reach its success return, so the current implementation event remains unacknowledged.
- Keep the existing order: report gate, commit/push, then reviewer event. Do not introduce a new
  protocol, retry loop, idempotency mechanism, or Agent Bus change.

## Focused Regression Tests

Add focused tests that prove:

1. Model subprocess environments omit `AGENT_BUS_TOKEN`, `AGENT_BUS_AGENT_TOKENS`, and multiple
   `AWF_*_TOKEN` keys while preserving PATH, ordinary AWF configuration, and UTF-8 settings.
   Exercise the adapter boundary so both executor and reviewer model paths are protected.
2. A subprocess with no explicit input receives `subprocess.DEVNULL`; the Codex reviewer with
   explicit prompt text receives that text and does not also set `stdin=DEVNULL`.
3. A successful coder tool run with an empty or missing report fails before add/commit/push and
   before `send_event()`.
4. A missing report prevents both Codex and OpenCode reviewer execution.
5. `send_event() == False` makes the coder handler fail rather than return 0; a successful send
   still returns 0.
6. The existing five checkout-sync regression tests continue to pass.

Use pytest monkeypatching/fakes for process and network boundaries. Tests must not contact a real
Agent Bus, remote Git service, OpenCode, or Codex.

## Acceptance Criteria

- No Agent Bus or role token listed above is visible in any model subprocess environment.
- OpenCode/non-input subprocesses receive `DEVNULL`; Codex prompt input remains intact.
- Missing ImplementationReport makes coder and reviewer handlers fail closed at the specified
  gates.
- Reviewer-event send failure produces a non-zero coder handler result, preventing ACK of the
  current event.
- Only the three allowed implementation/report files differ from the dispatched TaskCard commit.
- Focused pytest and Ruff checks pass.

## Verification Commands

```bash
.venv/bin/python -m pytest -q tests/test_awf_role.py
.venv/bin/ruff check scripts/awf_role.py tests/test_awf_role.py
.venv/bin/ruff format --check scripts/awf_role.py tests/test_awf_role.py
git diff --check
git status --short
git diff --name-only HEAD
```

If the Windows checkout uses a different project virtual environment path, use that checkout's
installed Python/Ruff executables for the same focused files; record the exact commands.

## ImplementationReport

Create `docs/tasks/executor-process-boundary-implementation-report.md` containing:

- summary of the implementation;
- files changed;
- exact verification commands and results;
- any deviations or unresolved failures;
- starting event commit and final local commit if available.

The trusted runner will verify this file exists before staging any output.

## Stop Conditions

- Stop and report if preflight detects a dirty tree, unpushed local commits, missing task branch,
  or event/remote commit drift.
- Stop and report if satisfying an acceptance criterion requires any file outside Allowed Changes.
- Do not repair infrastructure, rotate credentials, modify Agent Bus, or touch old queued events.
- Do not auto-reset or clean model output after a missing-report failure.
- Do not try to solve the known post-push event-retry/commit-drift recovery problem in this card.

## Explicitly Out of Scope

- Agent Host or any new host/runtime abstraction.
- Agent Bus source, protocol, deployment, retries, idempotency, claims, ACK implementation, or
  queue cleanup.
- Full postflight validation, allowed-path enforcement in the runner, secret scanning, or
  acceptance-command execution by the runner.
- Structured review verdicts or changes to `decision:awf-ready` routing.
- Service management, UI, dashboards, plugins, dependencies, refactors, or additional security
  mechanisms.
