# Changelog

## [Unreleased]

### Changed

- Reframed Agent Workflow around a use-first personal development method rather than generic orchestration completeness.
- **Shrank the core to a portable development method + handoff protocol.** Agent Workflow now defines *what to do, who is responsible, inputs/outputs, and when to stop* — it never executes, schedules, or orchestrates. Execution, sub-agents, and inner loops belong to each agent client's own runner.
- Added `constitution.md` as the single source of truth for the development method (project mode, greenfield/brownfield start, architecture convergence and round limits, delegation vs. escalation, reviewer authority, required per-stage artifacts, cross-client handoff).
- Made the `TaskCard` a **self-contained handoff package** (§6a): it carries its own working context (repo path, entry points, relevant files, no-regress notes) so a fresh-session executor on another machine can work from the card alone, and points to the *project's* `AGENTS.md` for real commands — keeping the portable method separate from per-project facts.
- Added a **pre-delegation consistency gate** (§6b): a planner self-check embedded in the TaskCard template that must pass before a card is handed to an executor (single deliverable, verifiable criteria, real commands, milestone-aligned).
- Defined the target Workflow Run Quick Start and brownfield project defaults; clarified that `awf` is **stateless** (renders packets, validates artifacts) and does not hold run state or decide transitions.
- Added a complete Agent Bus dogfood example covering baseline, goal, manual handoff, review, decision, and phase continuation.

### Removed

- Removed the Runner/EventBus/Memory/ArtifactStore **ports** and their local adapter stubs (`ShellRunner`, `LocalEventBus`, `LocalMemory`, `FilesystemArtifactStore`) — the core does not execute, transport events, or store memory.
- Removed the `BindingProfile`, `Policy`, and `Event` schemas, the `profiles/` directory, and example `bindings.yaml` — roles bind to no runner, and there is no policy engine or event protocol in the core.
- Removed the three-plane / Port-Adapter architecture narrative and the stage/run state-machine docs; retitled lifecycle docs as handoff semantics.

### Deferred

- Cross-machine transport (Agent Bus) and shared long-term memory (AI Memory) are now optional **external** integrations recorded under `docs/later/`. The core reserves no interfaces for them; adapters will be written against real APIs when a project needs them.

## [0.1.0] — 2026-07-07

### Added

- Initial project bootstrap (Phase 0: Contract Bootstrap).
- JSON Schema definitions for Role, Workflow, BindingProfile, Event, Artifact, Policy.
- Six default roles: planner, implementer, tester, reviewer, summarizer, arbiter.
- Four default workflows: feature-delivery, bugfix, documentation, research.
- Artifact templates: TaskCard, ImplementationReport, TestReport, ReviewReport, DecisionPacket, Decision, MemoryWriteCandidate.
- `awf validate` CLI command with JSON Schema and semantic validation.
- `awf inspect` CLI command for resource inspection.
- `awf version` CLI command.
- Port interfaces: RunnerPort, EventBusPort, MemoryPort, ArtifactStorePort.
- Local adapters: LocalEventBus, LocalMemory, FilesystemArtifactStore, ShellRunner.
- Integration contracts for Agent Bus and AI Memory.
- Architecture documentation, concept guide, lifecycle documentation.
- Four ADRs (project boundaries, contract-first design, artifact-based handoff, optional adapters).
- GitHub Actions CI (lint + test + validation).
- Example profiles and workflows.

[0.1.0]: https://github.com/atongrun/agent-workflow/releases/tag/v0.1.0
