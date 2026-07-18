# TaskCard: Fail-closed reviewer verdict routing

## Goal

Replace the current reviewer placeholder (`tool-review-complete` / process return code) with one
structured, fail-closed ReviewReport contract and route its semantic verdict safely. This task closes
the next P0 in the existing dogfood operations runner; it does not change Agent Workflow core
architecture or Agent Bus protocol.

## Fixed baseline

- Repository: `atongrun/agent-workflow`.
- Base: `origin/main` at `f759e34fa89aed5ded0ea870e261f3db30ac51c6`.
- Task branch: `codex/reviewer-verdict-routing`.
- PR #1 through PR #11 are merged. PR #11 merged the product-positioning and capacity-isolation
  contract, including the refreshed ReviewReport vocabulary and this task's dispatch gate. The
  baseline already includes exact checkout synchronization, model process boundaries,
  ImplementationReport and postflight gates, OpenCode argv termination, the Ruff baseline,
  mandatory push plus refreshed remote-SHA proof, durable handler evidence, and the Windows no-code
  handler-return gate.
- Current unsafe behavior: `role_reviewer()` maps model process `rc == 0` to
  `tool-review-complete`, sends `decision:awf-ready` unconditionally, ignores send failure, and
  returns zero even though no semantic ReviewReport has been validated.
- Historical Agent Bus events `49`, `50`, `51`, and `52` are evidence only. Do not read their
  payloads, consume them, ACK them, requeue them, or use them for this task.

The Allowed paths and `awf-postflight` contract below were revalidated against this merged baseline
before the task branch was created. Product-positioning documentation changes are already in the
baseline and are not part of the Executor's allowed paths.

## Allowed paths

Only these files may change after this TaskCard commit:

1. `scripts/awf-dispatch.sh`
2. `scripts/awf_listen.py`
3. `scripts/awf_role.py`
4. `scripts/reviewer-prompt.md`
5. `templates/artifacts/review-report.md`
6. `tests/test_awf_role.py`
7. `docs/tasks/reviewer-verdict-routing-implementation-report.md` (create)

After the baseline is refreshed and the TaskCard is committed on its task branch, the Executor must
not edit it.

## Required contract

### 1. Explicit ReviewReport path and production

- Extend the existing workflow pointer payload/handler argv narrowly so the reviewer receives an
  explicit repository-relative ReviewReport path distinct from the existing ImplementationReport
  path. A conventional default such as `.awf/artifacts/review-report-<task-id>.md` is acceptable.
- This is an Agent Workflow payload field only. Do not change Agent Bus endpoints, persistence,
  delivery, ACK, failure, or authentication semantics.
- Both Codex and OpenCode reviewer adapters must produce the ReviewReport at that exact path. Tool
  stdout or return code alone is not a report and cannot authorize routing.
- The trusted reviewer runner must read and validate the final report after the tool returns and
  before it emits any downstream event.
- A path is not a cross-machine handoff. Every verdict-dependent event must carry the complete,
  validated, normalized ReviewReport object in its payload so the recipient can inspect the
  verdict and evidence without access to the reviewer's checkout. Keep the serialized report at or
  below 16 KiB, exclude full diffs/patch bodies and secrets, and fail closed before send if it
  cannot be represented safely within that bound. The path remains local artifact provenance, not
  the only copy of the report available to downstream roles.

### 2. Structured, closed verdict set

The ReviewReport must have exactly one machine-readable verdict from this closed set:

- `PASS`
- `REQUEST_CHANGES`
- `BLOCKED`

Keep the representation small and explicit. The existing Markdown report may contain human-readable
findings and acceptance evidence, but parsing must not infer a verdict from prose, tool output, exit
status, filename, or absence of findings.

Missing reports, empty reports, malformed reports, duplicate verdict fields, and any unknown or
case-mismatched verdict fail closed. `tool-review-complete`, `approve`, process `rc == 0`, and a
successful model session are not aliases for `PASS`.

### 3. Routing rules

- `PASS`: only this verdict may send `decision:awf-ready` to `architect`. Include the validated
  ReviewReport object, branch, reviewed commit, ImplementationReport path, and local ReviewReport
  path.
- `REQUEST_CHANGES`: send a bounded rework event to `coder`; do not send
  `decision:awf-ready`. The ReviewReport must contain at least one deterministic failure with exact
  evidence (failed acceptance criterion, command/result, or precise file/line). Advisory style or
  architecture preferences cannot satisfy this gate. The coder event must carry the complete
  normalized ReviewReport object; do not rely on a checkout-local path and do not automatically
  start a new implementation handler in this task.
- `BLOCKED`: send a blocked/escalation event with the complete normalized ReviewReport object to
  `architect` for architect/user handling. Do not send ready and do not automatically rerun coder
  or reviewer.
- Keep event naming local to the existing Agent Workflow operations vocabulary and cover it in
  tests. Do not add a generic transition engine or new transport concept.

### 4. Downstream send and ACK boundary

- Check the boolean result of every verdict-dependent `send_event()` call.
- If downstream event sending fails or configuration is absent, the reviewer handler must return
  non-zero. It must not reach handler success, so the current `task:awf-review` event remains
  unacknowledged.
- Exactly one permitted downstream route may succeed per valid report. A failed send must not fall
  through to a different verdict or route.

## Focused regression tests

Use fakes/monkeypatching and temporary repositories. Tests must not contact Agent Bus, GitHub,
Codex, OpenCode, Windows, or a VPS. Prove all of the following:

1. A valid `PASS` report sends exactly one ready event to architect and returns zero only after the
   send succeeds.
2. A valid `REQUEST_CHANGES` report with deterministic, precise evidence sends exactly one rework
   event to coder, sends no ready event, and returns zero only after the send succeeds.
3. A valid `BLOCKED` report sends exactly one architect/user escalation event, sends no ready or
   coder-rework event, and does not invoke an automatic rerun.
4. Unknown, lowercase, duplicate, missing, malformed, and empty verdict/report cases fail before
   every downstream event.
5. `tool-review-complete` and reviewer process `rc == 0` cannot produce PASS without a valid report.
6. `REQUEST_CHANGES` without deterministic failure evidence fails closed rather than routing.
7. Downstream send failure for each of the three verdict routes produces non-zero handler exit and
   preserves the current review event's no-ACK boundary.
8. The explicit ReviewReport path survives dispatch -> listener handler argv -> coder review event
   -> reviewer validation without being confused with the ImplementationReport path; every routed
   event also contains the complete validated report object.
9. An oversized report, a report containing a full patch/diff body, or a report that cannot be
   safely serialized for the event payload fails before send.
10. Existing checkout, credential/DEVNULL, ImplementationReport, postflight, push/remote-SHA,
   durable evidence, and Windows/POSIX argv tests continue to pass.

## Acceptance criteria

- The reviewer always produces and the trusted runner validates a structured ReviewReport.
- Every downstream route carries the complete normalized ReviewReport object within the bounded
  event payload; a checkout-local path is never the sole handoff.
- Only `PASS`, `REQUEST_CHANGES`, and `BLOCKED` are accepted.
- Only PASS sends ready; REQUEST_CHANGES returns deterministic evidence to coder; BLOCKED escalates
  without retry.
- Missing or invalid ReviewReport data fails closed.
- A downstream send failure makes the handler fail so the current review event is not ACKed.
- No Agent Bus protocol, claim/lease, idempotency key, Agent Host, UI, generic workflow engine, or
  dependency is added.
- Only the seven allowed paths differ from this TaskCard commit.

## Verification commands

```text
python -m pytest -q tests/test_awf_role.py
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
git diff --check
```

Expected resource totals remain `6/6 roles`, `4/4 workflows`, and `3/3 examples`.

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf-dispatch.sh",
    "scripts/awf_listen.py",
    "scripts/awf_role.py",
    "scripts/reviewer-prompt.md",
    "templates/artifacts/review-report.md",
    "tests/test_awf_role.py",
    "docs/tasks/reviewer-verdict-routing-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_awf_role.py"],
    ["{python}", "-m", "pytest", "-q"],
    ["{python}", "-m", "ruff", "check", "."],
    ["{python}", "-m", "ruff", "format", "--check", "."],
    ["{python}", "-m", "agent_workflow.cli", "validate", "roles"],
    ["{python}", "-m", "agent_workflow.cli", "validate", "workflows"],
    ["{python}", "-m", "agent_workflow.cli", "validate", "examples"]
  ]
}
-->

## ImplementationReport

Create `docs/tasks/reviewer-verdict-routing-implementation-report.md` with the final event names and
payload fields, report format, routing matrix, files changed, exact verification results, review
findings/rework, remaining risks, starting commit, and final commit if available.

## Stop conditions

- Stop if the exact baseline or task branch has drifted, the checkout is dirty before execution,
  or the TaskCard postflight contract is invalid.
- Stop if safe routing requires an Agent Bus change, new dependency, generic orchestration layer,
  or any file outside Allowed paths.
- Do not clean, reset, stash, delete, or repair preserved evidence checkouts.

## Explicitly out of scope

- Consuming or handling historical events `49`, `50`, `51`, or `52`.
- Connecting to or modifying Windows, the VPS, or any real listener/service.
- A real cross-machine acceptance run; that belongs to the next session after deterministic review
  and CI.
- Agent Bus protocol/API/storage/auth/ACK/failure changes; claim/lease, competing consumers,
  `idempotency_key`, exactly-once semantics, or queue cleanup.
- Agent Host, UI, dashboards, provider SDKs, generic plugins, or a general workflow/transition
  engine.
- Reopening the method/core architecture or deciding whether runner/listener scripts become core.
