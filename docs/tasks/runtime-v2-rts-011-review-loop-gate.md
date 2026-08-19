# TaskCard: RTS-011 Review-After-Rework Authorization Gate

## Task ID

runtime-v2-rts-011-review-loop-gate

## Goal

Make the current Python reference capable of authorizing the second review in the already-frozen
RTS-011 sequence without weakening per-delivery attempt, rework-budget, duplicate, route, terminal,
or stage gates:

```text
implement -> review -> rework -> review
```

This is a narrow prerequisite correction. It does not itself satisfy RTS-011; the complete
disposable scripted-provider/restart/ACK/terminal acceptance remains the next TaskCard.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@41ce9c1df54c44488c05fc90b4033b11d4e74922`
- **Task branch**: `codex/runtime-v2-rts-011-review-loop-gate`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 1 / RTS-011 prerequisite
- **Draft faults**: `CG-1` and `F-AUTH-004`

RTS-010 is integrated and passed. Current source permits `implement -> review` but rejects
`rework -> review` as `stage_mismatch`. Even if that transition alone were opened, the existing
per-stage counter would reject the second review because `max_attempts=1`. The input `attempt`
value is a per-delivery provider-attempt bound and must remain 1 for each distinct review delivery;
it must not be raised globally to make the Workflow loop fit.

## Frozen semantics

1. Initial review remains legal only after implement.
2. A review after rework is legal only when the RunLedger records at least one authorized rework.
3. Review-stage cumulative capacity is `max_attempts + authorized reworks`; each consumed rework
   unlocks at most one corresponding follow-up review.
4. The input delivery's `attempt` must still be within the unchanged `max_attempts` bound. With the
   current owner contract, both review deliveries use `attempt=1`.
5. Implement, rework, and all other stage counters retain the existing `max_attempts` limit.
6. Rework authorization still consumes the unchanged owner-frozen `rework_budget`; no review can
   create or replenish rework budget.
7. Duplicate delivery, delivery-ID reuse, route, terminal, immutable packet, state-root, and
   authorization-before-provider behavior remain unchanged.

## Frozen model-writable scope

- `scripts/awf_control_plane.py`
- `tests/test_control_plane.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-011-review-loop-gate.md`
- `.awf/artifacts/review-report-runtime-v2-rts-011-review-loop-gate.md`

The committed TaskCard is frozen owner intent and is not model-writable. After the model-writable
implementation and ReviewReport pass, the owner may add
`docs/tasks/runtime-v2-rts-011-review-loop-gate-implementation-report.md` and make gate-status-only
updates to `docs/plans/runtime-v2-development-plan.md`, `HANDOFF.md`, and `ROADMAP.md`. Those owner
closeout paths are not part of the compiled model-write allowlist.

## Out of scope

- Provider, Agent Bus, listener, queue, event, remote-node, production, retained-delivery, default,
  release, migration, or destructive actions.
- A global `max_attempts=2`, a second implement allowance, an expanded rework budget, or a bypass
  around an already consumed authorization.
- Changing payload format, route names, checkpoint/outbox/inbox ordering, Artifact/provenance
  behavior, terminal handling, language, store, Coordinator topology, or CLI.
- Claiming RTS-011 or Phase 1 complete before the separate disposable acceptance passes.

## Acceptance criteria

- [ ] A ledger with `max_attempts=1` and `rework_budget=1` authorizes exactly
      `implement -> review -> rework -> review` with distinct delivery identities.
- [ ] Both reviews use input `attempt=1`; per-delivery attempt 2 remains denied.
- [ ] Stage attempts end as `implement=1`, `review=2`, `rework=1`, with total attempts 4 and
      reworks 1.
- [ ] A third distinct review is denied until another authorized rework exists; with budget 1, a
      second rework is denied.
- [ ] A run merely initialized at stage `rework` without an authorized rework cannot enter review.
- [ ] Existing duplicate/reuse, stage, attempt, rework-budget, terminal, and packet tests remain
      green.
- [ ] Ordinary cross-platform CI and Binary Feasibility pass on the exact publication head.
- [ ] Independent implementation Reviewer and final exact-head Reviewer return `PASS`.
- [ ] No live or external Runtime state is changed by this TaskCard.

## Verification

- Add focused direct-RunLedger regressions for the exact allowed and denied sequences.
- Add a role-wrapper regression proving distinct reviewer deliveries both retain `attempt=1`.
- Run focused control-plane tests and the full repository pytest/Ruff suite in GitHub CI.
- Run `git diff --check` and changed-path audit.
- Use an independent Reviewer Agent before publication and again at the exact PR head.

Mac local execution remains static only. Pytest/Ruff and platform validation run in GitHub CI under
the repository policy.

## Required output

- the minimal gate correction and regression tests;
- `.awf/artifacts/impl-report-runtime-v2-rts-011-review-loop-gate.md`;
- `.awf/artifacts/review-report-runtime-v2-rts-011-review-loop-gate.md`;
- a later owner-authored `docs/tasks/runtime-v2-rts-011-review-loop-gate-implementation-report.md`;
- independent Reviewer evidence and exact-head CI evidence before merge.

## Independent TaskCard review history

### Review 1 — `FAIL`

The Reviewer found that the first draft made the frozen TaskCard model-writable and used a docs
ImplementationReport instead of the compiled `.awf/artifacts/` implementation/review identities.
It also prompted an owner-side check of the Task ID/branch-leaf invariant.

Remediation: make Task ID equal the task branch leaf, remove all owner closeout files from the
model-write allowlist, add exactly the compiled ImplementationReport and ReviewReport paths, and
separate later owner closeout from model output. A direct `compile_run_artifact_contract()` check
now passes, and `derive_manifest()` returns an exact task ID/branch-leaf match.

### Review 2 — `PASS`

The independent Reviewer returned `PASS` with zero findings. It reproduced the run-artifact
contract compile, manifest derivation/validation, Task ID/branch-leaf equality, postflight JSON,
whitespace check, fault basis, and model/owner scope separation. Implementation may begin from this
frozen authority.

<!-- awf-postflight
{
  "allowed_paths": [
    "scripts/awf_control_plane.py",
    "tests/test_control_plane.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-011-review-loop-gate.md",
    ".awf/artifacts/review-report-runtime-v2-rts-011-review-loop-gate.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_control_plane.py"],
    ["{python}", "-m", "pytest", "-q"],
    ["ruff", "check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
