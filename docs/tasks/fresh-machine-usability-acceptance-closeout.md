# TaskCard: Fresh-Machine Usability Acceptance Closeout

## Task ID

AWF-USABILITY-FINAL-CLOSEOUT

## Goal

Record the separately authorized, fully isolated no-model acceptance rerun that cleared the
original `BLOCKED_BEFORE_DEEP` boundary. Preserve the first benchmark as historical evidence while
making the repository's current handoff, roadmap, and release notes state the final measured gate.

## Frozen contract

- Accept only credential-safe evidence from fresh Mac, VPS, and Windows installations at the exact
  merged main revision.
- The rerun must use an independent disposable Agent Bus process, SQLite database, tokens,
  configuration, state roots, repositories, and listeners. It must not inspect or operate any
  production or retained delivery.
- Fast Preflight must pass all nine layers on all three hosts with payload-blind architect and
  coder pending counts observed at zero.
- Deep Preflight must complete one genuinely cross-machine, no-model request/result route, require
  successful handler children, return both scoped queues to zero, and produce normal ACK evidence.
- Cleanup must remove every disposable secret, process, repository, environment, database, log,
  report, and local branch without stopping or changing a production service.
- This closeout changes documentation only. It does not authorize or invent a business TaskCard.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@83e706b1339dd3fbac64576abf25a1b61d5840bd`
- **Branch**: `codex/fresh-machine-acceptance-closeout`
- **Historical benchmark**: PR #93, which truthfully stopped at `BLOCKED_BEFORE_DEEP` before the
  separate disposable-environment authorization existed.

## Scope

- Add one credential-free closeout report.
- Update the historical benchmark report with a clearly separated follow-up result.
- Update current handoff, roadmap, and changelog truth.

## Out of scope

- Production code, schemas, services, Agent Bus protocol, model/provider adapters, Phase B, Agent
  Host, DAG, provider registry/model router, binary release work, or a live business TaskCard.
- Reading, identifying, operating, ACKing, requeueing, recovering, redispatching, or reusing any
  production, retained, or business event.
- Weakening provenance, delivery-hash, checkpoint, outbox, postflight, PR-tuple, queue, or ACK
  gates; business ACK and Finding ACK remain separate.

## Verification level and budget

- **Level C documentation closeout.** Existing GitHub CI is the regression gate.
- Local Mac runs only `compileall`, `git diff --check`, and allowed-path inspection; no pytest,
  Ruff, Rust, or Go build/test.
- Independent review must inspect the exact PR head using Pi with `opencode-go` / `glm-5.2`.

## Acceptance criteria

- [x] Three fresh Fast Preflight runs passed all nine layers with scoped queues at zero.
- [x] One Mac-to-Windows Deep Preflight completed with two distinct disposable control events,
  successful handlers/children, ACK evidence, and queues `0/0 -> 0/0`.
- [x] Post-proof payload-blind audit found exactly two acknowledged Preflight records and no
  pending, delivered, failed, or non-acknowledged record.
- [x] Disposable Mac, VPS, and Windows resources were removed and the production Bus remained
  active under its distinct identity.
- [ ] Lore commit, PR, green CI, independent exact-head review, fresh mergeability, merge,
  post-merge main/CI proof, shared-memory update, and short-branch cleanup complete.

## Required output

- `docs/tasks/fresh-machine-usability-acceptance-closeout-report.md`
- Current benchmark, handoff, roadmap, and changelog updates limited to the measured result.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/fresh-machine-usability-acceptance-closeout.md",
    "docs/tasks/fresh-machine-usability-acceptance-closeout-report.md",
    "docs/tasks/fresh-machine-usability-benchmark-report.md",
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
