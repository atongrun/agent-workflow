# Changelog

## [Unreleased]

### Fixed

- Bind listener readiness to a per-start launch identity instead of assuming the spawned launcher
  PID equals the interpreter PID. Windows virtual-environment redirectors can return a different
  PID from `Popen`; the cross-platform identity preserves trusted ownership without depending on
  process topology or accepting role/repository identity alone.

## [0.3.0-rc.3] — 2026-08-09

### Added

- Add `awf node doctor --json --ttl-seconds` as a credential-free, fingerprinted operator
  discovery snapshot that can replace repeated SSH probes during a short serial run while keeping
  Fast/Deep Preflight as the only remote-dispatch authority.

### Fixed

- Allow a listener up to 15 seconds to publish its matching role/repository/PID lease after a
  successful local readiness gate. This accommodates slower Windows Python and workspace startup
  while preserving bounded fail-closed termination when no trusted lease appears.

## [0.3.0-rc.2] — 2026-08-09

### Added

- Add a reviewer-only Pi adapter with explicit text-mode non-interactive argv, read-only tools,
  trusted stdout-to-ReviewReport persistence after exit zero, `AWF_PI_BIN` configuration, and the
  existing selection-integrity, isolated-workspace, checkpoint/recovery, schema, outbox, and ACK
  gates. Coder support and a generic provider registry remain out of scope.
- Package the production operations modules, adapters, model Git guards, service assets, schemas,
  and artifact templates in the wheel so an installed `awf` does not depend on an Agent Workflow
  source checkout.
- Add the cross-platform `awf node doctor/start/status/stop/logs` local user-process surface with
  one credential-free role-profile schema and pre-model readiness checks.
- Add factual, read-only node status for listener, workspace, checkpoint, queue, artifact, PR, and
  CI observations, including separate `file_sha256` and `canonical_report_sha256` fields for a
  ReviewReport.

### Fixed

- Bind independent coder and reviewer selections through the owner RunManifest and the exact
  committed TaskCard. Mixed OpenCode-coder/Pi-reviewer runs now hand off the frozen reviewer
  selection, route `REQUEST_CHANGES` back to the frozen coder selection, and fail before model
  invocation when either role drifts. Existing cards without the optional selection block retain
  the prior same-tool behavior and the v3 payload schema is unchanged.
- Reject metadata-complete v1-v3 coder/reviewer deliveries when listener-local `AWF_TOOL` or
  `AWF_MODEL` differs from the integrity-hashed payload selection, before control-plane,
  recovery/outbox, model, or inbox lifecycle work; emit reviewer verdict identity from the
  validated effective selection while preserving legacy direct-entry overrides.
- Stop dispatch before Agent Bus delivery when the TaskCard branch push fails, preventing remote
  executors from receiving a pointer to an unavailable commit.
- Parse Windows credential ACL principals separately from the echoed target path so a secure file
  under `C:\Users\...` does not fail readiness, while unreadable ACLs, inherited ACEs, and grants
  to any principal other than the current user fail closed.
- Bypass environment HTTP proxies for the configured Agent Bus host at handoff, listener, and
  dispatch boundaries, preserving existing `NO_PROXY` entries while keeping private mesh traffic
  off localhost or corporate proxies.
- Move OpenCode coder and fallback reviewer runs into fresh event-scoped no-remote clones, restrict
  their ordinary Git command path to read operations, import only verified file/report deltas into
  the trusted checkout, refresh local/remote refs before publication, and generate Lore-compliant
  trusted commits. Reject authenticated proxy environment URLs before model launch while preserving
  credential-free proxy connectivity. Force-include configured report artifacts from ignored
  directories and reject reviewer evidence absent from the dispatched commit. Same-user
  hostile-code isolation remains an explicit operating boundary.
- Verify architect terminal events in event-scoped trusted workspaces without fetching, checking
  out, stashing, cleaning, or overwriting a shared source checkout. Preserve terminal-ledger,
  inbox-completion, replay, and ACK ordering when the source checkout is dirty.
- Reject listener startup before Bus connection when a role workspace is not ready, the role PID
  is already live, or another role owns the same repository. Local `Ctrl-C` now exits without a
  traceback and releases only the matching listener lease.

## [0.3.0-rc.1] — 2026-07-19

This was an internal candidate and was not published as a Git tag or GitHub Release.

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

[Unreleased]: https://github.com/atongrun/agent-workflow/compare/v0.3.0-rc.3...HEAD
[0.3.0-rc.3]: https://github.com/atongrun/agent-workflow/compare/v0.3.0-rc.2...v0.3.0-rc.3
[0.3.0-rc.2]: https://github.com/atongrun/agent-workflow/compare/v0.2.0...v0.3.0-rc.2
[0.2.0]: https://github.com/atongrun/agent-workflow/compare/a08664da1640207bd8757609cbf83348249df709...v0.2.0
[0.1.0]: https://github.com/atongrun/agent-workflow/commit/a08664da1640207bd8757609cbf83348249df709
