# Agent Workflow

**An opinionated, model-agnostic development method for AI-assisted projects.**

Agent Workflow codifies progressive planning, limited architecture challenge, task closure, layered review, information compression, and forced convergence. Contracts are its internal representation, not the product's primary user interface.

## Why This Exists

Every AI coding agent — Claude Code, Codex, OpenCode, Hermes — has its own planner,
architect, reviewer, sub-agents, and inner loop. What they lack is a **shared, portable
rule for how a project is developed**: when to freeze architecture, what may be delegated,
what must escalate, and what each stage must hand off.

Agent Workflow is that rule layer. It defines **what to do, who is responsible, what the
inputs and outputs are, and when to stop** — as plain contracts any tool can follow. It
does **not** re-implement planning, execution, review, or orchestration; those stay inside
each agent's own runner. The point is to put every tool under the same development method
and let you swap tools freely — not to compete with them.

The whole method lives in one file: [`constitution.md`](constitution.md).

## Product Direction

**Use first, abstract second.** Requirements that have not been validated in a real project do not enter the core architecture. The first target is a local or semi-automatic loop that can continue an existing project from its verified baseline; generic engines, remote scheduling, UI, and plugin systems are deferred.

For brownfield projects, the default path is:

`Current Baseline → Next Milestone → Incremental Plan → Current TaskCard → Execute and Verify`

See [Development Workflow MVP](docs/development-workflow-mvp.md) for the usage contract and [Agent Bus Brownfield Dogfood](examples/agent-bus-dogfood/README.md) for the complete real example.

## What It Is (and Isn't)

Agent Workflow ships as a small set of markdown/YAML contracts plus a thin, stateless
validation CLI. It never executes, schedules, or orchestrates anything.

The repository also contains `scripts/` used to dogfood the method across real agent clients and
machines. Those trusted runner/listener and service-operation scripts are an **operations surface
outside the `awf` core**: they exercise Agent Bus and model CLIs, but they do not turn the
validation CLI into a workflow engine or make transport part of the core contract.

**Boundaries**

1. It **does not** run models, spawn sub-agents, or drive an inner loop — each agent
   client does that internally.
2. It **does not** implement cross-machine transport or long-term memory. Those are
   external, optional concerns recorded under [`docs/later/`](docs/later/) — the core
   reserves no interfaces for them and runs with only local files.
3. It **does not** bind to any single model or tool. A tool may be swapped at any stage
   boundary without changing the contract.
4. Agents hand off via **structured Artifacts**, not free-form chat logs.

## Core Concepts

### Role
A role defines *responsibilities*, *capabilities*, and *constraints* — and, crucially,
authority boundaries (e.g. a reviewer may only flag deterministic failures). It binds to
no model, tool, or runner. Default roles: `planner`, `implementer`, `tester`, `reviewer`,
`summarizer`, `arbiter`.

### Workflow
A workflow declares *stages* and their *transitions*. Each stage is assigned a role and
declares its inputs, outputs, and `onSuccess`/`onFailure` targets. Example:
`plan → implement → test → review → summarize → decide`. It is a description of *what
happens and when to stop* — not an execution engine.

### Artifact
Structured handoff documents between stages: `TaskCard`, `ImplementationReport`,
`TestReport`, `ReviewReport`, `DecisionPacket`, `Decision`. Each carries machine-readable
data and a human-readable summary. The artifact chain — not chat history — is the portable
state any client reads to produce the next step.

## Phase 0 Validation Quick Start

```bash
# Install
pip install -e .

# Validate all resources
awf validate roles
awf validate workflows
awf validate examples

# Inspect a resource
awf inspect workflows/feature-delivery.yaml

# Check version
awf version
```

These commands validate and inspect contracts; they do not start a development Workflow Run.

## MVP Run Quick Start

The usable MVP must support this path:

```bash
awf init \
  --project ../agent-bus \
  --goal examples/agent-bus-dogfood/goal.md \
  --mode dual \
  --executor manual \
  --reviewer manual \
  --decider manual

awf status --project ../agent-bus
awf next --project ../agent-bus
awf submit --project ../agent-bus --artifact /path/to/result.md
```

The current Phase 0 CLI does not implement these run commands yet. They are the acceptance contract for Phase 1; the project is not considered usable for development work until this Quick Start completes end to end.

## CLI Examples

```bash
# Validate a single file
awf validate roles/planner.yaml
# PASS roles/planner.yaml

# Validate a directory
awf validate roles
# PASS roles/planner.yaml
# PASS roles/implementer.yaml
# ...

# Validate each resource directory
awf validate roles
awf validate workflows
awf validate examples

# Inspect a workflow
awf inspect workflows/feature-delivery.yaml
# apiVersion: agent-workflow/v1alpha1
# kind: Workflow
# name: feature-delivery
# version: 0.1.0
# stages: 6
#   - plan [planner] (onSuccess: implement, onFailure: failed)
#   - implement [implementer] (onSuccess: test, onFailure: failed)
#   ...

# Inspect a role
awf inspect roles/planner.yaml
# capabilities (4):
#   - Read task descriptions and requirements
#   - Read project structure and documentation
#   ...
# forbiddenActions (4):
#   - Modify code or configuration files
#   ...
```

## Example Workflow: Feature Delivery

```yaml
apiVersion: agent-workflow/v1alpha1
kind: Workflow
metadata:
  name: feature-delivery
spec:
  stages:
    - id: plan          # planner → TaskCard
    - id: implement     # implementer → ImplementationReport
    - id: test          # tester → TestReport, onFailure → implement
    - id: review        # reviewer → ReviewReport, onFailure → implement
    - id: summarize     # summarizer → DecisionPacket
    - id: decide        # arbiter → Decision (approve | request_changes | reject | escalate)
```

## Repository Structure

```
agent-workflow/
├── constitution.md    # The development method — the single source of truth
├── docs/              # Concepts, ADRs; docs/later/ holds deferred integrations
├── schemas/           # JSON Schema for Role, Workflow, Artifact
├── roles/             # Default role definitions
├── workflows/         # Default workflow definitions
├── templates/         # Artifact templates
├── examples/          # Complete example configurations
├── src/agent_workflow/ # Thin validation CLI (awf)
│   ├── cli.py          # CLI entry point (validate, inspect)
│   ├── validation.py   # Schema + semantic validation
│   ├── models.py       # Data models
│   └── errors.py       # Error types
└── tests/              # Test suite
```

## Current Status

**Phase 0 — Contract Bootstrap** (current; validation-only)

- ✅ The development method in one file (`constitution.md`)
- ✅ JSON Schema for Role, Workflow, Artifact
- ✅ Default roles (planner, implementer, tester, reviewer, summarizer, arbiter)
- ✅ Default workflows (feature-delivery, bugfix, documentation, research)
- ✅ Artifact templates for all handoff types
- ✅ Validation CLI (`awf validate`, `awf inspect`)
- ✅ Schema and semantic validation tests
- ✅ CI pipeline (GitHub Actions)

Cross-machine transport (Agent Bus) and shared long-term memory (AI Memory) are deferred, external, and optional — recorded under [`docs/later/`](docs/later/). The core reserves no interfaces for them.

Phase 0 is not yet a usable development workflow: it cannot initialize a run, establish a brownfield baseline, produce architecture/phase/task artifacts, or import execution results.

### Operations dogfood checkpoint

The external operations surface has advanced beyond the Phase 0 CLI and is deliberately tracked
separately:

- ✅ exact executor checkout and dispatched-commit synchronization;
- ✅ model subprocess credential/stdin boundaries and required ImplementationReport gating;
- ✅ trusted postflight verification, allowed-path, artifact, secret, and diff gates;
- ✅ OpenCode file-array argv termination and repository-wide Ruff format baseline;
- ✅ mandatory push plus refreshed remote-SHA proof before reviewer handoff;
- ✅ durable handler-exit evidence and a real Windows no-code handler-return/ACK proof;
- 🚧 reviewer verdict routing remains unsafe: tool exit zero and `tool-review-complete` are not
  semantic approval. The next P0 is the
  [reviewer verdict routing TaskCard](docs/tasks/reviewer-verdict-routing.md).

The launchd, systemd, WinSW, and `just` service surfaces are implemented as operations templates.
Their three-OS install, reboot, crash-recovery, and unattended-listener behavior has not been
accepted end to end; see [listener service status](scripts/service/README.md).

An open product question remains: whether any of these dogfood runner/listener conveniences should
eventually become an official Agent Workflow product surface. Until that decision is made, keep the
boundaries distinct: core method/validation CLI, operations scripts, Agent Bus transport, listener
service supervision, and a possible future Agent Host.

## What Agent Workflow Is Not

Agent Workflow is **not**:

- an LLM
- a coding agent
- a replacement for Agent Bus
- a replacement for AI Memory
- a hosted multi-agent platform
- a visual workflow builder

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full roadmap.

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Contract Bootstrap | ✅ Current |
| 1 | Minimum usable development loop | 📋 Planned |
| 2 | Agent Bus brownfield dogfood | 🚧 Operations evidence collected; artifact loop incomplete |
| 3 | Evidence-driven hardening | 📋 Deferred until dogfood |
| Later | Optional external integrations (Agent Bus, AI Memory) | 📋 Deferred |

## License

MIT — see [LICENSE](LICENSE).
