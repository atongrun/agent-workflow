# Agent Bus Brownfield Dogfood

This example is the first real acceptance scenario for the Development Workflow MVP. It intentionally uses manual model handoff so the workflow method can be validated before remote automation.

> The run commands below define the target MVP interface. The current Phase 0 CLI does not implement `init`, `status`, `next`, or `submit` yet.

## Goal

Continue the existing Agent Bus project with one bounded milestone: add the first non-mutating `agent-bus doctor --json` diagnostic slice described in [goal.md](goal.md). Start from the verified capabilities in [baseline.md](baseline.md); do not redesign Agent Bus.

## Start the Run

From the Agent Workflow checkout:

```bash
awf init \
  --project ../agent-bus \
  --goal examples/agent-bus-dogfood/goal.md \
  --mode dual \
  --executor manual \
  --reviewer manual \
  --decider manual

awf status --project ../agent-bus
awf next --project ../agent-bus
```

Expected first output:

```text
stage: architecture-primary
input: baseline.md, goal.md
expected: ArchitectureRecord draft
packet: .awf/runs/<run-id>/inbox/next-stage.md
```

Give the packet to the primary architect, save its response, and submit it:

```bash
awf submit --project ../agent-bus --artifact /tmp/architecture-primary.md
awf next --project ../agent-bus
```

The next packet goes to the challenger. The challenger may raise only issues that materially affect this diagnostic milestone. The primary then freezes, freezes with known risk, revises within the three-round limit, or asks the user.

## Plan and Task

After architecture freezes, continue the same loop:

```bash
awf next --project ../agent-bus
awf submit --project ../agent-bus --artifact /tmp/phase-plan.md
awf next --project ../agent-bus
```

The run must now contain:

```text
artifacts/architecture-record.md
artifacts/phase-plan.md
artifacts/task-cards/ABUS-DIAG-001.md
```

The TaskCard is limited to `client/cli.py`, focused CLI tests, and CLI documentation. It forbids server/schema changes, new dependencies, event mutation, and unrelated cleanup.

## Execute, Review, and Decide

Give the TaskCard packet to the selected executor. The executor runs the focused tests and returns an `ImplementationReport`. Import it, then repeat for test and review artifacts:

```bash
awf submit --project ../agent-bus --artifact /tmp/implementation-report.md
awf next --project ../agent-bus
awf submit --project ../agent-bus --artifact /tmp/test-report.md
awf next --project ../agent-bus
awf submit --project ../agent-bus --artifact /tmp/review-report.md
```

Compile/test failures or explicit TaskCard violations may return to execution. Architecture disagreements and optional improvements cannot. They are compressed into the DecisionPacket for the selected decider.

```bash
awf next --project ../agent-bus
awf submit --project ../agent-bus --artifact /tmp/decision.md
awf status --project ../agent-bus
```

Expected final status:

```text
task: ABUS-DIAG-001 completed
architecture: frozen | frozen_with_known_risk
phase: cli-diagnostics
next: next-task | phase-advance
```

Calling `awf next` continues to the next TaskCard. If phase exit criteria are satisfied, it emits a phase-advance packet and generates detail only for the next phase.

## Acceptance Evidence

- The complete baseline-to-decision artifact chain exists.
- Architecture used no more than three rounds.
- Agent Bus diagnostic tests deterministically cover missing configuration, network failure, unhealthy service, unauthorized token, and success.
- Non-blocking suggestions did not consume rework or block completion.
- Manual handoffs, rework count, packet size, and targeted-context requests are recorded.
- No generic Agent Bus adapter or complex runtime was needed to complete the run.
