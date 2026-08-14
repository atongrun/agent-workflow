# TaskCard: P0-1 Canonical State-Root Contract

## Goal

Make one resolved host-local state root authoritative for every node-managed listener and every
run record it creates, while retaining an explicit legacy direct-entry default-resolution path.

## Scope

- Resolve `NodeProfile.state_root` once and pass that exact absolute path to the listener and every
  generated business/preflight handler.
- Bind the process record, listener lease, `RunEvidence`, RunLedger context, delivery checkpoint,
  business outbox, Feedback Outbox, readiness, and status to the same root by exact path locally
  and a credential-free SHA-256 binding in persisted/operator evidence.
- Reject profile/argv/environment disagreement before Agent Bus connect and reject handler
  disagreement before provider/model invocation.
- Preserve direct handlers through the documented precedence `--state-root`, then
  `AWF_STATE_ROOT`, then the platform default.

## Out of Scope

- Lifecycle vocabulary/state redesign, durable installed-profile work, contract compiler,
  implement-to-rework repair, status redesign, Agent Host, binary packaging, Phase B, or Agent Bus
  Core changes.
- Any read, ACK, requeue, recovery, redispatch, or payload use for historical events 163/166 or
  retained rework event 173. No live business event is used for verification.

## Working Context

- **Repository**: `atongrun/agent-workflow`
- **Base branch and exact baseline**: `main@f17df2bbf0a133521953a535463905fd93be9e22`
- **Task branch**: `codex/canonical-state-root`
- **Entry points**: `src/agent_workflow/node.py`, `src/agent_workflow/status.py`,
  `scripts/awf_listen.py`, `scripts/awf_role.py`, `scripts/awf_control_plane.py`,
  `scripts/awf_feedback.py`, and existing focused tests.
- **Existing invariants**: handler-success business ACK; separate business/Finding ACK; existing
  provenance, checkpoint, outbox, postflight, and PR-tuple fail-closed gates remain unchanged.

## Binding Inventory

| Surface | Required binding |
|---|---|
| process record | resolved root path plus binding digest |
| listener lease | same resolved root path plus binding digest |
| `RunEvidence` | event evidence under the root plus binding digest in `result.json` |
| RunLedger context | binding digest in the checksummed context packet |
| delivery checkpoint | binding digest in each recovery record |
| business outbox | binding digest in each prepared delivery record |
| Feedback Outbox | naturally below the same root and occurrence record carries the binding digest |
| readiness/status | profile provenance plus binding digest; no credential values |

## Verification Level and Budget

- **Level B**; add exactly two focused regression tests.
- Test 1: custom non-default root propagation through representative node, run, checkpoint/outbox,
  Feedback, readiness, and status evidence using existing fixtures/assertions.
- Test 2: mismatched root fails before mocked Agent Bus connect and provider/model invocation.
- Do not add an OS matrix, per-record tests, snapshots, or copied production algorithms. If test
  growth approaches production growth, consolidate assertions first.

## Baseline Metrics

- User-authored objects on the supported path: one node profile plus existing owner/runtime
  artifacts; P0-1 adds none.
- State-root choices: profile-bound node path has one; legacy direct entry retains one optional CLI
  flag/environment override.
- Current failure boundary: divergence can survive listener start and be discovered after Bus
  connection or inside a handler. Target boundary: listener mismatch before Bus connect; handler
  mismatch before model invocation.
- Elapsed time: not measured; this is not a fresh-environment benchmark.
- Compatibility: existing platform-default direct-entry fixtures must remain green; live platform
  lifecycle facts remain outside this synthetic package.

## Acceptance Criteria

- [ ] Node-generated listener argv and all generated handler commands carry the exact profile root.
- [ ] Every inventoried surface is path-bound or digest-bound to the same root.
- [ ] Root mismatch performs no Bus connect and no provider/model invocation.
- [ ] Direct entry has documented deterministic default resolution.
- [ ] Exactly two focused regressions cover propagation and fail-closed behavior.
- [ ] GitHub CI is green and an independent review approves the exact PR head.

## Verification

Local Mac: static inspection and `git diff --check` only. Full Ruff, Pytest, resource, installed
wheel, and platform verification runs in GitHub CI.

## Required Output

- `docs/tasks/canonical-state-root-contract-implementation-report.md`
- Necessary architecture/HANDOFF updates, one Lore commit series, PR, green CI, and independent
  review evidence.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/canonical-state-root-contract.md",
    "docs/tasks/canonical-state-root-contract-implementation-report.md",
    "docs/runtime-node-lifecycle-architecture.md",
    "HANDOFF.md",
    "README.md",
    "src/agent_workflow/node.py",
    "src/agent_workflow/state_root.py",
    "src/agent_workflow/status.py",
    "src/agent_workflow/cli.py",
    "scripts/awf_listen.py",
    "scripts/awf_role.py",
    "scripts/awf_control_plane.py",
    "scripts/awf_feedback.py",
    "tests/test_node.py",
    "tests/test_awf_role.py",
    "tests/test_control_plane.py",
    "tests/test_status.py",
    "tests/test_awf_feedback.py",
    "schemas/node-profile.schema.json"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_node.py", "tests/test_awf_role.py", "tests/test_status.py", "tests/test_awf_feedback.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
