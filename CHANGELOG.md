# Changelog

## [Unreleased]

### Changed

- Reframed Agent Workflow around a use-first personal development method rather than generic orchestration completeness.
- Defined the target Workflow Run Quick Start and brownfield project defaults.
- Added a complete Agent Bus dogfood example covering baseline, goal, manual handoff, review, decision, and phase continuation.
- Deferred UI, cross-machine automation, generic plugins, and complex runtime work until a real project completes the workflow.

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
