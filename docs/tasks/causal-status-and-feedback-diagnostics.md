# TaskCard: P1-1 Causal Status and Feedback Diagnostics

## Task ID

AWF-USABILITY-P1-1

## Goal

Turn the existing factual node snapshot into one read-only causal explanation for a requested run,
while showing Dogfood Finding capture/outbox/flush state independently from business completion and
ACK state. The UTF-safe runtime boundary is already complete in P1-1a and is not repeated here.

## Frozen contract

- `awf node status --profile ... --run ... --explain` identifies the current run, stage and attempt,
  the first observed blocking boundary, its owner and cause, whether model invocation was observed,
  payload-blind event metadata, and one legal next action.
- Causal conclusions are derived only from existing lifecycle, RunLedger and delivery-checkpoint
  facts. Missing or unreadable evidence remains `unknown`; status never invents readiness or model
  execution.
- Feedback capture/outbox/flush facts are a separate top-level status component. Business terminal
  or ACK state never implies Feedback was sent, and pending/corrupt Feedback never rewrites business
  terminal state.
- Status stays read-only: no Agent Bus ACK/requeue/send, recovery, redispatch, checkpoint mutation,
  provider/model invocation, lifecycle action or Git mutation.
- Existing factual fields and `awf.node-status.v1` remain compatible. `--explain` adds the causal
  human rendering; JSON always exposes the same causal and Feedback facts for auditability.
- No dependency is added.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@18737dbc9de642e5dc357f3a39a1716d8a839d30`
- **Branch**: `codex/causal-status-diagnostics`
- **Completed prerequisite**: P1-1a UTF-safe Runtime Text Boundary, PR #87, merge
  `32cbaebc7bace0ad8e95a0761c81402a205834bc`.

## Scope

- Reuse the current lifecycle, ledger, delivery-checkpoint and Feedback Outbox readers.
- Add one deterministic causal projection and concise explain rendering.
- Wire `--explain` through the existing node CLI without changing the listener health exit code.
- Add three representative focused tests: lifecycle-not-runnable, denied-before-model, and business
  terminal with Feedback pending. One test also locks the no-mutation boundary.

## Out of scope

- Runtime text decoding already delivered by P1-1a; status schemas beyond additive fields; Feedback
  flush/ingest behavior; Agent Bus protocol; ACK/requeue/recovery/dispatch; provider/model changes;
  service lifecycle changes; P1-2/P1-3/P2; Phase B; Agent Host; DAG; provider registry/model router.
- Reading, operating, ACKing, requeueing, recovering, redispatching or reusing events 163, 166, 173,
  any retained business event, or any business payload.

## Verification level and budget

- **Level A/B; three focused tests.**
- Extend existing status fixtures instead of creating a new harness.
- One representative side-effect test makes mutating Bus/model/recovery/lifecycle functions fail if
  reached while the snapshot is built.
- Local Mac verification is limited to compile/static/diff checks. Pytest and Ruff run only in
  GitHub CI.

## Acceptance criteria

- [ ] Every blocked representative state exposes `owner`, `cause`, `model_invocation`, and
  `next_legal_action`.
- [ ] Event observation includes no payload or delivery hash/body.
- [ ] Business terminal plus Feedback pending remains two independent facts.
- [ ] `--explain` renders the causal chain and first blocker without changing JSON or health exit
  semantics.
- [ ] Three focused tests and the full GitHub CI matrix pass.
- [ ] Independent review approves the exact PR head before merge.

## Required output

- `docs/tasks/causal-status-and-feedback-diagnostics-implementation-report.md`
- Minimal code/tests, Lore commits, PR, green CI, exact-head independent review, fresh mergeability
  gate, merge, post-merge main/CI proof, necessary shared docs, and short-branch cleanup.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/causal-status-and-feedback-diagnostics.md",
    "docs/tasks/causal-status-and-feedback-diagnostics-implementation-report.md",
    "src/agent_workflow/status.py",
    "src/agent_workflow/node.py",
    "src/agent_workflow/cli.py",
    "tests/test_status.py",
    "tests/test_node.py",
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "HANDOFF.md",
    "docs/runtime-execution-architecture.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_status.py", "tests/test_node.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
