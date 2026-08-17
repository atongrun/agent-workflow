# TaskCard: Fresh-Machine Usability Benchmark

## Task ID

AWF-USABILITY-FINAL

## Goal

Measure the completed usability-remediation program from fresh, no-model environments before any
new business TaskCard is authorized. The benchmark records the beginner journey as it exists; it
does not retrofit a target or add another control surface.

## Frozen contract

- Run one disposable local synthetic journey through `init`, `doctor --explain`, `start`, `run
  check`, bare `run`, `status --explain`, and `stop`/`drain` without invoking a model.
- Separately run fresh Mac, VPS, and Windows no-model Preflight journeys only against disposable
  identities and data.
- Record elapsed time, operator commands, human decisions, configuration concepts, failures, and
  remediations. Compare them with the review's explicitly unmeasured baseline hypothesis.
- Treat missing credentials, unavailable machines, stale lifecycle facts, non-empty or unknown
  queues, and incomplete Preflight evidence as fail-closed results rather than repairing around
  them.
- Only after both no-model gates pass may a separately authorized new business TaskCard be
  considered. This package never creates, reads, dispatches, ACKs, requeues, recovers, or reuses a
  business event.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@bb0d597ee6a08a48a071908a259e4d88316d6a5f`
- **Branch**: `codex/fresh-machine-acceptance`
- **Completed prerequisite**: P2 binary feasibility PR #92, deterministic result
  `NO_GO_PRODUCTION_BINARY`.

## Scope

- Benchmark and document the already merged facade and no-model Preflight behavior.
- Use disposable config/state/workspaces and synthetic task identities.
- Update repository handoff/roadmap/release notes with the measured result and first fail-closed
  boundary, if any.

## Out of scope

- Production code, schemas, services, provider/model adapters, Agent Bus protocol, Phase B, Agent
  Host, DAG, provider registry/model router, binary release work, or a live business TaskCard.
- Reading or operating events 163, 166, 173, any retained business event, or any business payload.
- Automatic ACK, requeue, recover, redispatch, retry, or weakening any provenance, delivery-hash,
  checkpoint, outbox, postflight, or PR-tuple gate.

## Verification level and budget

- **Level C milestone evidence; no new automated tests.** Existing CI remains the regression gate.
- Local Mac does not run pytest, Ruff, Rust, or Go build/test.
- Benchmark artifacts must remain credential-free and must not contain private URLs, host
  addresses, payloads, or sensitive logs.

## Acceptance criteria

- [x] The disposable local seven-command synthetic journey completes without a model invocation.
- [x] Fresh Mac, VPS, and Windows no-model Preflight evidence is either complete or stops at the
  first truthful fail-closed boundary with the missing prerequisite identified.
- [x] The report records elapsed time, commands, human decisions, configuration concepts,
  failures, and remediations without claiming an unmeasured result.
- [x] No retained/business event or production service is touched.
- [ ] Lore commit, PR, green CI, independent exact-head review, fresh mergeability, merge,
  post-merge main/CI proof, shared-memory pointer update, and short-branch cleanup complete.

## Required output

- `docs/tasks/fresh-machine-usability-benchmark-report.md`
- Repository handoff/roadmap/release-note updates limited to the measured acceptance result.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/fresh-machine-usability-benchmark.md",
    "docs/tasks/fresh-machine-usability-benchmark-report.md",
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "HANDOFF.md"
  ],
  "verification_commands": [
    ["git", "diff", "--check"],
    ["python", "-m", "compileall", "-q", "src", "scripts"]
  ]
}
-->
