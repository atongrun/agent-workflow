# TaskCard: P0-4a Read-only Run Contract Compiler

## Task ID

AWF-USABILITY-P0-4A

## Goal

Add a local, read-only compiler/linter that proves one owner RunManifest, internal authority
manifest, frozen TaskCard artifact contract, role node profiles, repository, run identity, and
state-root binding agree before any remote, process, Git, or Agent Bus side effect.

## Frozen contract

- The credential-free `awf.run-manifest.v1` document remains the owner-visible source of truth.
- `awf.authority-manifest.v1` remains an internal fail-closed gate input. The CLI names the two
  classes separately and reports both expected and received format identifiers on a mix-up.
- `awf plan check` only reads local files and prints an `awf.run-contract-report.v1` report. It does
  not initialize a ledger, mutate Git, connect to Agent Bus, start a process, or dispatch an event.
- The report binds compiler provenance, the RunManifest, authority manifest, TaskCard, state root,
  repository, and exact role profile identities by canonical SHA-256 facts.
- The compiler validates run/branch identity; v1-v3 route compatibility; coder/reviewer tool,
  model, route, repository, provenance and state-root agreement; and the frozen TaskCard's
  ImplementationReport/ReviewReport allowlist contract.
- This package does not change `setup`, `run`, or `dispatch` consumption. P0-4b owns that switch.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@06e71c46118bc8b584cc94667fa6f39fc1f93b2d`
- **Branch**: `codex/run-intent-compiler`
- **Primary files**: `src/agent_workflow/manifest.py`, `src/agent_workflow/cli.py`,
  `scripts/awf_artifact_contract.py`, `scripts/awf_control_plane.py`, focused manifest/artifact/CLI
  tests, installed-wheel verification, and operator documentation.

## Scope

- Add the read-only compiler result and deterministic component bindings.
- Add a distinct `awf plan check --run-manifest ... --authority-manifest ...` CLI.
- Extend the artifact linter to validate both required report paths against one frozen allowlist.
- Preserve explicit compatibility for existing v1, v2, and v3 workflow routes.

## Out of scope

- Switching setup/run/dispatch to consume compiled output (P0-4b), workspace transition (P0-5),
  status/facade work, Agent Bus changes, Phase B, Agent Host, DAGs, provider registries, or model
  routers.
- Any weakening of fail-closed provenance, delivery hash, checkpoint, outbox, postflight, PR tuple,
  handler-success ACK, or business/Finding ACK separation.
- Any read, ACK, requeue, recovery, redispatch, reuse, or payload access for events 163, 166, 173,
  or any retained business event. Tests use only local temporary fixtures.

## Verification level and budget

- **Level B; target two new focused tests, maximum three.**
- One exact manifest-class mix-up test proves a local failure naming both schemas before any
  compiler side-effect callback can run.
- One table-driven contract test covers TaskCard/report, state-root, profile route/tool/model/repo,
  and run/branch binding mismatches; one valid matrix covers v1-v3 compatibility.
- Extend the installed-wheel unrelated-cwd verification with one compiler smoke.
- Local Mac verification is limited to static inspection, compile/AST checks, JSON parsing, and
  `git diff --check`; GitHub CI owns Pytest, Ruff, and the cross-platform installed-wheel matrix.

## Acceptance criteria

- [ ] `awf plan check` emits a deterministic `awf.run-contract-report.v1` with compiler provenance
      and SHA-256 bindings for every input class.
- [ ] Passing a RunManifest as the authority input fails locally and names
      `awf.run-manifest.v1` and `awf.authority-manifest.v1` distinctly, with zero remote/process/
      event side effects.
- [ ] TaskCard and both required report paths are checked against the frozen postflight contract.
- [ ] Run id, branch, roles, tools/models, routes, repositories, rework budget, state root, and
      profile identity drift fail closed before output is declared compatible.
- [ ] Valid v1-v3 route manifests return an explicit compatibility result.
- [ ] Existing setup/run/dispatch behavior is unchanged until P0-4b.
- [ ] Focused tests and the full GitHub CI/installed-wheel matrix pass; an independent reviewer
      approves the exact PR head before merge.

## Required output

- `docs/tasks/read-only-run-contract-compiler-implementation-report.md`
- Minimal runtime/compiler code, proportional tests, README/architecture/CHANGELOG/HANDOFF updates,
  Lore commit series, PR, green CI, exact-head independent review, merge, post-merge proof, and
  short-branch cleanup.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/read-only-run-contract-compiler.md",
    "docs/tasks/read-only-run-contract-compiler-implementation-report.md",
    "docs/runtime-execution-architecture.md",
    "HANDOFF.md",
    "README.md",
    "CHANGELOG.md",
    "src/agent_workflow/manifest.py",
    "src/agent_workflow/cli.py",
    "scripts/awf_artifact_contract.py",
    "scripts/awf_control_plane.py",
    "tests/test_manifest.py",
    "tests/test_phase0_artifact_contract.py",
    "tests/test_cli.py",
    "tests/verify_installed_wheel.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_manifest.py", "tests/test_phase0_artifact_contract.py", "tests/test_cli.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
