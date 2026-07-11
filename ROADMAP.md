# Roadmap

## Product Gate

**Use first, abstract second.** Agent Workflow must complete one real brownfield development loop before expanding generic infrastructure. Requirements that have not appeared in real use do not enter the core architecture.

The first proof project is Agent Bus. Until its baseline-to-decision run completes, do not expand UI, cross-machine automation, a generic plugin system, complex runtime machinery, arbitrary DAGs, or generalized retry/retrieval protocols.

## Phase 0: Contract Bootstrap ✅ Current

- [x] Repository and project structure
- [x] JSON Schema and semantic validation
- [x] Initial roles, workflows, profiles, and artifact templates
- [x] Validation/inspection CLI
- [x] Port boundaries and local adapter stubs
- [x] Architecture, lifecycle, integration, and ADR documentation
- [x] Tests and CI

Phase 0 is validation-only. It is not a usable development workflow because a user cannot initialize a run, establish a brownfield baseline, obtain architecture/phase/task artifacts, or submit execution results.

## Phase 1: Minimum Usable Development Loop 📋

The acceptance path is documented in [Development Workflow MVP](docs/development-workflow-mvp.md).

- [ ] `awf init` accepts a project, goal, architecture mode, executor, reviewer, and decider
- [ ] Brownfield initialization records verified capabilities, constraints, unfinished work, next milestone, blockers, and test evidence
- [ ] Generated Workflow/Profile YAML remains internal output rather than required user input
- [ ] `awf status`, `awf next`, and `awf submit` support resumable manual handoff
- [ ] Single-architect self-challenge and dual-architect one-primary/one-challenger modes
- [ ] Three-round hard stop: freeze, freeze with known risk, or wait for user
- [ ] Separate project `ArchitectureRecord`, current `PhasePlan`, and executable `TaskCard`
- [ ] Only deterministic failures may return to execution; optional improvements cannot block
- [ ] Compressed DecisionPacket excludes full diffs by default
- [ ] Next TaskCard or next-phase refinement follows a completed decision
- [ ] Quick Start runs end to end in a temporary fixture

Keep the controller limited to these method-specific gates. Generic execution or scheduling mechanics may later be replaced by mature projects.

## Phase 2: Agent Bus Brownfield Dogfood 📋

Run the complete [Agent Bus example](examples/agent-bus-dogfood/README.md) before broader hardening.

- [ ] Regenerate and verify the existing Agent Bus baseline
- [ ] Freeze only the architecture needed for the next diagnostic milestone
- [ ] Produce the current phase plan and `ABUS-DIAG-001` TaskCard
- [ ] Implement and test the non-mutating `agent-bus doctor --json` slice
- [ ] Complete first-line review and compressed final decision
- [ ] Record architecture rounds, manual handoffs, deterministic rework, optional suggestions, packet size, and targeted context requests
- [ ] Continue to the next task or next phase from the same run

Success means the artifact chain is complete and Agent Bus made a verified increment—not that Agent Workflow supports every project shape.

## Phase 3: Evidence-Driven Hardening 📋

- [ ] Fix only failures or repeated manual burden observed in dogfood
- [ ] Run a second bounded Agent Bus task
- [ ] Promote behavior into a reusable core capability only after repeated evidence
- [ ] Package schemas and add install smoke tests when needed by real use
- [ ] Improve recovery or automation only where the run proves value

## Later: Optional Integrations

Consider these only after the real-project gate:

- Agent Bus transport adapter and cross-machine dispatch
- Agent Host `workflow.engine` integration
- AI Memory adapter
- Codex, Claude Code, Hermes, and OpenCode runner conveniences
- UI or tray experience
- Generic plugin/runtime integration using a mature implementation where practical

## Explicit Non-Roadmap

- Hosted multi-tenant SaaS
- Visual drag-and-drop workflow builder
- Database migration without demonstrated need
- Kubernetes operator
- Cloud-provider SDKs
- Reimplementing a general-purpose multi-agent framework for completeness
