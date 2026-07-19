# Changelog

## [Unreleased]

## [0.3.0-rc.1] — 2026-07-19

### Core method and contracts

- Defined Agent Workflow as a model-agnostic development method, structured handoff protocol, and
  verifiable process contract that isolates high-value-model capacity in downstream projects.
- Separated infrastructure-development reliability metrics from downstream capacity-isolation
  metrics; infrastructure work is not required to minimize high-value-model use.
- Defined Repository Truth, Run Context, TaskCard, AI Memory, Agent Bus, and future-runtime
  boundaries without adding a runtime or adapter.
- Added `ArchitectureRecord` and `PhasePlan` as recognized Artifact types and aligned first-line
  ReviewReport verdicts to `PASS`, `REQUEST_CHANGES`, and `BLOCKED`.

### Operations surface

- Added role-based dispatch/listener scripts, cross-platform bootstrap and handoff checks, and
  launchd, systemd, and WinSW service templates without promoting them into the stateless core.
- Added exact dispatched-commit checkout, isolated model-process execution, trusted postflight,
  allowed-path, secret, diff, commit/push, and refreshed remote-SHA completion gates.
- Added durable handler logs and atomic result evidence so model completion, postflight entry, and
  handler exit remain independently auditable after the listener process ends.
- Replaced tool-exit-based review completion with structured semantic ReviewReport validation and
  fail-closed `PASS`, `REQUEST_CHANGES`, and `BLOCKED` event routing.

### Verification and release metadata

- Closed the Windows Python 3.12 default-locale boundary with explicit UTF-8 resource handling,
  trusted verification-environment isolation, and a fresh Windows postflight acceptance.
- Reconciled repository, branch, TaskCard, implementation-report, and archived failure-evidence
  truth after the reviewer-routing and Windows portability work landed.
- Set the PEP 440 package candidate version to `0.3.0rc1` (future Git tag
  `v0.3.0-rc.1`) and added a regression test that keeps project, runtime, and CLI versions aligned.
- Packaged the canonical root `schemas/` files as runtime package resources and added a clean-wheel
  installation gate so `awf validate` no longer depends on a source checkout.

### Not yet complete

- No fresh uninterrupted cross-machine semantic loop has accepted dispatch through implementation,
  review, verdict routing, merge or deterministic rework, and next-TaskCard continuation.
- Capacity-isolation metrics have not yet been captured from that live loop.
- The first non-infrastructure downstream multi-TaskCard dogfood remains a product gate.
- Listener supervision and operations helpers remain a non-core surface; this candidate does not
  claim a generic runtime, scheduler, Agent Host, or plugin system.

## [0.2.0] — 2026-07-11

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

[Unreleased]: https://github.com/atongrun/agent-workflow/compare/v0.3.0-rc.1...HEAD
[0.3.0-rc.1]: https://github.com/atongrun/agent-workflow/compare/v0.2.0...v0.3.0-rc.1
[0.2.0]: https://github.com/atongrun/agent-workflow/compare/a08664da1640207bd8757609cbf83348249df709...v0.2.0
[0.1.0]: https://github.com/atongrun/agent-workflow/commit/a08664da1640207bd8757609cbf83348249df709
