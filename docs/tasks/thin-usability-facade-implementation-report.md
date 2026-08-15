# P1-2 Thin Usability Facade — Implementation Report

## Outcome

The beginner journey now composes the existing durable profile, owner RunManifest, compiled
run-contract, truthful lifecycle and causal status contracts. It does not introduce a facade
schema, database, scheduler, recovery path, provider registry, or Agent Bus behavior.

## Changed files

- `src/agent_workflow/facade.py` owns exact default-artifact discovery, credential-free profile
  generation, lifecycle composition, and the queue-empty drain gate.
- `src/agent_workflow/cli.py` adds `init`/`enroll`, top-level lifecycle/diagnostic commands, `run
  check`, bare-run card discovery, and the compatibility router for legacy `status --run`.
- `tests/test_facade.py` contains the two budgeted tests: one seven-command synthetic journey and
  one representative all-profiles-before-mutation start/drain boundary.
- `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `HANDOFF.md`, and
  `docs/runtime-execution-architecture.md` record the supported surface and trust boundary.

## Simplifications

- One platform state root replaces a beginner-supplied `--state-root` choice.
- Deterministic machine/project/role profile names replace repeated profile arguments.
- Default `.awf/run-manifest.json` and `.awf/run-contract.json` discovery removes normal
  authority-manifest and compiled-contract path choices.
- `run check` reuses the compiler and bare `run` reuses the existing initializer; no execution
  algorithm was copied into the facade.
- `init` and `enroll` share one handler. Existing advanced `setup`, `plan`, `node`, explicit-card
  `run`, and `status --run` call shapes remain supported.

## Program metrics

- Supported journey: seven operator commands (`init`, `doctor`, `start`, `run check`, `run`,
  `status`, `stop`/`drain`).
- Explicit onboarding choices recorded by the synthetic proof: machine, project, coder runtime,
  reviewer runtime, and their existing model/provenance selections.
- User-authored facade configuration objects: zero. Generated objects are two existing node
  profiles plus the existing owner RunManifest and compiled report.
- Failure gates: profile/schema/compiler drift, unknown/stale managed installation, and
  unknown/non-empty queues all fail before lifecycle mutation at their respective composite gate.
- Elapsed time: deliberately unmeasured here; the separately authorized fresh-machine milestone
  owns that measurement.

## Verification

- Local Mac: Python `compileall` and `git diff --check`; no pytest or Ruff was run locally.
- GitHub Actions run `31862772976`: all six required jobs passed on the published PR head,
  including Linux/macOS/Windows installed-wheel checks, the Linux test/lint suite, the Windows
  test suite, and the macOS runtime check.
- Independent exact-head review remains the final pre-merge gate and will be attached to PR #90.

## Remaining risks

- External provider authentication, `dispatch.env`, Git credentials, role checkout preparation and
  native-manager availability remain explicit prerequisites; the facade does not provision them.
- Fresh Mac/VPS/Windows no-model timing and live lifecycle behavior remain the final acceptance
  milestone, not a claim of this synthetic package.
- P1-3 structured handler invocation and P2 packaging feasibility remain separate work packages.
