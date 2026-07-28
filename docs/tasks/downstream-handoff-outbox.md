# TaskCard: Durable downstream handoff outbox

## Objective

Make every Agent Workflow downstream handoff recoverable across handler retries without rerunning
an already-completed model stage. Preserve strict checkout drift checks and Agent Bus v0.3.0 as an
opaque at-least-once transport.

## Baseline

- Base: `main` at `5cf19d1bbe6eddb0904c5bb5f56242cb92219ff9`.
- Task branch: `codex/downstream-send-retry`.
- A coder currently commits and verifies `origin/<branch>` before sending `task:awf-review`.
- If that send fails, the source event remains unacknowledged. Its retry carries the original
  dispatched commit, so strict preflight rejects the intentionally advanced remote branch.
- The same transient-send pattern exists after reviewer verdict routing.
- Agent Bus delivery is at least once and payload-opaque. A failed CLI return after invocation is
  ambiguous: the server may already have persisted the event.

## Allowed Changes

1. `scripts/awf_role.py`
2. `scripts/awf_listen.py`
3. `scripts/awf-dispatch.sh`
4. `tests/test_awf_role.py`
5. `docs/tasks/downstream-handoff-outbox-implementation-report.md`

Do not change Agent Bus, dependencies, service configuration, historical events, or this TaskCard
after it is frozen.

## Required Behavior

### Stable delivery identity

- Initial architect dispatch includes an opaque, deterministic Workflow delivery ID bound to the
  event type, branch, and dispatched commit.
- Every downstream Workflow event includes a new deterministic delivery ID, a canonical payload
  hash, and the source event ID.
- Listener handlers pass the delivery ID and payload hash as explicit argv values.
- The trusted handler recomputes and verifies the payload hash from its bound inputs. The same
  delivery ID with different inputs fails closed.

### Durable outbox

- Store outbox records outside Git checkouts under the existing per-user Agent Workflow state
  root. Use atomic replace and do not store credentials, complete environments, or command lines.
- Prepare and fsync an outbox record before invoking `agent-bus send`.
- Record `prepared`, `attempting`, `ambiguous`, and `sent` states. Any non-zero/exception after the
  CLI is invoked is ambiguous.
- The outbox binds source role/event/delivery, branch, source commit, verified evidence commit,
  destination, event type, exact payload, and canonical payload hash.
- Coder writes the outbox only after trusted commit, push, and remote-SHA equality. Reviewer writes
  it only after parsing a valid verdict and choosing exactly one route.

### Replay before strict checkout

- At the start of coder and reviewer roles, inspect the exact input's durable outbox before normal
  checkout/model work.
- `sent` returns success without another send so a lost source ACK can converge.
- `prepared` or `ambiguous` replays the exact persisted payload. Success marks `sent`; failure stays
  non-zero and ambiguous.
- Coder replay refreshes and requires `origin/<branch>` to equal the outbox evidence commit. It
  must not compare the advanced branch to the old dispatched commit and must not rerun OpenCode.
- Outbox identity/input/hash/remote mismatches fail closed before sending.
- Normal first execution still uses the existing strict `fetch_and_checkout()` gate unchanged.

### Receiver deduplication

- Use a durable inbox keyed by the incoming Workflow delivery ID outside the checkout.
- A completed inbox record with the same canonical input hash returns success without rerunning the
  model or emitting another downstream handoff.
- Reuse of a delivery ID with different bound inputs fails closed.
- Mark inbox completion only after the stage's downstream outbox is durably `sent`.
- Apply the same behavior to initial implementation, deterministic rework, review, and all three
  reviewer verdict routes.

## Focused Tests

1. State paths are outside the checkout on Windows and POSIX.
2. Outbox writes are atomic, contain no credentials, and preserve an exact canonical payload hash.
3. Failed coder send leaves an ambiguous outbox and a non-zero handler result.
4. Retry with the remote branch at the recorded evidence commit replays before checkout/model and
   converges to sent.
5. Retry with any remote, input, delivery, or payload-hash mismatch fails before send.
6. Sent coder outbox returns success without another send or model call.
7. Duplicate reviewer delivery with the same hash returns success without Codex/OpenCode or
   another verdict event; a hash mismatch fails closed.
8. Reviewer PASS, REQUEST_CHANGES, and BLOCKED routes all use durable outbox replay.
9. Dispatch and listener templates carry the stable delivery fields on implementation, review,
   and rework routes.
10. Existing checkout, postflight, Git-boundary, remote-SHA, durable evidence, and routing tests
    remain green on Mac and Windows.

## Verification

```bash
python -m pytest -q tests/test_awf_role.py
python -m pytest -q
ruff check .
ruff format --check .
bash -n scripts/awf-dispatch.sh
awf validate roles
awf validate workflows
awf validate examples
git diff --check
```

Run the focused role suite on a fresh Windows checkout at the exact final head. Agent Workflow code
must receive a fresh independent Codex native review and successful GitHub CI before merge.

## Stop Conditions

- Stop if recovery requires weakening first-run branch/commit equality, force-pushing, resetting a
  task branch, reading historical payloads, ACK/requeue, or changing Agent Bus.
- Stop if exact receiver deduplication cannot be proven without a transport protocol change.
- Preserve every historical event and old checkout unchanged.

## Explicitly Out Of Scope

- Agent Bus protocol, storage, API, release, idempotency keys, ACK, fail, or requeue behavior.
- Multi-host shared state for two simultaneous listeners with the same role. Dogfood continues to
  require one active listener per identity.
- Hostile same-user arbitrary-code isolation, Agent Host, service manager work, UI, dashboards, or
  new dependencies.

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf_role.py",
    "scripts/awf_listen.py",
    "scripts/awf-dispatch.sh",
    "tests/test_awf_role.py",
    "docs/tasks/downstream-handoff-outbox-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_awf_role.py"],
    ["{python}", "-m", "ruff", "check", "scripts/awf_role.py", "scripts/awf_listen.py", "tests/test_awf_role.py"],
    ["{python}", "-m", "ruff", "format", "--check", "scripts/awf_role.py", "scripts/awf_listen.py", "tests/test_awf_role.py"]
  ]
}
-->
