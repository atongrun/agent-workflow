# ImplementationReport — Runtime v2 RTS-011 Review Loop Gate

Task: `runtime-v2-rts-011-review-loop-gate`
Base: `41ce9c1df54c44488c05fc90b4033b11d4e74922`
Branch: `codex/runtime-v2-rts-011-review-loop-gate`

## Changed

- `scripts/awf_control_plane.py`
  - permits `rework -> review` only when the ledger records an authorized rework;
  - keeps the input delivery's `attempt <= max_attempts` check unchanged;
  - gives only the review stage cumulative capacity `max_attempts + authorized_reworks`;
  - leaves every other stage at the existing `max_attempts` capacity and leaves rework-budget,
    duplicate, route, terminal, packet, and authorization ordering unchanged.
- `tests/test_control_plane.py`
  - locks the exact allowed `implement -> review -> rework -> review` sequence;
  - proves both review deliveries use `attempt=1` and attempt 2 remains denied;
  - proves rejected attempts do not consume counters, a third review and second rework remain
    denied, and final counters/transitions are exact;
  - proves an unbacked initial `rework` stage cannot enter review;
  - proves the production role wrapper carries two distinct review deliveries with attempt 1.

## Verification

Local Mac verification is static under repository policy:

- `python3 -m compileall -q scripts/awf_control_plane.py tests/test_control_plane.py` — PASS;
- `git diff --check` — PASS;
- changed paths before Review are limited to the two model-writable source/test paths plus this
  compiled ImplementationReport.

Pytest and Ruff are intentionally deferred to GitHub ordinary cross-platform CI. Binary
Feasibility and exact-publication-head CI are later merge gates.

## Safety and limitations

- No global attempt budget was raised. A second implement remains impossible under
  `max_attempts=1`.
- An additional review is causally bounded by the count of already authorized reworks; a review
  does not create rework authority.
- This implementation does not itself satisfy RTS-011. The disposable scripted-provider sequence,
  restart recovery, duplicate/redelivery, outbox/inbox, handler-success ACK, terminal ordering, and
  synthetic-path disclosure remain the next acceptance TaskCard.
- No provider, Agent Bus, listener, queue, event, remote node, retained delivery, production,
  default, release, migration, or destructive action was performed.

## Review gate

An independent Reviewer must check the frozen semantics, source, regressions, report, and exact
allowlist. Any finding is repaired and re-reviewed before publication.
