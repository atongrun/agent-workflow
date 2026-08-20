# TaskCard: RTS-030 Selected Python Runtime Core Boundary

## Task ID

runtime-v2-rts-030-python-core-boundary

## Goal

Create the first enforceable installed-package boundary for the selected Python Runtime v2 Core.
Define immutable `RunSpec` and renderer-facing `InvocationSpec` contracts plus narrow logical
RunStore, per-invocation journal, status-reader and provider-renderer ports under
`agent_workflow.runtime`. Lock their authority and dependency direction with focused tests.

This is a contract/package boundary card, not a production handler migration. It must identify the
first successor integration seam while remaining independently reversible by deleting only the new
package/tests/artifacts and closeout references.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@77b497931d183b0e29ea0f2b54efdb6030e90ba5`
- **Task branch**: `codex/runtime-v2-rts-030-python-core-boundary`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 3 / RTS-030
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Historical comparison fixture**: `tests/fixtures/runtime_v2_shared_slice_cases.json`, read-only

Current installed code in `src/agent_workflow/` still imports packaged operational scripts by
prepending the operations directory to `sys.path`. RTS-030 does not remove or reroute those paths.
It creates the inward Core boundary that later cards can implement and adopt one seam at a time.

## Frozen architecture boundary

### Immutable owner intent

`RunSpec` is an immutable, strict, canonical owner/compiler value. It binds at least:

- format/version, run ID and task ID;
- trusted repository identity, frozen base and task branch;
- canonical state-root binding and Frozen semantic-contract digest;
- exact coder/reviewer provider and model selections;
- bounded implement/review/rework capacities;
- exact implementation and review Artifact paths.

Construction rejects blank identifiers, control characters, non-canonical repository-relative
paths, absolute/traversal paths, malformed SHA-256 values, invalid capacities and unknown fields at
the mapping boundary. Canonical JSON bytes and SHA-256 are deterministic. The value contains no
credential, live provider/Bus/GitHub/OS observation or mutable state.

### Renderer-facing invocation

`InvocationSpec` is immutable and fully bound before a renderer sees it. It contains only the
provider-facing identity and structured local inputs needed to construct one process invocation:

- invocation/run/task identity and opaque authorization digest;
- role, provider and model;
- exact workspace, input and report paths;
- exact structured provider arguments/options that are safe to expose to the renderer.

It MUST NOT expose Workflow Stage, attempt/rework counters, RunStore/journal objects, state-root
mutation handles, Agent Bus operations, GitHub credentials or a generic plugin/config registry.
The Runtime owns Stage-to-invocation authorization before constructing this renderer surface.

`RenderedInvocation` contains an executable plus argument tuple, exact cwd, optional stdin bytes and
an explicit environment allowlist/overrides value. It cannot contain a shell command string and
must reject an empty executable, NUL/control-bearing argv, relative cwd or mutable containers.

### Logical ports

- `RunStore` is the sole logical Workflow transition writer. Its command methods accept immutable
  exact-identity command values and return immutable decisions/snapshots. It owns authorization,
  exact local outgoing intent and terminal facts; it does not invoke providers or external systems.
- `InvocationJournal` is one exact invocation's durable recovery API. It preserves separately typed
  authorization, launch intent, process observation, result and validation/effect facts. The port
  exposes no “set arbitrary phase” or guessed repair method.
- `StatusReader` has read-only snapshot methods only. It cannot inherit from or expose a RunStore,
  journal writer, provider, transport or lifecycle mutation method.
- `ProviderRenderer` is pure: `render(InvocationSpec) -> RenderedInvocation`. It receives no Runtime
  state object and performs no subprocess, filesystem, Git, Bus or network effect.

RTS-030 defines ports and values only. The selected checksummed atomic-file implementation belongs
to a successor TaskCard after these dependency/immutability tests pass.

## Dependency and packaging rules

1. `src/agent_workflow/runtime/` may import only Python standard library modules and other packaged
   `agent_workflow` modules that do not import operations scripts.
2. It MUST NOT import `scripts`, `awf_*` bare modules, `agent_workflow.operations`, `cli`, `facade`,
   `node`, `status`, provider CLIs or third-party packages.
3. It MUST NOT mutate `sys.path`, discover repository roots, read environment credentials, spawn a
   process or open a network connection at import time or through the contract/port APIs.
4. Existing `scripts/`, CLI, node, status, provider adapters and state representations are read-only
   and remain the production/default path.
5. No new dependency, generic framework, registry, ORM, async runtime, scheduler, daemon, SQLite,
   native launcher, compatibility facade or dual Runtime dispatcher.
6. Production implementation budget: at most 700 nonblank/noncomment lines across the new package;
   focused test budget: at most 900. Crossing either budget requires a deterministic stop and a
   narrower follow-up design, not hidden scope expansion.

## Frozen writable scope

- `src/agent_workflow/runtime/__init__.py`
- `src/agent_workflow/runtime/contracts.py`
- `src/agent_workflow/runtime/ports.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_core_contracts.py`
- `tests/verify_installed_wheel.py` (only the isolated import proof for `agent_workflow.runtime`)
- `.awf/artifacts/impl-report-runtime-v2-rts-030-python-core-boundary.md`
- `.awf/artifacts/review-report-runtime-v2-rts-030-python-core-boundary.md`

After implementation, focused/full CI and independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-030-python-core-boundary-implementation-report.md` and update only the
Phase 3 gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Modification of existing production `src/agent_workflow/*.py`, `scripts/`, schemas, CLI, facade,
  node/lifecycle, status, provider adapters, package metadata, CI workflows or state formats. The
  sole exception is the allowed installed-wheel import assertion in `tests/verify_installed_wheel.py`.
- A concrete atomic-file RunStore/journal implementation, legacy adapter, handler integration,
  provider invocation, workspace/Git implementation, Agent Bus envelope or cross-machine behavior.
- Editing the Frozen contract, ADR-0006, comparison experiments/fixtures/evidence or Rust paths.
- Checkpoint/outbox/inbox deletion, read migration, dual write, silent fallback, state rollback,
  default switch, production migration, native launcher, release or destructive cleanup.
- Live/retained event, payload, delivery, queue, listener, service, state root, provider, credential,
  ACK, remote Git or GitHub business operation.

## Acceptance criteria

- [ ] Task ID equals the branch leaf and all changed paths remain inside the frozen writable scope.
- [ ] `agent_workflow.runtime` is importable from the source tree and installed wheel without bare
      script-path injection.
- [ ] `RunSpec` is frozen, strict, canonical, checksum-addressable and rejects every named malformed
      identity/path/capacity case before any state or provider effect.
- [ ] `InvocationSpec` is frozen and fully bound but exposes no Workflow Stage, attempt/rework
      counter, state writer, transport operation or credential-bearing registry.
- [ ] `RenderedInvocation` uses structured executable/argv/cwd/stdin/environment values and rejects
      command strings, mutable containers and control-bearing tokens.
- [ ] RunStore, InvocationJournal, StatusReader and ProviderRenderer are narrow typed protocols with
      the selected ownership direction and no arbitrary phase/mutation escape hatch.
- [ ] Static dependency tests fail if the new package imports scripts/bare `awf_*`, mutates
      `sys.path`, imports third-party/runtime facade modules or exposes forbidden port methods.
- [ ] Contract tests prove immutable/hash-stable values, strict mapping keys, path normalization,
      renderer surface separation and immutable transition/journal command values.
- [ ] No provider, subprocess, Git, Bus, network, production state or external mutation occurs in
      tests; all inputs are pure/disposable values.
- [ ] New production package stays at or below 700 nonblank/noncomment lines, focused tests at or
      below 900, with no new dependency.
- [ ] Focused tests, full pytest/Ruff, installed-wheel import and ordinary cross-platform CI pass on
      the TaskCard candidate head.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; L1 repairs receive focused validation,
      while any L3 authority/interface repair receives focused re-review.
- [ ] Closeout names exactly one successor integration seam and does not claim Phase 3, distribution,
      default, migration or release completion.

## Verification

- Focused local checks may compile the new Python modules, parse the TaskCard/artifacts, inspect AST
  imports and run `git diff --check`. Per repository Mac boundary, pytest/Ruff remain CI-owned.
- Focused CI runs the two new test modules and installed-wheel import before the candidate Gate
  Review; one final ordinary cross-platform CI runs on the exact publication head.
- Static tests parse the new package AST/source rather than relying only on a successful import.
- Independent Review checks immutability, strict construction, canonical hashing, interface escape
  hatches, dependency direction, Frozen semantic preservation, LOC/dependency budget and scope.

## Required output

- one installed `agent_workflow.runtime` contract/port package;
- two focused boundary/contract test modules;
- compiled ImplementationReport and ReviewReport;
- owner closeout naming the first production integration seam.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/ports.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_core_contracts.py",
    "tests/verify_installed_wheel.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-030-python-core-boundary.md",
    ".awf/artifacts/review-report-runtime-v2-rts-030-python-core-boundary.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "tests/test_runtime_core_boundary.py", "tests/test_runtime_core_contracts.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_core_boundary.py", "tests/test_runtime_core_contracts.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credentials, tokens, private URLs, business payloads, retained-event data, or personal environment facts may enter Runtime contracts, tests or reports.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-030-python-core-boundary.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-030-python-core-boundary.md"
}
-->
