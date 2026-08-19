# ImplementationReport: RTS-011 Review-After-Rework Authorization Gate

## Outcome

The current Python RunLedger can now authorize the exact bounded sequence
`implement -> review -> rework -> review` without raising the per-delivery provider-attempt limit
or weakening the rework budget. Each authorized rework unlocks at most one additional review-stage
slot; both distinct review deliveries still carry input `attempt=1`.

This closes only the source prerequisite identified by `CG-1` / `F-AUTH-004`. RTS-011 remains open
until its separate disposable scripted-provider acceptance proves provider counts, exact rework
lineage, redelivery behavior, restart recovery, outbox/inbox, handler-success ACK and terminal
ordering.

## Frozen authority and implementation

- Base: `main@41ce9c1df54c44488c05fc90b4033b11d4e74922`
- Branch: `codex/runtime-v2-rts-011-review-loop-gate`
- Frozen TaskCard commit: `1d0895c`
- Initial implementation commit: `fe2d7e4`
- Exact green implementation head: `b270a02`
- Pull request: #100

The production change in `scripts/awf_control_plane.py`:

- permits `rework -> review` only after the ledger records an authorized rework;
- keeps `attempt <= max_attempts` unchanged for every input delivery;
- sets only review-stage cumulative capacity to `max_attempts + authorized_reworks`;
- leaves implement, rework and every other stage at `max_attempts`;
- leaves rework-budget, duplicate/reuse, route, terminal, packet and pre-provider authorization
  behavior unchanged.

Focused direct-ledger and production role-wrapper regressions prove the allowed sequence, both
review attempts at 1, exact final counters, the denied third review and second rework, duplicate
replay, and fail-closed review from an unbacked `rework` stage.

## Independent review

The TaskCard received an initial `FAIL` because its first draft made owner intent model-writable and
did not use the compiled Artifact identities. After remediation, TaskCard Review 2 returned `PASS`
with zero findings and reproduced the artifact compiler plus Task ID/branch-leaf invariant.

The independent implementation Reviewer returned `PASS` with zero findings for the frozen source,
tests and compiled reports. The same Reviewer then examined each CI-driven assertion correction:

- filtering authorized review events from durable rejected-event evidence — `PASS`;
- the formatter-prescribed mechanical line join — `PASS`;
- treating an absent pre-authorization `stage_attempts` field as zero consumption — `PASS`.

No Reviewer edited the implementation.

## CI failure and remediation record

Ordinary failures were retained as evidence and repaired rather than treated as stop conditions:

1. Run `32295177578` reached 646 passed / 5 skipped and failed two new test assertions. The tests
   incorrectly indexed `stage` on durable rejected events and expected a denial to erase its audit
   record. Commit `066b39e` filters authorized review events and asserts the exact rejection while
   preserving zero counters.
2. Run `32295557960` failed before pytest on Ubuntu and Windows because Ruff required one
   comprehension line join. Commit `e3a3b40` applied exactly the formatter output.
3. Run `32295810205` reached 647 passed / 5 skipped and exposed that `stage_mismatch` occurs before
   `stage_attempts` is initialized. Commit `b270a02` accepts field absence as the same zero-consumed
   state without accepting a non-empty counter.

The Binary run paired with the third ordinary attempt had an unrelated macOS arm64 GitHub API
`403 rate limit exceeded` while resolving `python-build-standalone`. The fresh final implementation
head cleared that external boundary without a workflow or product-code change.

At exact implementation head `b270a02`:

- ordinary CI run `32296030440` passed Ubuntu full pytest/Ruff (648 passed, 5 skipped), Windows
  recovery/configuration, macOS runtime and installed-wheel jobs on Ubuntu, Windows and macOS;
- Binary Feasibility run `32296030380` passed Linux arm64/x86_64, macOS arm64/x86_64, Windows
  x86_64 and the aggregate job;
- local Mac static checks (`compileall`, `git diff --check`, changed-path audit) passed; pytest and
  Ruff were not run locally under repository policy.

The owner-only closeout commit changes the publication head, so merge still requires fresh
exact-head CI and an independent final exact-head Reviewer. Those are PR integration evidence, not
substitutes for the green implementation head above.

## Safety and remaining gate

No provider, Agent Bus, listener, queue, event, remote node, retained delivery, production,
default, release, migration or destructive action was performed. No global attempt budget was
raised, and this change authorizes no live acceptance by itself.

The next legal TaskCard is the disposable scripted-provider RTS-011 acceptance. It must use fresh
isolated identities and must disclose synthetic paths; it may not inspect or operate retained
business deliveries.
