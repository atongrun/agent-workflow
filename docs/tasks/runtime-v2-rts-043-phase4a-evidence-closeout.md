# TaskCard: RTS-043 Phase 4A Evidence Adjudication and Closeout

## Task ID

runtime-v2-rts-043-phase4a-evidence-closeout

## Goal

Decide, from existing immutable repository and retained acceptance evidence only, whether RTS-040,
RTS-041 and RTS-042 jointly satisfy the Frozen Runtime v2 Phase 4A exit criteria. Obtain one
independent Gate Review, repair only documentation/evidence defects, and close Phase 4A if and only
if every criterion has an exact owner and proof.

This card adds no Runtime, Agent Bus, lifecycle, launcher, migration or cleanup behavior. It creates
no event, delivery, state root, listener, service, credential or acceptance identity.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base evidence head**: `719f368ef2bfab2e9aaff4406320706bd04deb18`
- **Task branch**: `codex/runtime-v2-rts-043-phase4a-evidence-closeout`
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4A
- **Prerequisite reports**:
  - `docs/tasks/runtime-v2-rts-040-transport-envelope-implementation-report.md`
  - `docs/tasks/runtime-v2-rts-041-outgoing-intent-adapter-implementation-report.md`
  - `.awf/artifacts/impl-report-runtime-v2-rts-042-cross-machine-acceptance.md`

RTS-042 identity `rts042-live-20260820-01` remains terminal failed and
`EXTERNAL_BLOCKED / evidence preserved`. It is never PASS evidence. Identity
`rts042-live-20260820-02` is the only successful live acceptance and may be considered only as the
separately owner-authorized fresh proof recorded in the implementation report.

## Entry criteria

- RTS-040 has a strict versioned Stage-blind command/result envelope, exact identity/causation
  tests, independent Review PASS and exact-head CI evidence.
- RTS-041 has a Store-owned exact outgoing intent, attempt-before-I/O sender, conservative
  ambiguity/no-replay behavior, independent focused re-review PASS and exact-head CI evidence.
- RTS-042 preserves the first post-send failure without retry/requeue/ACK/replacement, records its
  component-owned failure chain and local Git-blob repair, and records one independently fresh
  two-event cross-machine success.
- No production/retained event, Runtime default, production state, migration, release or Phase 4B
  lifecycle action is needed to adjudicate the evidence.

## Frozen review questions

The independent Reviewer must answer with exact file/line or immutable run evidence:

1. Does RTS-040 prove one stable, versioned, Stage-blind command/result envelope whose malformed,
   foreign or mismatched input denies before application/provider entry?
2. Does RTS-041 prove that the selected Store owns exact reconstructable outgoing bytes and records
   `attempting` before I/O, without interpreting send as handler success or ACK and without replaying
   ambiguous sends?
3. Did RTS-042's successful identity exercise the RTS-040 envelope and unmodified RTS-041
   dispatcher over a real independently versioned Agent Bus across Mac and Windows?
4. Do two real bounded child processes, two handler-success ACK records and scoped
   `0/0 -> 0/0` queue evidence exist for the successful identity, without a model/business handler?
5. Is `rts042-live-20260820-01` still excluded from PASS, with its failure and `retry_count=1`
   correctly owned by the Windows listener/Agent Bus server rather than Runtime v2?
6. Is `rts042-live-20260820-02` the only successful acceptance, with no retry, requeue, manual ACK,
   replacement delivery, manufactured completion or hidden fallback?
7. Were production/retained events untouched and Agent Bus kept independently versioned?
8. Do the three TaskCards jointly satisfy every Phase 4A exit criterion without changing the
   Frozen contract or expanding Runtime ownership?

## Writable scope

- `docs/tasks/runtime-v2-rts-043-phase4a-evidence-closeout.md`
- `.awf/artifacts/review-report-runtime-v2-rts-043-phase4a-evidence-closeout.md`
- `docs/tasks/runtime-v2-rts-043-phase4a-evidence-closeout-report.md`
- `docs/plans/runtime-v2-development-plan.md`
- `HANDOFF.md`
- `ROADMAP.md`

## Prohibited actions

- Any edit under `src/`, `scripts/`, `tests/`, schemas, packaging, workflows or dependencies.
- Any Agent Bus query or operation against production, retained or previous acceptance state.
- Any retry, requeue, ACK, resend, redispatch, replacement identity or third live acceptance.
- Any deletion or cleanup of retained RTS-042-01 evidence.
- Runtime/transport/lifecycle/launcher abstraction, Agent Bus feature, migration, default switch,
  release, service action or Phase 4B implementation.
- Treating pending-zero, process exit or later success as proof that the failed delivery ACKed.

## Exit criteria

- [ ] Independent Gate Reviewer returns `PASS`, or all evidence-backed documentation findings are
      repaired and a focused independent re-review returns `PASS`.
- [ ] The closeout report maps all five Phase 4A exit criteria to RTS-040/041/042 evidence and names
      any remaining limitation without semantic inflation.
- [ ] The report states that RTS-042-01 remains `EXTERNAL_BLOCKED`, is retained, and is never future
      PASS evidence.
- [ ] The report states that RTS-042-02 is the only successful live acceptance and proves exactly
      two ACKed events, two zero-exit child processes, `attempting -> sent`, and `0/0 -> 0/0`.
- [ ] No retry/requeue/manual ACK/replacement/manufactured completion or third identity occurred.
- [ ] Frozen contract semantics, Agent Bus ownership and Runtime product boundary are unchanged.
- [ ] Changed paths are documentation/evidence only and remain inside this card's writable scope.
- [ ] `git diff --check`, credential/path scan and exact-head documentation checks pass.
- [ ] HANDOFF, ROADMAP and the authoritative plan name Phase 4A closed only after Reviewer PASS.
- [ ] The next action is a separately frozen Phase 4B TaskCard, not lifecycle implementation in
      this card.

## Failure handling

- Documentation/evidence inconsistency: repair narrowly, focused validation, then focused re-review.
- Architectural/invariant conflict: do not modify implementation; record a later ADR requirement
  and stop `PLAN_CONFLICT`.
- Missing or untrustworthy retained evidence: do not manufacture replacement evidence or another
  acceptance; return `BLOCKED`.

## Required output

- one independent Gate Review report;
- one RTS-043 Phase 4A closeout report;
- minimal plan, HANDOFF and ROADMAP gate updates after PASS.
