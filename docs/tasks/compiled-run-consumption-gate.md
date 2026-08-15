# TaskCard: P0-4b Compiled Run Consumption Gate

## Task ID

AWF-USABILITY-P0-4B

## Goal

Make normal `awf setup` persist one complete credential-free owner intent and its deterministic
compiled run contract, then require `awf run` to recompile and match that exact contract before
RunLedger initialization or any later operational action.

## Frozen contract

- The owner RunManifest remains the visible source of truth and now records the canonical
  state-root plus exact coder/reviewer profile references.
- `awf setup` takes explicit, class-specific `--run-manifest`, `--state-root`, and repeated
  `--profile role=value` inputs; it validates the complete P0-4a graph before atomically writing the
  owner manifest and `.awf/run-contract.json`.
- The compiled file is owner-only, credential-free, deterministic, and carries
  `awf.run-contract-report.v1` plus its exact `contract_sha256`.
- `awf run` accepts class-specific owner/compiled paths, loads the owner intent, recompiles the
  current authority/TaskCard/profile/state-root graph, requires exact report equality, and only then
  resolves Git HEAD and initializes the RunLedger.
- The context packet binds the compiled contract SHA. An existing ledger cannot be reopened with a
  different compiled contract.
- Existing v1 RunManifests without compiled inputs fail closed with a migration instruction; no
  silent inference from environment, default state, or retained transport data is allowed.
- Native dispatch remains unchanged in P0-4b; its migration belongs to a later explicitly scoped
  compatibility/facade package.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@bd582e1a9c6c3eafa5e55b094356e503042970ea`
- **Branch**: `codex/compiled-run-gate`
- **Prerequisite**: P0-4a PR #85, exact-head PASS and post-merge main CI `31830185877` green.
- **Primary files**: `src/agent_workflow/manifest.py`, `src/agent_workflow/cli.py`,
  `scripts/awf_control_plane.py`, focused manifest/CLI/control-plane tests, installed-wheel smoke,
  and operator documentation.

## Scope

- Persist state-root/profile references in the existing credential-free RunManifest contract.
- Add owner-only atomic compiled-report load/write validation.
- Compile during setup and recompile/compare during run before ledger mutation.
- Bind `run_contract_sha256` into the context packet and ledger immutable identity.
- Replace normal setup/run generic manifest flags with class-specific names and explicit migration
  errors; leave the lower-level dispatch compatibility surface unchanged.

## Out of scope

- Dispatch transport changes, implement-to-rework workspace transition, causal status/facade work,
  Agent Bus changes, Phase B, Agent Host, DAGs, provider registries, or model routers.
- Any weakening of provenance, delivery hash, checkpoint, outbox, postflight, PR tuple,
  handler-success ACK, or business/Finding ACK separation.
- Any read, ACK, requeue, recovery, redispatch, reuse, or payload access for events 163, 166, 173,
  or any retained business event. Tests use only temporary local fixtures.

## Verification level and budget

- **Level B; target two new focused tests, maximum three.**
- One setup/run round-trip proves the exact compiled SHA reaches the context packet before ledger
  initialization.
- One table-driven fail-closed test mutates owner manifest, TaskCard allowlist, profile identity,
  authority binding, state-root, or compiled report and proves ledger/Git/Bus/process callbacks stay
  at zero.
- One compatibility test proves an old manifest or generic flag gets a precise migration error.
- Extend the installed-wheel unrelated-cwd smoke to exercise setup -> compiled artifact -> run gate
  without any Bus or model invocation.
- Local Mac verification remains compile/static/diff only; GitHub CI owns Pytest, Ruff, and
  cross-platform installed-wheel execution.

## Acceptance criteria

- [ ] Setup writes a complete owner RunManifest and matching owner-only compiled report only after
      the P0-4a graph validates.
- [ ] Run recompiles current local inputs and requires exact report/contract SHA equality before
      Git HEAD lookup and RunLedger initialization.
- [ ] Context packet and ledger immutable identity include the exact compiled contract SHA.
- [ ] RunManifest/authority/compiled classes have distinct flag names and errors; no generic normal
      setup/run manifest input remains.
- [ ] Drift in any bound input fails locally with zero ledger/Git/Bus/process/event side effects.
- [ ] Existing uncompiled owner manifests receive an explicit setup migration instruction.
- [ ] Two or three focused tests plus the full CI/installed-wheel matrix pass; an independent
      reviewer approves the exact PR head before merge.

## Required output

- `docs/tasks/compiled-run-consumption-gate-implementation-report.md`
- Minimal code/docs/tests, Lore commit series, PR, green CI, exact-head independent review, fresh
  mergeability gate, merge, post-merge main/CI proof, and short-branch cleanup.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/compiled-run-consumption-gate.md",
    "docs/tasks/compiled-run-consumption-gate-implementation-report.md",
    "docs/runtime-execution-architecture.md",
    "HANDOFF.md",
    "README.md",
    "CHANGELOG.md",
    "src/agent_workflow/manifest.py",
    "src/agent_workflow/cli.py",
    "scripts/awf_control_plane.py",
    "tests/test_manifest.py",
    "tests/test_cli.py",
    "tests/test_control_plane.py",
    "tests/verify_installed_wheel.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_manifest.py", "tests/test_cli.py", "tests/test_control_plane.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
