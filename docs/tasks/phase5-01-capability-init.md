# TaskCard: Phase 5-01 Capability-First Machine Init

## Task ID

phase5-01-capability-init

## Goal

Deliver one capability-first `awf init` vertical slice that configures the current machine with any
selected subset of the product roles `architect`, `coder`, and `reviewer`; binds each role to one
actually supported agent tool/model; gives every selected role an exact profile and deterministic
isolated local checkout; adds a real read-only Pi Architect renderer plus trusted TaskCard stdout
validation/persistence; verifies the structured Agent Bus argv capability; and keeps Dogfood Finding
off unless a maintainer explicitly opts in.

This is Phase 5-01 L2 product/interface work. It does not execute a TaskCard or adopt Runtime v2 as
the production run path.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Integrated base**: `main@6ce518273cc21cabdf9821ab01958e9f7f7a01ac`, the merge of PR #120
- **Task branch**: `codex/phase5-01-capability-init`
- **Phase 4B result**: RTS-046/RTS-048 and Phase 4B are closed; failed identities remain evidence
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Product boundary**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Current gaps**:
  - `awf init` requires a TaskCard and exactly coder/reviewer;
  - the facade assigns both roles the same repository path while live listener ownership rejects it;
  - `InvocationSpec` has no architect role and Pi has only a reviewer renderer;
  - architect node profiles require `tool=none`;
  - provider prompts and status expose Finding without an explicit opt-in;
  - node doctor validates Bus health but not `agent-bus.listen.on-argv.v1` capability.

## Product boundary

### Machine and role bindings

- One current machine configuration points to zero or more exact role profiles; it is local,
  credential-free configuration, not Workflow authority, a registry, or topology discovery.
- Normal onboarding exposes only Architect, Coder, and Reviewer.
- Each selected role owns a distinct deterministic profile and local checkout path.
- One resolved executable installation may serve several profiles. Same tool/model for Coder and
  Reviewer is legal and produces only an informational warning.
- Existing listener path-conflict and exact lifecycle gates remain unchanged.

### Static supported capability matrix

The onboarding matrix must reflect renderers that can actually construct an invocation:

| Product role | Supported provider in this card |
|---|---|
| Architect | Pi |
| Coder | OpenCode |
| Reviewer | OpenCode, Pi, Codex |

Legacy lower-level profiles and commands remain available. `architect + none` remains valid for the
existing deterministic terminal consumer but is not advertised as an agent-tool binding.

### Pi Architect

- Extend the existing closed renderer dispatch narrowly for `role=architect, provider=pi`.
- Use Pi text/no-session/no-approve mode with only read-only repository tools.
- Bind trusted context as an exact input file and require complete TaskCard Markdown on stdout.
- Provide a trusted helper that validates bounded UTF-8, Task ID/branch/postflight structure,
  report-path bindings, secret shapes, and an exact repository-contained destination before a
  create-only durable write.
- Do not give the Pi process Git credentials, authenticated remotes, shell interpretation, or direct
  TaskCard write authority.
- This is a preparatory, trusted planning-output boundary only. It must not call or extend
  `LocalRuntimeApplication`, `RunSpec`, `RunStore`, invocation journals, transport envelopes, ACK
  handling, listener lifecycle, or Workflow transitions. The helper accepts caller-supplied trusted
  context, repository root, and one exact destination; validates all untrusted stdout before any
  write; uses create-only durable persistence; and returns a non-authorizing Artifact fact. The
  resulting TaskCard becomes executable only after the existing owner commit/TaskCard gate and the
  separately scoped Phase 5-02 `awf run <TaskCard>` path.

### Finding

- Add `finding_enabled: boolean` to the node-profile schema; omission is `false`.
- When off, provider prompts contain no Dogfood Finding instructions, capture is not attempted, and
  normal status omits Feedback.
- Existing `awf feedback ...` and reporter functionality remain callable for explicit maintainer
  profiles. No Phase B behavior is added.
- Phase 5-01 must not add Finding state to `RunSpec`, `InvocationSpec`,
  `LocalRuntimeApplication`, RunStore, journals, transport, or Workflow authority. Normal Runtime v2
  renderers default to no Finding instructions. The explicit profile boolean applies only to the
  existing profile-driven Phase A listener/adapter prompt capture and normal status; `awf feedback`
  remains independently callable. Binding Finding into a future fresh-run Runtime invocation is
  deferred to a separately scoped Phase 5-02 decision.

### Agent Bus

- Resolve the configured client and perform a local no-event `listen --help` capability probe for
  `--on-argv` before Bus health or listener work.
- Record credential-free executable/probe provenance in readiness output.
- Do not authorize compatibility from version text alone.
- Do not install, release, deploy, upgrade, or supervise Agent Bus.

## User-visible behavior

- `awf init` without `--card` performs detect-first machine onboarding.
- It prints detected dependencies/tools and a deterministic recommended role configuration.
- On a TTY, Enter accepts the recommendation and Customize allows enabling any role subset and
  choosing among installed supported tools/models.
- Non-interactive flags can express the three required acceptance scenarios.
- Existing TaskCard-bound onboarding remains available through `awf enroll` and the legacy
  `awf init --card ...` compatibility path.
- `awf doctor`, `status`, `start`, `stop`, `drain`, and a top-level `logs` can discover the new
  machine config while retaining legacy compiled-run discovery.

## Acceptance criteria

- [ ] Task ID equals branch leaf; every changed path is inside the frozen implementation/closeout
      scope below.
- [ ] Unsupported role/provider selections deny before machine config, profile, or workspace
      mutation with a concrete remediation.
- [ ] Dependency discovery verifies Git/GitHub, configured Agent Bus executable and
      `--on-argv`, and installed provider executables without invoking a model or sending an event.
- [ ] Deterministic defaults prefer Pi Architect and OpenCode Coder/Reviewer where available; the
      interactive flow can accept or override role/tool/model choices.
- [ ] Windows-like Coder+Reviewer OpenCode/same-model init succeeds, emits one non-blocking
      independence warning, reuses one executable, and creates distinct identities/profiles/repos.
- [ ] Mac-like Architect-only Pi init succeeds without Coder/Reviewer and the profile passes local
      provider/lifecycle validation.
- [ ] Architect Pi + Coder OpenCode + Reviewer OpenCode coexist with three distinct role workspaces;
      no Host, scheduler, worker pool, registry, discovery service, or plugin framework is added.
- [ ] Existing live listener path-conflict rejection is unchanged.
- [ ] Pi Architect is accepted by `InvocationSpec`, rendered through the closed provider dispatch
      with read-only tools, and its stdout can be validated/persisted only by the trusted helper.
- [ ] The Pi Architect helper denies a missing/nonexistent destination parent, symlink/escape
      destination, existing destination, invalid UTF-8, invalid TaskCard/postflight/report-path
      binding, or secret-shaped output before creating any file, and returns only a non-authorizing
      Artifact fact.
- [ ] Coder Codex, Coder Pi, Architect OpenCode/Codex and other unsupported combinations remain
      unadvertised and fail before mutation/provider start.
- [ ] Finding is off by default across profile generation, prompts/capture and normal status;
      explicit maintainer opt-in preserves Phase A behavior.
- [ ] Node doctor denies a client missing `--on-argv` before Bus health/event work and reports safe
      capability/provenance facts when compatible.
- [ ] Focused table-driven tests, full pytest, Ruff/format, resource validation and installed-wheel
      verification pass. Ordinary exact-head CI passes at the meaningful candidate.
- [ ] One independent L2 boundary Reviewer returns `PASS`; concrete findings receive focused repair
      and re-review only where affected.
- [ ] Closeout updates current repository truth and names Phase 5-02 fresh `awf run <TaskCard>`
      production integration as the only next legal milestone, without starting it.

## Verification

```text
python -m compileall -q src/agent_workflow scripts tests
python -m pytest -q tests/test_facade.py tests/test_cli.py tests/test_node.py \
  tests/test_status.py tests/test_runtime_provider_renderers.py tests/test_runtime_architect.py \
  tests/test_agent_adapters.py tests/test_awf_role.py tests/test_awf_listen.py
ruff check .
ruff format --check .
python -m pytest -q
python tests/verify_installed_wheel.py
awf validate roles
awf validate workflows
awf validate examples
git diff --check
```

## Frozen implementation scope

- `docs/tasks/phase5-01-capability-init.md`
- `src/agent_workflow/cli.py`
- `src/agent_workflow/facade.py`
- `src/agent_workflow/node.py`
- `src/agent_workflow/status.py`
- `src/agent_workflow/runtime/__init__.py`
- `src/agent_workflow/runtime/architect.py`
- `src/agent_workflow/runtime/contracts.py`
- `src/agent_workflow/runtime/renderers.py`
- `schemas/node-profile.schema.json`
- `scripts/awf_listen.py`
- `scripts/awf_role.py`
- `scripts/agent_adapters/codex.py`
- `scripts/agent_adapters/opencode.py`
- `scripts/agent_adapters/pi.py`
- `tests/test_facade.py`
- `tests/test_cli.py`
- `tests/test_node.py`
- `tests/test_status.py`
- `tests/test_runtime_provider_renderers.py`
- `tests/test_runtime_architect.py`
- `tests/test_agent_adapters.py`
- `tests/test_awf_role.py`
- `tests/test_awf_listen.py`
- `tests/verify_installed_wheel.py`
- `.awf/artifacts/impl-report-phase5-01-capability-init.md`
- `.awf/artifacts/review-report-phase5-01-capability-init.md`

After candidate verification and independent Review, closeout may additionally update:

- `docs/tasks/phase5-01-capability-init-report.md`
- `docs/plans/runtime-v2-development-plan.md`
- `README.md`
- `HANDOFF.md`
- `ROADMAP.md`

## Prohibited actions

- TaskCard execution, business event send, model invocation, ACK/retry/requeue/recovery, retained
  event/state operation or production Runtime adoption.
- Changing Workflow transition, RunStore/journal, ambiguity/replay, ACK ordering, migration, default,
  release or compatibility deletion semantics.
- Agent Bus code/server/service/credential/release changes or automatic client installation.
- Agent Host, scheduler, DAG, capability registry, generic provider/plugin framework, model catalog,
  dashboard, Finding Phase B, reporter onboarding, native launcher, signing/SBOM or Phase 6.
- Weakening exact role/profile/workspace/process identity or allowing two active roles to share one
  checkout path.

## Risk and failure handling

| Risk | Level | Required response |
|---|---:|---|
| Machine config/profile/workspace identity drift | L2 | deny before mutation; focused boundary tests |
| Provider advertised without renderer | L2 | closed static matrix and renderer-dispatch test |
| Partial init mutation | L2 | preflight all selections/targets; stage new clones; exact cleanup only for newly created staging |
| Finding alters business semantics | L2 | default-off tests; opt-in is prompt/capture/status only |
| Existing L3 authority behavior changes | L3 | stop, preserve evidence, and request a separately scoped repair |

Routine lint/test/interactive-output failures are repaired inside scope. Need for a new authority,
state migration, Runtime default switch, Agent Bus change or generic framework is `PLAN_CONFLICT`.

## Required output

- one capability-first current-machine init flow;
- one static honest role/provider matrix;
- one real Pi Architect renderer and trusted TaskCard output boundary;
- deterministic isolated role profiles/workspaces and same-tool warning;
- Finding default-off with explicit maintainer opt-in;
- capability-first Agent Bus diagnostics;
- focused/full/installed-wheel/CI evidence;
- ImplementationReport and independent ReviewReport;
- exact Phase 5-02 stop boundary.

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/cli.py",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/node.py",
    "src/agent_workflow/status.py",
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/architect.py",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/renderers.py",
    "schemas/node-profile.schema.json",
    "scripts/awf_listen.py",
    "scripts/awf_role.py",
    "scripts/agent_adapters/codex.py",
    "scripts/agent_adapters/opencode.py",
    "scripts/agent_adapters/pi.py",
    "tests/test_facade.py",
    "tests/test_cli.py",
    "tests/test_node.py",
    "tests/test_status.py",
    "tests/test_runtime_provider_renderers.py",
    "tests/test_runtime_architect.py",
    "tests/test_agent_adapters.py",
    "tests/test_awf_role.py",
    "tests/test_awf_listen.py",
    "tests/verify_installed_wheel.py",
    ".awf/artifacts/impl-report-phase5-01-capability-init.md",
    ".awf/artifacts/review-report-phase5-01-capability-init.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_facade.py", "tests/test_cli.py", "tests/test_node.py", "tests/test_status.py", "tests/test_runtime_provider_renderers.py", "tests/test_runtime_architect.py"],
    ["ruff", "check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
