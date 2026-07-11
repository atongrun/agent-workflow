# Phase 0 Follow-ups

> **Superseded (2026-07-11).** This review was written when Agent Workflow was still
> planned as a control-plane runtime with internal Port abstractions and an Agent Host
> `workflow.engine` plugin. The project has since been refocused as a portable
> development **method + handoff protocol**: the Runner/EventBus/Memory/ArtifactStore
> ports were removed, and execution/transport/memory are no longer core concerns. The
> items below that assume port abstractions or a plugin adapter (esp. the System
> Position section and the port ↔ capability mapping) no longer reflect the direction.
> Kept for history. Current direction: [`constitution.md`](../../constitution.md),
> [`ROADMAP.md`](../../ROADMAP.md), and deferred integrations under [`docs/later/`](../later/).

This review records hardening work that was considered before the refocus. It does not change Agent Workflow behavior.

## System Position

Agent Workflow is the control plane. Agent Host is the host/runtime layer. Agent Bus is the event/transport plane. AI Memory is the context/memory plane.

Agent Workflow will eventually run as the Agent Host `workflow.engine` plugin while preserving its internal port abstractions. Agent Host must provide capability client adapters rather than becoming the workflow state machine.

## WF-01: Package Schema Resources

Current risk:

- Schemas live at the repository root under `schemas/`.
- The wheel primarily packages `src/agent_workflow`.
- Validation currently relies on source-tree path discovery.
- Editable installs can mask failures that appear after installing a built wheel outside the repository.

Follow-up:

- Move or mirror runtime schemas into the Python package.
- Include schemas as package data.
- Load packaged schemas through `importlib.resources`.
- Add a smoke test that builds a wheel, installs it into a fresh virtual environment, changes outside the repository, and runs `awf validate`.

## WF-02: Route CLI Validation Through Semantic Checks

Current risk:

- `validate_workflow_semantics` and `validate_role_semantics` exist.
- `awf validate` mostly exercises JSON Schema validation.
- Semantic tests bypass the real CLI user path.

Follow-up:

- Make directory validation load a role map before checking workflows.
- Fail when a workflow references a missing role.
- Fail on duplicate stage IDs.
- Fail on invalid `onSuccess` and `onFailure` targets.
- Fail when role capabilities conflict with `forbiddenActions`.
- Add CLI tests that cover the real invocation path.

## WF-03: Add Agent Host Architecture Layer

Target architecture:

```text
Agent Host
└── Agent Workflow Plugin
    ├── RunnerPort        <-> runner.executor
    ├── EventBusPort      <-> event.bus
    ├── MemoryPort        <-> memory.provider
    └── ArtifactStorePort <-> artifact.store
```

Follow-up:

- Document Agent Workflow as the future `workflow.engine` plugin.
- Keep workflow run state inside Agent Workflow, not Agent Host.
- Preserve existing Port interfaces as Agent Workflow internal abstractions.
- Implement Host capability client adapters that satisfy those ports.
- Do not make Agent Workflow core depend on Agent Host Rust code.

## WF-04: Decide Schema Strictness

Decision needed:

- Whether `v1alpha1` should gradually add `additionalProperties: false`.
- How to catch misspellings without blocking early extension.

Recommended direction:

- Tighten stable object layers first.
- Leave extension points open where the contract is still actively evolving.
- Avoid one large schema lockdown that makes early adapters harder to prototype.

## WF-05: Separate Version Domains

Do not collapse these into one version:

- Agent Workflow resource API version.
- Artifact schema version.
- Event schema version.
- Agent Host capability version.
- Plugin implementation version.

Follow-up:

- Document where each version appears.
- Define compatibility promises independently per version domain.

## WF-06: Define Plugin Adapter Entry Point

Future plugin integration needs:

- `plugin.yaml`.
- JSON-RPC entry point.
- `workflow.engine` capability implementation.
- Host lifecycle methods.
- Capability client adapters.

This review only records the entry-point shape. It intentionally does not implement the plugin adapter.

## WF-07: Add Formal Install Smoke Tests

Future test flow:

- Build the wheel.
- Install it into a fresh virtual environment.
- From outside the repository, run:
  - `awf version`
  - `awf validate`
  - `awf inspect`

These tests should specifically prove that packaged schemas and CLI semantic validation work outside editable installs.

## Phase 1 Gate

Agent Workflow Phase 1 is blocked until Agent Host contract baseline is reviewed and approved.
