# RTS-032 Production Provider Renderer Boundary Implementation Report

## Result

The selected Python Runtime package now owns closed, pure renderers for the evidenced OpenCode
coder/reviewer, Codex reviewer and Pi reviewer command surfaces. Each renderer accepts one frozen,
fully bound `InvocationSpec` and returns one canonical `RenderedInvocation`; production
`awf_role.py` materializes only declared file bytes and passes the exact rendered executable, argv,
cwd, environment and stdin to the existing controlled spawn boundary.

The current RunLedger/checkpoint/outbox/inbox implementation remains the sole production authority.
RTS-032 neither reads nor writes the RTS-031 Store, adds a journal, changes replay policy or changes
Workflow/Agent Bus/ACK ordering.

## Bound identity and parity

- `InvocationSpec` now binds executable, bounded multiline provider input and the exact
  credential-stripped environment in addition to the existing invocation/run/task authority,
  role/provider/model, workspace, input/report paths and closed provider options.
- `RenderedInvocation` identity covers every structured argv token, cwd, environment, bounded stdin
  and each declared file input by exact path, byte length and SHA-256.
- OpenCode and Codex same-fixture outputs match the retained pure adapter oracles exactly.
- Pi preserves every flag, model token, message and context byte. Its generated context path is the
  one frozen exception: it moves from the event state directory to ignored
  `.awf/pi-review-context.md` inside the isolated model workspace so `InvocationSpec` can enforce
  containment. Existing conflicting bytes fail before provider spawn.
- Empty rendered environments are rejected before spawn, preventing the generic process helper's
  inherited-environment fallback from weakening the bound child environment.
- Existing ambiguous and completed recovery fixtures now also assert the installed renderer remains
  unreachable, in addition to the existing no-provider/no-send assertions.

## Changed files

- `docs/tasks/runtime-v2-rts-032-provider-renderers.md`
- `src/agent_workflow/runtime/contracts.py`
- `src/agent_workflow/runtime/renderers.py`
- `src/agent_workflow/runtime/__init__.py`
- `scripts/awf_role.py`
- `tests/test_runtime_core_contracts.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_provider_renderers.py`
- `tests/test_runtime_command_boundary.py`
- `tests/test_awf_role.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-032-provider-renderers.md`

## Scope and budgets

- Renderer module: 119/320 nonblank/noncomment lines.
- Focused renderer tests: 268/750 nonblank/noncomment lines.
- Production `scripts/awf_role.py`: net +161/180 nonblank/noncomment lines against `origin/main`.
- Dependencies: no addition; installed Runtime remains standard-library only.
- Dispatch: one explicit provider/role branch, no discovery, registry, plugin or provider framework.
- Writable-path audit: only frozen TaskCard paths changed; no generated artifact remains.

## Local verification

Repository-policy-safe local validation passed:

- AST parse for all changed Python modules and tests;
- direct same-fixture OpenCode/Codex/Pi argv/stdin/context parity smoke;
- direct production wrapper smoke across all four supported role/provider surfaces;
- relative Codex report-token, Windows environment-name, multiline input and canonical identity
  smoke;
- static no-operations-import/no-old-adapter/no-registry/no-process-effect scans;
- exact writable-path, dependency and LOC audits;
- `git diff --check`.

Per repository policy, local pytest, Ruff and Rust were not run on this Mac. Independent TaskCard
Gate Review returned `PASS` with zero findings on semantic candidate `9d2cb47`. Exact-head ordinary
CI `32345260471` and Binary Feasibility `32345260487` then passed at `1028eae`, including full Linux
and Windows suites, Ruff, macOS runtime, installed-wheel jobs, all five native cells and both
aggregates. The only post-review repair was the L1 test-stub compatibility commit `1028eae`, which
accepted the already-reviewed `binding=` keyword in two monkeypatched fakes; it changed no Runtime
behavior or semantic evidence.

## Explicit non-claims

This candidate does not adopt or dual-write the RTS-031 Store, alter checkpoint/outbox/inbox or
RunEvidence formats, change provider ambiguity/replay, modify Artifact/Git/PR/CI/Agent Bus/ACK
semantics, add a provider, implement the launcher, switch a default, migrate retained/production
state, release or authorize destructive cleanup.

<!-- awf-implementation-report
{
  "summary": "Move evidenced provider command rendering behind closed installed Runtime v2 renderers while retaining the existing production authority and recovery path.",
  "changed_files": [
    "docs/tasks/runtime-v2-rts-032-provider-renderers.md",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/renderers.py",
    "src/agent_workflow/runtime/__init__.py",
    "scripts/awf_role.py",
    "tests/test_runtime_core_contracts.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_provider_renderers.py",
    "tests/test_runtime_command_boundary.py",
    "tests/test_awf_role.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-032-provider-renderers.md"
  ],
  "commands": [
    "Python AST and direct renderer parity/role-wrapper smoke checks",
    "static dependency, purity, writable-path and generated-file audit",
    "LOC and line-length checks",
    "git diff --check"
  ],
  "tests": [
    "Local policy-safe static and direct smoke validation PASS",
    "Independent TaskCard Gate Review PASS with zero findings at semantic candidate 9d2cb47",
    "Exact-head ordinary CI 32345260471 PASS at 1028eae",
    "Exact-head Binary Feasibility 32345260487 PASS at 1028eae"
  ],
  "source_revision": "1028eae5eecde2b5427ab15e58e32d834201ba39"
}
-->
