# RTS-022B Independent Maintainer Fault Gate Closeout

Status: **RUST_MAINTAINER_GATE_PASS**

Date: 2026-08-20

TaskCard: [`runtime-v2-rts-022-maintainer-fault-gate.md`](runtime-v2-rts-022-maintainer-fault-gate.md)

Pull request: [#105](https://github.com/atongrun/agent-workflow/pull/105)

## Result

A fresh maintainer with no RTS-022A implementation or review context diagnosed and repaired one
owner-injected Candidate fault in one semantic attempt. The maintainer used only the current source,
frozen contract, existing shared fixture/tests and exact seeded-head CI logs; it attested that it did
not inspect seed-parent diffs, patch history, blame, reflog, bisect, GitHub commit patches or owner
hints before submitting the repair.

The injected status projection incorrectly returned `SAFE_CONTINUE` for durable implement launch
intent without a trusted result. All five Rust targets compiled and then failed the same existing
`S-AUTH-START-LAUNCH-NO-RESULT` row. The maintainer identified the Candidate invariant—launch intent
without recoverable result is ambiguous and must never replay—and restored
`AMBIGUOUS_NO_REPLAY`. The repair changed one line, exactly reversed the seed, and left the final
Rust source byte-identical to the RTS-022A-passed `origin/main` source.

## Gate evidence

- Frozen TaskCard correction: `c3d373f78b25b4fb0db2261255fc2b73fc6c3b9c`.
- Independent pre-seed TaskCard Review PASS: `2026-08-20T02:14:55.667Z`, persisted Codex turn
  `01a01cf3-01fc-7a22-8790-45c2f5b28be3`.
- Stable transcript extraction digest:
  `b9afba26ccb46316a27d027b1bb3f6eff5de96a917a60a6d7fb0163e92bb49c1`.
- Blinded seed: `1731a4b95079c6b6c3532fbb88b0764cdcdaf05b`, committed 47 seconds after
  the TaskCard PASS.
- Seeded ordinary CI `32324044948`: PASS.
- Seeded Binary Feasibility `32324044913`: five Rust fmt/Clippy/build PASS cells followed by the
  same expected shared-suite failure.
- Single semantic repair: `3ba1db590587071cd69708c5806207311451468e`.
- Candidate evidence head: `194e6398d993735ba2927f8e8547dc9bc60643e6`.
- Candidate ordinary CI `32324509595`: PASS, including full pytest/Ruff, wheel/platform and Windows
  recovery/configuration jobs.
- Candidate Binary Feasibility `32324509603`: PASS, including all five Rust cells, strict Rust
  aggregate and existing native candidate jobs.
- Independent Gate Review: PASS after verifying full seed/repair history and existing pre-seed
  transcript evidence.

The initial candidate Review returned `STOP_RUST_MAINTAINER_SCOPE` only because the pre-seed PASS was
not yet linked from repository evidence. No semantic change followed. The same Reviewer verified the
immutable timestamped transcript, digest and commit ordering and closed that evidence-only finding.

## Budget and boundaries

The gate used one owner seed, one fresh maintainer, one semantic repair candidate, one candidate CI
matrix and one independent Gate Reviewer. It used no second hypothesis, mechanical repair, new test,
dependency, module, fixture, workflow, abstraction, framework or production path. Rust remains zero
dependency and the RTS-022A LOC/maintenance/distribution measurements are unchanged.

No production/default/release/migration, live/retained state, Agent Bus, provider, queue, remote Git,
ACK, destructive or historical recovery action occurred. The result proves only that a fresh
maintainer can repair this bounded Rust Candidate fault from documented evidence.

## Next gate

RTS-022 is complete. RTS-023 does not enter because Rust did not hit a Rust-specific stop. RTS-024
is now `OWNER_DECISION_REQUIRED`: the owner must accept one written product-boundary and
implementation-choice ADR covering language, Store, logical-versus-physical Coordinator and scope.
No Phase 3 implementation, semantic-contract Frozen promotion, production Runtime choice, default
switch, migration or release is authorized by this report.

The final closeout head still requires exact-head ordinary CI, Binary Feasibility and a focused
same-Reviewer verification that the evidence-only closeout introduced no L3 change before merge.
