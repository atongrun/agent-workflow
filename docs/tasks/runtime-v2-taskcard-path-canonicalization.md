# TaskCard: Canonicalize compiled TaskCard identity across operating systems

## Task ID

`runtime-v2-taskcard-path-canonicalization`

## Context

RTS-010 fresh authority r2 stopped before provider invocation because Windows `awf run` persisted
the TaskCard field with `\` separators while the canonical delivery and role handler used `/`.
RunLedger correctly rejected the immutable identity drift. The failed r2 event, ledger and queue are
retained evidence and are outside this TaskCard; no ACK, requeue, redispatch or hot repair is allowed.

## Goal

Make the owner-side `awf run` context packet use the same repository-relative POSIX TaskCard
identity on every supported OS. Preserve every other packet, compiler, authorization, budget,
delivery, provider, outbox, inbox and terminal semantic.

## Allowed changes

- `src/agent_workflow/cli.py`
- `tests/test_cli.py`
- `docs/tasks/runtime-v2-taskcard-path-canonicalization.md`
- `docs/tasks/runtime-v2-taskcard-path-canonicalization-implementation-report.md`
- `docs/plans/runtime-v2-development-plan.md`
- `HANDOFF.md`
- `ROADMAP.md`

## Acceptance criteria

- `awf run` writes a nested repository-relative TaskCard identity with `/` separators on macOS,
  Linux and Windows.
- A cross-platform regression asserts the exact canonical packet value.
- Existing compiled RunContract and first-role-gate regressions remain green.
- Ruff, the full pytest matrix, installed-wheel checks and Binary Feasibility pass on exact head.
- An independent Reviewer finds no unresolved correctness, safety or scope issue.
- No live Bus, retained event, provider, queue, production/default, migration or release action is
  performed by this TaskCard.

## Verification

```text
python -m pytest tests/test_cli.py tests/test_control_plane.py
python -m pytest
python -m ruff check .
git diff --check
```

The Mac execution policy delegates pytest and Ruff to GitHub CI.
