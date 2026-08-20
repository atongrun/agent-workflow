# RTS-024 Product Boundary and Implementation Choice Closeout

Status: **PASS — PYTHON + NATIVE LAUNCHER / CONTRACT FROZEN**

Date: 2026-08-20

TaskCard: [`runtime-v2-rts-024-decision.md`](runtime-v2-rts-024-decision.md)

ADR: [`ADR-0006`](../adr/0006-runtime-v2-product-boundary-implementation-choice.md)

Pull request: [#106](https://github.com/atongrun/agent-workflow/pull/106)

## Owner decision

Runtime v2 uses a Python refactor, checksummed atomic-file RunStore plus per-invocation journal API,
and one logical Workflow writer without a physical always-on Coordinator. The Core has the narrow
owner boundary recorded in ADR-0006. RTS-023 does not enter; Rust remains a comparison oracle and
SQLite remains valid but unselected evidence.

The native launcher is a later bounded distribution candidate only after Phase 3 stabilizes the
Python package/application boundary. It is not accepted production distribution and cannot weaken
Runtime semantics or automatically reopen Rust if it stops.

## Same-fixture evidence

RTS-020 Python, RTS-021 atomic/SQLite and RTS-022A/B Rust all use the same 14-row language-neutral
comparison. Atomic and SQLite remove the same four named local ordering windows; SQLite adds no
unique Workflow ownership reduction. Rust passes five native targets and the maintainer gate, but
its external-boundary evidence remains disposable/synthetic compared with current Python production,
real providers, Agent Bus/ACK, Git/GitHub, lifecycle and downstream dogfood.

The adversarial Reviewer corrected one measurement-head ambiguity: Python runner was 1,380 lines on
pre-final-review head `77c7023` and 1,396 on repair head `457a336`; the RTS-020 provider measurement
remains 74 and Rust numerator 3,471. The correction did not change the owner decision.

## Review and freeze

- Independent Architecture Review: `PASS`.
- Separate independent Adversarial Review: one repairable evidence finding.
- Repair `5da55fd` plus same-Reviewer focused re-review: `PASS`.
- ADR-0006: `Accepted`.
- `awf.semantic-contract.v1`: `Frozen`.
- Normative fault matrix: `Frozen`, 39 cases and 11 outcomes unchanged.

## Safety boundary

RTS-024 changed documents/evidence only. It performed no production implementation, state-format
migration, dual write, default switch, release, launcher implementation, retained-event operation,
live service/queue/provider mutation, remote business write or destructive cleanup.

## Next gate

Phase 2 is complete. Phase 3 enters through a separately frozen `RTS-030` TaskCard for the selected
Python local Runtime Core interfaces and enforceable package boundary. That card must remain
independently reversible, keep current Python production as default, avoid dual write and preserve
legacy representations until replacement fixtures and live-dependency gates pass.
