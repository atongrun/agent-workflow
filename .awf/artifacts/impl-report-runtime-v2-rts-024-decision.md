# RTS-024 Decision Implementation Report

## Result

The owner-selected Runtime v2 route is `PYTHON + NATIVE LAUNCHER`: a Python refactor for the
production Runtime boundary plus one later, independently stoppable native-launcher distribution
candidate after the Python package/application boundary is accepted.

ADR-0006 selects:

- checksummed atomic-file RunStore plus one per-invocation journal API;
- one logical Workflow transition writer without a physical always-on Coordinator;
- narrow fully bound InvocationSpec renderers for Codex, OpenCode and Pi;
- a Runtime Core limited to RunSpec, Workflow authority, invocation recovery, exact Artifact/
  workspace/Git lineage, bounded rework, terminal, read-only status, exact stop and Agent Bus
  handoff identity/intent/provenance semantics;
- Feedback as an optional compatibility utility outside normal `run/status/stop` and business
  terminal/ACK authority;
- native lifecycle limited to exact process/incarnation safety.

Production Rust, Go fallback, SQLite, a physical Coordinator and immediate broad scope expansion are
rejected for this route without denying the validity of their completed comparison evidence.

## Evidence and reviews

The decision uses the same 14-row fixture evidence from RTS-020 Python, RTS-021 atomic/SQLite and
RTS-022A/B Rust. It explicitly discloses that Python also has real production/provider/Bus/GitHub/
lifecycle/dogfood evidence while Rust has a disposable five-target slice and bounded maintainer gate.

Independent Architecture Review returned `PASS`. A separate Adversarial Review returned one
repairable LOC-head finding; commit `5da55fd` distinguished Python runner 1,380 at `77c7023` from
1,396 at repair head `457a336`, retained the reported 74-line provider fixture and the Rust 3,471
numerator, and changed no decision. Focused re-review returned `PASS`.

After both PASS verdicts, ADR-0006 became `Accepted`, and the semantic contract plus 39-case/
11-outcome fault matrix became `Frozen`. The promotion changed no normalized outcome, prohibited
effect or external owner.

## Boundaries

No production source, script, schema, CLI, state representation, provider adapter, lifecycle code,
fixture, experiment, dependency or CI workflow changed. No production/default/migration/release,
launcher implementation, dual write, silent fallback, ambiguous replay, state rollback,
retained/live event operation, remote business mutation or destructive cleanup occurred.

## Verification

- strict duplicate-key JSON parse;
- exact 39 unique fault cases and 11 outcomes;
- all outcome and evidence references resolve to the Frozen contract;
- local documentation links resolve;
- changed paths are within the RTS-024 TaskCard;
- `git diff --check` passes;
- independent Architecture Review PASS;
- independent Adversarial Review and focused re-review PASS.

<!-- awf-implementation-report
{
  "summary": "Record the owner-selected Python plus deferred native-launcher route, atomic RunStore/journal, logical writer and narrow Runtime v2 product boundary, then freeze the semantic contract after two independent reviews.",
  "changed_files": [
    "docs/tasks/runtime-v2-rts-024-decision.md",
    "docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md",
    "docs/adr/0001-project-boundaries.md",
    "docs/adr/0002-contract-first-design.md",
    "docs/adr/0005-high-value-model-capacity-isolation.md",
    "docs/runtime-v2-semantic-contract.md",
    "docs/testing/runtime-v2-fault-matrix.md",
    "docs/testing/runtime-v2-fault-matrix.json",
    "docs/reviews/2026-08-20-runtime-v2-rts-024-architecture-review.md",
    "docs/reviews/2026-08-20-runtime-v2-rts-024-adversarial-review.md",
    ".awf/artifacts/impl-report-runtime-v2-rts-024-decision.md"
  ],
  "commands": [
    "strict duplicate-key fault-matrix validation",
    "evidence/outcome reference and local-link validation",
    "changed-path audit",
    "git diff --check"
  ],
  "tests": [
    "39 unique Frozen fault cases and 11 normalized outcomes PASS",
    "Independent Architecture Review PASS",
    "Independent Adversarial Review PASS after focused LOC evidence repair"
  ],
  "source_revision": "5da55fda62119eec01844e5d6c52f91d5dd187ba"
}
-->
