# Durable Downstream Handoff Outbox Implementation Report

## Summary

Agent Workflow now persists every coder and reviewer downstream handoff before invoking Agent Bus.
If a send fails after a trusted push or review, a later delivery of the same Workflow input replays
the exact outbox payload before strict checkout or model execution. A sent outbox and completed
inbox let a lost source ACK converge without another send.

Agent Bus remains unchanged at v0.3.0. The implementation treats its send result as ambiguous after
the CLI is invoked and handles possible duplicate Bus events with Workflow-owned delivery IDs and
receiver-side inbox deduplication.

## Changes

- `scripts/awf-dispatch.sh`
  - Defaults new implementation traffic to `task:awf-impl-v2`, isolating the delivery-metadata
    contract from preserved legacy events.
  - Builds JSON through Python rather than string interpolation.
  - Adds a deterministic delivery ID, canonical SHA-256 payload hash, and source-event marker.
  - Resolves `AWF_PYTHON_BIN`, then `python3`, then `python` for Mac/Windows portability.
- `scripts/awf_listen.py`
  - Defaults coder/reviewer listeners to versioned implementation/review event types.
  - Passes event type, delivery ID, payload hash, and source event ID as explicit handler argv.
  - Preserves the distinct structured rework argument mapping for v1 and v2 routes.
- `scripts/awf_role.py`
  - Adds a per-user Workflow state root while preserving existing event run evidence paths.
  - Reconstructs and hashes the exact metadata-free input payload for implementation, review, and
    rework handlers.
  - Persists atomic outbox and inbox records outside Git checkouts. Records contain no credentials,
    environment snapshots, or command lines.
  - Validates action/recipient/type routes, canonical payload hash, envelope hash, delivery ID,
    branch, source commit, and input identity before every replay.
  - Replays prepared/attempting/ambiguous outboxes before strict checkout. A coder replay refreshes
    the remote branch, requires the recorded evidence commit, and requires the ImplementationReport
    to be tracked at that commit.
  - Marks a send ambiguous on false return or exception. Success is recorded durably before the
    source handler can return zero.
  - Applies the same recovery behavior to coder review handoff and reviewer PASS,
    REQUEST_CHANGES, and BLOCKED routing.
  - Suppresses duplicate downstream model execution when the same Workflow delivery arrives under
    a different Agent Bus event ID.
- `tests/test_awf_role.py`
  - Covers delivery state locations, handler metadata, dispatch canonicalization, ambiguous coder
    replay, sent replay convergence, remote drift, delivery/hash mismatch, reviewer deduplication,
    and all three versioned verdict routes.

## State And Recovery Boundary

Production state remains outside repositories:

```text
<platform state root>/agent-workflow/runs/event-<bus-event-id>/
<platform state root>/agent-workflow/outbox/<role>/<delivery-hash>.json
<platform state root>/agent-workflow/inbox/<role>/<delivery-hash>.json
```

The role listener contract still requires one active listener per identity. State is local to that
role machine and user. Moving the same logical role to another host while an ambiguous outbox is
pending is not supported by this bounded change.

The normal first-run `fetch_and_checkout()` commit equality gate is unchanged. Replay does not
reset, force-push, or rerun a model after the trusted branch has advanced.

## Mac Verification

- Test-first baseline: 5 new focused tests failed before implementation because delivery state and
  handler metadata did not exist.
- Focused role suite: `173 passed, 1 skipped`.
- Full suite: `213 passed, 1 skipped`.
- `ruff check .`: passed.
- `ruff format --check .`: 73 files already formatted.
- `bash -n scripts/awf-dispatch.sh`: passed.
- Resource validation: roles 6/6, workflows 4/4, examples 3/3.
- `git diff --check`: passed.

## Remaining Verification

- Fresh Windows exact-head role suite, Ruff, format, dispatch shell syntax, SHA, and clean-tree
  checks.
- Fresh independent native Codex review at the final exact head.
- GitHub CI, PR merge, and Mac/Windows/VPS exact-version rollout.

No Agent Bus code, deployment, payload history, ACK, or requeue state was changed or inspected by
this implementation.
