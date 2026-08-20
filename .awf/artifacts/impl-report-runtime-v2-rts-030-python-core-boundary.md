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
  argv, cwd, stdin and environment values. Its canonical digest covers those fields while retaining
  only stdin digest and length, so journal launch intent never depends on ad hoc object hashing. It
  has no provider execution or Runtime mutation method.
- Static AST/source checks forbid operations scripts, bare `awf_*`, `sys.path`, subprocess/network
  modules, third-party dependencies and concrete Store/journal/executor modules in this slice.

## Scope and budgets

Only the RTS-030 frozen writable paths changed. Existing production CLI, handlers, scripts,
providers, lifecycle, status and legacy representations remain untouched and continue as the sole
default Runtime. The installed-wheel check adds only an import and package-location assertion.

The package contains 679 nonblank/noncomment lines against the 700-line limit. The two focused test
modules contain 450 against the 900-line limit. No dependency was added.

## Verification state

Local repository-policy-safe checks pass:

- Python AST parsing for all new package and focused-test files;
- direct pure-value contract smoke checks;
- static dependency-boundary scan;
- exact writable-path and generated-file audit;
- line-length and LOC budget checks;
- `git diff --check`.

Candidate CI run `32335336859` passed full Linux/Windows tests, macOS runtime checks and installed-
wheel checks on all three platforms after one L1 import-order repair. Binary Feasibility run
`32335336776` also passed all jobs. The single independent Gate Reviewer then found one L3 launch-
identity gap: `LaunchIntent` required a rendered-invocation digest without canonical bytes. Repair
`c9e2c5f` added exact canonical hashing and focused field-drift tests. Repair CI `32336141952`
passed Ruff, complete Linux tests/distribution validation, macOS runtime and all installed-wheel
jobs before closeout. The same Reviewer's focused re-review returned `PASS` with no new L3 defect.

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
    "Candidate ordinary CI 32335336859 PASS",
    "Candidate Binary Feasibility 32335336776 PASS",
    "Independent Gate Review PASS after c9e2c5f launch-identity repair and focused re-review"
  ],
  "source_revision": "c9e2c5f1731b8690318420df1b87c35602be5611"
}
-->
