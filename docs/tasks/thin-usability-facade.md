# TaskCard: P1-2 Thin Usability Facade

## Task ID

AWF-USABILITY-P1-2

## Goal

Expose one beginner-oriented local journey over the already proven profile, lifecycle, compiled
run-contract and causal-status surfaces. The facade removes routine manifest-class, state-root and
native service-definition choices without becoming a scheduler or a second control plane.

## Frozen contract

- `.awf/run-manifest.json` and `.awf/run-contract.json` remain the only project run configuration;
  no facade database or schema is introduced.
- `awf init` (with `awf enroll` as the same compatibility spelling) accepts machine, project and
  runtime choices, generates credential-free durable coder/reviewer profiles, validates them with
  the existing profile contract, and compiles the existing owner RunManifest and run contract.
- `awf doctor --explain`, `awf start`, `awf run check`, bare `awf run`, `awf status --explain`,
  `awf drain` and `awf stop` discover exact profiles and the canonical state root from the compiled
  project artifacts. Existing low-level commands remain available unchanged.
- Facade start may compose the existing managed `install` then `start` actions only when lifecycle
  facts explicitly report `installed=false`; unknown or stale installation evidence fails closed.
- Drain is local and fail-closed: it stops exact configured listeners only when every read-only
  queue observation is `observed` with zero pending deliveries. It never ACKs, requeues or recovers.
- Init/check/doctor/status stay payload-blind and read-only apart from writing the explicitly
  requested generated configuration during init. They never dispatch, invoke a model, recover a
  run, mutate a checkpoint, flush Feedback or change lifecycle state.
- No dependency is added.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@e2224ed2888d22ae6e7ae28d37a62df6c78e68a2`
- **Branch**: `codex/thin-usability-facade`
- **Completed prerequisite**: P1-1 causal status and diagnostics, PR #89.

## Scope

- Add one small facade module that generates existing artifacts and composes existing APIs.
- Add top-level beginner commands and default discovery while preserving all advanced call shapes.
- Record config provenance and the number of commands/operator choices for the later benchmark.
- Add one synthetic journey test and one representative payload-blind/fail-closed boundary test.

## Out of scope

- New profile/run/facade schemas; Agent Bus protocol or handler changes; dispatch/recovery/model
  scheduling; automatic ACK/requeue; credential authoring; live business events; Phase B; Agent
  Host; DAG; provider registry/model router; P1-3 structured handler work; P2 packaging.
- Reading, operating, ACKing, requeueing, recovering, redispatching or reusing events 163, 166, 173,
  any retained business event, or any business payload.

## Verification level and budget

- **Level B; two focused tests.**
- One synthetic local journey covers init -> doctor -> start -> run check -> run -> status -> stop
  using disposable configuration/state and existing compiler/lifecycle/status seams.
- One boundary test proves read-only facade commands cannot reach transport/model/recovery/Feedback
  or lifecycle mutation and that start/drain fail closed on unknown or pending evidence.
- Local Mac verification is limited to compile/static/diff checks. Pytest and Ruff run only in
  GitHub CI.

## Acceptance criteria

- [x] The supported journey requires no authority-manifest argument, state-root argument or native
  service-definition editing.
- [x] Generated profiles, RunManifest and run contract are inspectable and identify their source.
- [x] Existing setup/plan/node/status/resume/dispatch commands remain compatible.
- [x] Thin journey records seven operator commands and the explicit machine/runtime/project choices;
  elapsed time remains a final fresh-machine benchmark measurement.
- [x] Read-only commands are payload-blind and cannot ACK, requeue, dispatch, recover or invoke a
  model; start/drain preserve fail-closed lifecycle and queue gates.
- [x] Two focused tests and the full GitHub CI matrix pass.
- [ ] Independent review approves the exact PR head before merge.

## Required output

- `docs/tasks/thin-usability-facade-implementation-report.md`
- Minimal code/tests, Lore commits, PR, green CI, exact-head independent review, fresh mergeability
  gate, merge, post-merge main/CI proof, necessary shared docs, and short-branch cleanup.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/thin-usability-facade.md",
    "docs/tasks/thin-usability-facade-implementation-report.md",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/cli.py",
    "tests/test_facade.py",
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "HANDOFF.md",
    "docs/runtime-execution-architecture.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_facade.py", "tests/test_cli.py", "tests/test_node.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
