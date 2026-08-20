# RTS-030 Python Runtime Core Boundary Implementation Report

## Result

The selected Python Runtime v2 now has a reversible installed-package boundary at
`agent_workflow.runtime`. The slice defines immutable, strict and checksum-addressable `RunSpec`
and `InvocationSpec` values, structured `RenderedInvocation` output, and narrow typed ports for the
logical RunStore writer, one per-invocation journal, read-only status and pure provider rendering.

`RunSpec` binds TaskCard identity and digest, repository/base/branch/state-root/semantic-contract
identity, exact role/provider/model selections, routes, attempt/rework capacities and Artifact
paths. `InvocationSpec` is constructed only after authorization and exposes no Workflow Stage,
attempt, state writer, transport or credential registry to a renderer.

## Authority and effect boundaries

- `RunStore` alone exposes Workflow authorization, outgoing-intent and terminal command methods.
- Journal facts keep authorization, launch intent, process observation, provider result and
  validation/trusted effect separately typed rather than collapsing them into one phase enum.
- `StatusReader` exposes only a read-only snapshot with owner, cause, first blocker and one next
  action.
- `ProviderRenderer` accepts one fully bound `InvocationSpec` and returns structured executable,
  argv, cwd, stdin and environment values. It has no provider execution or Runtime mutation method.
- Static AST/source checks forbid operations scripts, bare `awf_*`, `sys.path`, subprocess/network
  modules, third-party dependencies and concrete Store/journal/executor modules in this slice.

## Scope and budgets

Only the RTS-030 frozen writable paths changed. Existing production CLI, handlers, scripts,
providers, lifecycle, status and legacy representations remain untouched and continue as the sole
default Runtime. The installed-wheel check adds only an import and package-location assertion.

The package contains 659 nonblank/noncomment lines against the 700-line limit. The two focused test
modules contain 428 against the 900-line limit. No dependency was added.

## Verification state

Local repository-policy-safe checks pass:

- Python AST parsing for all new package and focused-test files;
- direct pure-value contract smoke checks;
- static dependency-boundary scan;
- exact writable-path and generated-file audit;
- line-length and LOC budget checks;
- `git diff --check`.

Per repository policy, pytest, Ruff and installed-wheel execution are CI-owned. Their results and
the single independent TaskCard Gate Review will be recorded on the candidate head before closeout.

## Explicit non-claims

This card does not implement the atomic-file Store or journal, migrate a production handler, invoke
a provider, send or acknowledge an Agent Bus event, mutate Git/GitHub/OS state, delete a legacy
representation, implement a native launcher, change a default, migrate production state or release
Runtime v2.

<!-- awf-implementation-report
{
  "summary": "Create the reversible installed Python Runtime v2 contract and effect-port boundary without changing the production default.",
  "changed_files": [
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/ports.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_core_contracts.py",
    "tests/verify_installed_wheel.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-030-python-core-boundary.md"
  ],
  "commands": [
    "Python AST and direct contract smoke checks",
    "static dependency and writable-path audit",
    "LOC and line-length checks",
    "git diff --check"
  ],
  "tests": [
    "Local static and pure-value checks PASS",
    "Candidate CI and independent Gate Review pending"
  ],
  "source_revision": "3fa97188a41fd1f989bedf2e288fe31bd9251ee8"
}
-->
