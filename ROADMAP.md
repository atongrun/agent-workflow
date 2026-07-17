# Roadmap

## Product Gate

**Use first, abstract second.** Agent Workflow must complete one real brownfield development loop before expanding generic infrastructure. Requirements that have not appeared in real use do not enter the core architecture.

The first proof project is Agent Bus. Until its baseline-to-decision run completes, do not expand UI, cross-machine automation, a generic plugin system, complex runtime machinery, arbitrary DAGs, or generalized retry/retrieval protocols.

## Phase 0: Contract Bootstrap ✅ Current

- [x] Repository and project structure
- [x] The development method in one file (`constitution.md`)
- [x] JSON Schema and semantic validation (Role, Workflow, Artifact)
- [x] Initial roles, workflows, and artifact templates
- [x] Validation/inspection CLI
- [x] Concepts, handoff-semantics, and ADR documentation
- [x] Tests and CI

Phase 0 is validation-only. It is not a usable development workflow because a user cannot initialize a run, establish a brownfield baseline, obtain architecture/phase/task artifacts, or submit execution results.

> The earlier Phase 0 shipped Runner/EventBus/Memory ports, local adapter stubs, and BindingProfile/Policy/Event schemas. These were removed when the project was refocused as a portable method + handoff protocol; execution, transport, and memory belong to each agent client or to deferred external projects (`docs/later/`), not the core.

## Phase 1: Minimum Usable Development Loop 📋

The acceptance path is documented in [Development Workflow MVP](docs/development-workflow-mvp.md).

- [ ] `awf init` accepts a project, goal, architecture mode, executor, reviewer, and decider
- [ ] Brownfield initialization records verified capabilities, constraints, unfinished work, next milestone, blockers, and test evidence
- [ ] Any generated Workflow YAML remains internal output rather than required user input
- [ ] `awf status`, `awf next`, and `awf submit` support resumable manual handoff **statelessly** — progression is a function of which artifacts exist on disk, not a private state machine
- [ ] Single-architect self-challenge and dual-architect one-primary/one-challenger modes
- [ ] Three-round hard stop: freeze, freeze with known risk, or wait for user
- [ ] Separate project `ArchitectureRecord`, current `PhasePlan`, and executable `TaskCard`
- [ ] Only deterministic failures may return to execution; optional improvements cannot block
- [ ] Compressed DecisionPacket excludes full diffs by default
- [ ] Next TaskCard or next-phase refinement follows a completed decision
- [ ] Quick Start runs end to end in a temporary fixture

Keep `awf` limited to these method-specific, stateless helpers: render the next packet, validate submitted artifacts. It must not execute models, hold run state, or decide transitions — the human plus the chosen agent client drive progression.

## Phase 2: Agent Bus Brownfield Dogfood 📋

Run the complete [Agent Bus example](examples/agent-bus-dogfood/README.md) before broader hardening.

The repository has already collected substantial **operations dogfood** outside the Phase 0
validation CLI: exact checkout synchronization, trusted executor boundaries, postflight completion,
OpenCode argv portability, push plus remote-SHA proof, durable handler evidence, and a real Windows
handler-return/ACK gate are on `main`. Agent Bus v0.2.0 has also completed a separate real
three-endpoint transport acceptance. These facts do not complete the artifact-chain checklist below:
the current reviewer path still treats tool completion as a placeholder verdict and cannot safely
route a structured ReviewReport.

The next and only P0 is [reviewer verdict routing](docs/tasks/reviewer-verdict-routing.md). Until it
lands, `tool-review-complete`, process exit zero, and a missing or malformed report must never be
treated as PASS or used to advance a workflow.

- [ ] Regenerate and verify the existing Agent Bus baseline
- [ ] Freeze only the architecture needed for the next diagnostic milestone
- [ ] Produce the current phase plan and `ABUS-DIAG-001` TaskCard
- [ ] Implement and test the non-mutating `agent-bus doctor --json` slice
- [ ] Complete first-line review and compressed final decision
- [ ] Record architecture rounds, manual handoffs, deterministic rework, optional suggestions, packet size, and targeted context requests
- [ ] Continue to the next task or next phase from the same run

Success means the artifact chain is complete and Agent Bus made a verified increment—not that Agent Workflow supports every project shape.

Service supervision remains a separate operations candidate. launchd, systemd, WinSW, and `just`
surfaces exist, but their three-OS install, reboot, crash-recovery, and unattended-listener behavior
has not been accepted. Whether runner/listener conveniences formally belong to Agent Workflow is an
open product decision; do not resolve it by silently moving execution or transport into the core.

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
