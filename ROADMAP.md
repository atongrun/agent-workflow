# Roadmap

## 2026-08-24 v0.4.0-rc.2 Productization Scope

The sole RC.2 implementation authority is the
[v0.4.0-rc.2 Productization Plan](docs/plans/v0.4.0-rc.2-productization-plan.md). The execution model
is frozen. RC.2 is limited to:

- [ ] reconcile product/help/architecture and first-run/configured-selection truth;
- [ ] provide one read-only status/error projection with blocker, next safe action and conservative
  allowed actions;
- [ ] tighten PR-level TaskCard decomposition policy and prove validator conformance without a new
  TaskCard protocol;
- [ ] pass one clean-installed real two-card milestone plus Coder/Reviewer kill and Windows/macOS
  listener UX acceptance;
- [ ] repair only Golden Path blockers retained by that E2E.

Operations formal packaging, `awf_role.py` decomposition, MCP, provider session resume, benchmark
infrastructure, new providers, TaskCard vNext, parallel/DAG execution, dashboard/TUI, plugin systems
and Runtime v2 default migration are outside RC.2. See the plan for immediate post-RC.2 ordering,
backlog and explicit rejects.

## Product Gates

1. **Use first, abstract second.** A requirement enters the stable core only after real use proves
   it belongs there.
2. **Engineering feasibility is not product value.** Cross-machine dispatch and ACK prove transport
   boundaries. Downstream value requires evidence that frequent high-value-model participation was
   replaced by a lower-cost execution/review chain without losing completion quality.

Before UI, a generic engine, arbitrary DAGs, Plugin SDK, Agent Host integration, or broad runtime
automation, complete one downstream Phase that records model role, invocation class, escalation
reason, deterministic rework, human intervention, and TaskCard completion.

## 2026-08-22 Phase 5 Productization

- [x] Merge Phase 4B PR #120 into `main` as `6ce5182` without unrelated changes.
- [x] Freeze and independently review one Phase 5-01 capability-first current-machine init TaskCard.
- [x] Configure any Architect/Coder/Reviewer subset with exact profiles and distinct deterministic
  role checkouts while permitting one Agent Tool installation/model to serve several roles.
- [x] Add the first real Architect provider capability as Pi read-only rendering plus a trusted,
  create-only, non-authorizing TaskCard stdout boundary.
- [x] Persist model selection as tool-default or one opaque explicit Agent Tool-native reference;
  never own provider auth/config/catalog/defaults or silent fallback.
- [x] Require Agent Bus structured argv capability before health/event work and record safe client
  provenance rather than trusting ambiguous version text.
- [x] Make Finding profile opt-in/default-off across prompts, capture and normal status.
- [x] Repair and regression-lock recoverable profile/machine-config replacement after independent
  Review found one partial-init split-binding risk.
- [x] Pass local focused `470/2`, full `913/5`, installed-wheel, ordinary CI `32574488604`, Binary
  Feasibility `32574488742` and independent focused re-review at candidate `d9f470c`.
- [x] Owner integrated Phase 5-01 through PR #121 as `8f13b80`.
- [x] Close Phase 5-02 on one real Pi-authored downstream card: exact PlanFact, internal Fast/Deep,
  Windows OpenCode, trusted PR/CI/AWF merge, CompletedCardFact and zero queues.
- [x] Close Phase 5-03 on one real two-card milestone: fresh main after Card 1, dynamically authored
  Card 2 bound to that main, two immutable completion facts, two PR/CI/AWF merges, exact
  `MILESTONE_COMPLETE` and zero queues.
- [x] Prepare `0.4.0rc1`, release notes, installed-wheel evidence and Draft PR #122 for owner Release
  review; stop feature work at this boundary.

Phase 5 reuses the production v0.3.0 operations path and Agent Bus v0.3.1 transport. It adds no
Runtime v2 default/adoption, second worker/Git pipeline, Host/scheduler/TaskCard queue, migration,
native launcher or compatibility deletion. Deferred Recovery/Resume remains explicitly out of the
release candidate: Human stop/resume, active Architect/process-crash recovery, partial Coder
workspace takeover, provider session resume, mutation/ACK or merge ambiguity reconciliation, Plan
hot update, Architect hot swap, concurrent milestones, retained-state migration and V2 cutover.

## 2026-08-19 Runtime Simplification Decision Program

- [x] Preserve the owner Review, adversarial double review and gated Runtime v2 development plan.
- [x] Complete the RTS-001 TaskCard: Draft semantic contract, 39-case machine-readable fault matrix,
  current authority/evidence inventory, static validation and independent Reviewer `PASS`.
- [x] Integrate PR #96 after final exact-head review/CI. Three bounded macOS arm64 attempts failed at
  the same external GitHub API 403; a later fresh run cleared the block and passed the full matrix.
- [x] Merge the reviewed/green compiled-handler binding remediation in PR #97 as `38dffae1`.
- [x] Merge PR #98's platform-neutral TaskCard identity fix after final exact-head CI/Review as
  `d92594d`, with all five Binary Feasibility targets plus aggregate green.
- [x] Complete RTS-010 with one fresh post-remediation bounded downstream business PASS: exactly one
  coder and reviewer invocation, terminal PASS, five ACKed isolated events, green CI and merge.
- [x] Correct the RTS-011 Python prerequisite so one authorized rework unlocks exactly one
  follow-up review while distinct review deliveries retain input `attempt=1`; PR #100 passed
  independent Review, ordinary cross-platform CI and all five Binary Feasibility targets.
- [x] Complete RTS-011 with the disposable deterministic
  `implement -> review -> rework -> review -> terminal` acceptance.
- [x] Promote the contract to `Candidate` after both reference acceptances pass.
- [x] Complete RTS-020 with one removable Python shared slice: one implement/review normal path,
  all eight fault families across 14 machine rows, one RunStore writer, one InvocationJournal API,
  independent implementation Review, green ordinary/Binary CI on pre-final-review head `77c7023`,
  and corrupt authorized-journal outcome repair on `457a336`.
- [x] Complete RTS-021 with one backend-neutral atomic/SQLite comparison: the same 14 shared rows,
  four named local windows, 11 storage cases, strict observed-fact eligibility, independent Review,
  and green ordinary/Binary CI on pre-closeout head `00baa356`.
- [x] Complete RTS-022A with one removable zero-dependency Rust slice: the same 14 shared rows,
  five native targets, strict aggregate evidence, no Python process, independent semantic Review,
  and green ordinary/Binary CI on pre-closeout head `3be3263`.
- [x] Complete RTS-022B with one blinded Candidate fault, one fresh independent maintainer, one
  semantic repair, exact seeded/candidate five-target evidence, and independent Gate Review PASS.
- [x] Complete RTS-024 with the same-fixture comparison and owner decision: Python refactor,
  checksummed atomic-file RunStore/journal, logical single writer, narrow product boundary and later
  bounded native-launcher candidate; freeze the contract after Architecture and Adversarial PASS.
- [x] Complete RTS-030 as the first independently reversible Phase 3 Python Core interface/package
  boundary without dual write, default change, representation deletion or launcher work.
- [x] Complete RTS-031 as a pure local checksummed atomic-file RunStore/per-invocation journal
  implementation behind the selected ports, with no production handler migration or dual write.
- [x] Complete RTS-032 as the closed installed Codex/OpenCode/Pi provider-renderer seam, preserving
  current production authority/recovery and passing independent Review plus exact-head CI.
- [x] Complete RTS-033 as the event-contained no-remote workspace, compatible Git-control identity
  and exact trusted local import seam, preserving sole current production authority.
- [x] Complete RTS-034 as the installed TaskCard/report identity, strict report/raw-Artifact and
  postflight-decision seam, preserving sole current production authority and recovery.
- [x] Complete RTS-035 as the disposable selected local `run/status/stop` application composition,
  with full PASS/rework/BLOCKED paths, all shared faults and no production/default adoption.
- [x] Complete RTS-040 as the strict versioned Stage-blind command/result envelope and no-I/O local
  receive/preparation boundary, with exact identity/causation and pre-provider denial.
- [x] Complete RTS-041 as the Store-owned exact outgoing-intent and bounded Stage-blind sender
  boundary, with attempt-before-I/O, conservative ambiguity and no ACK ownership.
- [x] Preserve RTS-042-01 as terminal failed and `EXTERNAL_BLOCKED`; prove the bounded Git-blob
  fixture repair with exact-head CI and one separately fresh RTS-042-02 cross-machine success.
- [x] Complete RTS-043 evidence adjudication and Phase 4A closeout after final focused independent
  re-review clears the documentation-only closeout findings.
- [x] Complete RTS-044 local native-lifecycle conformance review without adding an
  `AgentInstallation` abstraction; preserve its initial exact-identity findings.
- [x] Complete RTS-045 bounded exact-lifecycle repair for process-root and installed manager-target
  identity, with focused/full tests, independent L3 Review and exact-head cross-platform CI.
- [x] Complete RTS-047 bounded native venv re-entry repair after the first real LaunchAgent scope,
  with independent L3 Review and exact-head CI.
- [x] Complete RTS-048 bounded Windows login-recovery repair for transient pre-listener readiness and
  PID-reuse exact stale cleanup, with independent L3 re-review and exact-head CI.
- [x] RTS-046 passes real macOS launchd, fresh `tx-vps` Linux systemd-user, non-disruptive Windows
  Task Scheduler under `-03`, and real Windows logout/login under `-05`.
  Do not count failed macOS `-01`/`-02` or Windows `-04` as PASS.
- [ ] Before Phase 5, separately consider a formal Agent Bus client release (likely v0.3.1) carrying
  `agent-bus.listen.on-argv.v1`; do not publish or redesign Agent Bus through RTS-046.

Current last passed implementation TaskCard gate is RTS-048; Phase 3 and Phase 4A are complete, and
local Phase 4B lifecycle conformance is closed. Fresh RTS-046 evidence now passes all three native
managers and Windows login. Independent review rejected a new lifecycle abstraction and
closed exact-identity defects through RTS-045, native venv re-entry through RTS-047 and login stale
convergence through RTS-048. Fresh Windows `-05` completed the one authorized logout, RustDesk PIN
login, automatic exact Task Scheduler convergence and exact stop/uninstall. Fresh Linux `-06` used
the owner-corrected `tx-vps` root/systemd-user and unchanged local Bus Server, produced two exact
incarnations, exact stop/uninstall and complete disposable cleanup with linger/unit/server baselines
restored. The prior `la-codex-node` assumption is invalid and excluded.
ADR-0006 selects
`PYTHON + NATIVE LAUNCHER` with a checksummed atomic-file RunStore/per-invocation journal, one
logical writer and no physical Coordinator. The semantic contract and 39-case/11-outcome matrix
are Frozen. RTS-030 added strict
installed Python Core contracts and ports. RTS-031 added the selected disposable local Store and
journal; RTS-032 moved existing provider command rendering behind the installed Runtime boundary
while leaving current state sole authority; RTS-033 moved exact isolated-workspace and trusted
local import effects behind the same boundary; RTS-034 moved Artifact validation and exact raw facts
without changing recovery or lineage authority; RTS-035 composes those seams through one disposable
local application and exact Store writer; RTS-040 adds the strict Stage-blind envelope and local
receive/preparation boundary; RTS-041 adds the exact Store-owned outgoing intent and conservative
attempt-before-I/O adapter. RTS-042-01 remains failed and permanently excluded from PASS;
RTS-042-02 alone proves the fresh isolated Mac-to-Windows request/result, two real children, two
ACKed events and `0/0 -> 0/0`. Rust remains a comparison oracle, RTS-023 does not enter, SQLite is
not selected, and launcher work remains deferred. Final independent RTS-046 evidence review returned
PASS with zero blocking findings; Phase 4B is closed. STOP: Phase 5 needs a separate owner-approved
replan and must not start from this branch. Agent Bus is not installed or absorbed by AWF. Before any
Phase 5 plan, consider a small formal
client release (likely v0.3.1) for the already-implemented structured argv contract; publishing is
not authorized. Phase 5 is not started or authorized. No
production/retained Bus operation, production Store adoption or dual write, default, migration,
release, retained-event operation or destructive cleanup is authorized. See the
[development plan](docs/plans/runtime-v2-development-plan.md) and
[RTS-046 acceptance report](docs/tasks/runtime-v2-rts-046-native-manager-acceptance-report.md).

## 2026-08-17 Usability Remediation Final Gate

- [x] Measure the seven-command local synthetic facade journey from a fresh installed wheel and
  disposable configuration/state roots without a model or business event.
- [x] Run exact-main Fast Preflight on fresh Mac, VPS, and Windows surfaces and preserve the first
  fail-closed boundary without repairing around it.
- [x] Complete Deep Preflight with both scoped queues observed at zero and provisioned VPS/Windows
  operations configuration.
- [ ] Authorize one new business TaskCard only after the fresh no-model gates pass.

The original benchmark result was `BLOCKED_BEFORE_DEEP`: Mac observed one coder-scoped pending
delivery by count only, and the disposable VPS/Windows surfaces lacked strict operations
configuration. A separately authorized, isolated rerun then passed all nine Fast layers on all
three hosts and one Mac-to-Windows Deep route with handler success, acknowledged request/result,
and scoped queues `0/0 -> 0/0`. The current no-model gate is `PASS`; no production or retained
delivery was inspected or operated. See the
[historical benchmark](docs/tasks/fresh-machine-usability-benchmark-report.md) and
[acceptance closeout](docs/tasks/fresh-machine-usability-acceptance-closeout-report.md).

## Binary Release Readiness

The completed P2 matrix remains `NO_GO_PRODUCTION_BINARY`. The deterministic P2b assessment rejects
repairing one measured freezer candidate because real Python module/script re-entry failed in all
15 cells. The shortest legal next experiment is a native launcher plus relocatable real CPython
and an installed AWF application, with Agent Bus independently distributed. This is not yet an
adopted production contract.

- [ ] Pass all frozen runtime and distribution gates with one five-target runtime bundle.
- [ ] Adopt an explicit production launcher/runtime/app/independent-Bus compatibility contract.
- [ ] Automate production supply-chain trust, including platform signing/notarization evidence.
- [ ] Prove immutable install, compatibility, upgrade, rollback and signed RC acceptance.

Live release-asset publication is a separate owner-authorization boundary after these four
technical blockers close. Windows arm64, macOS universal2, older-glibc/musl breadth and
package-manager/automatic-updater integration are deferred unless claimed. See the
[P2b readiness report](docs/tasks/binary-release-readiness-report.md).

## Phase 0: Method Contract and Validation CLI ✅

- [x] Normative development constitution
- [x] Role, Workflow, and Artifact schemas plus semantic validation
- [x] Default roles, staged workflow examples, and handoff templates
- [x] Stateless `validate` and `inspect` CLI
- [x] Tests and CI

The CLI validates contracts only. Earlier ports, adapters, Policy/Event/BindingProfile schemas, and
control-plane runtime concepts were removed. The core is not a Workflow Engine.

## Phase 1: Product Positioning and Repository Truth ✅

- [x] Define high-value-model capacity isolation as the downstream objective
- [x] Separate infrastructure-development and downstream-operation modes
- [x] Define normal-path, escalation, deterministic-rework, and Reviewer authority semantics
- [x] Define Repository Truth, Run Context, TaskCard, and AI Memory boundaries
- [x] Classify current branches, PRs, operations evidence, and incomplete links
- [x] Add product-positioning ADR and measurable product metrics
- [x] Merge the positioning PR and freeze reviewer routing from the resulting `main`

## Phase 2: Close the Proven Operations Gap 📋

The non-core operations surface has already demonstrated:

- exact dispatched-commit checkout;
- model credential/stdin isolation;
- required ImplementationReport and trusted postflight gates;
- allowed-path, secret, and diff checks;
- commit/push plus refreshed remote-SHA proof;
- durable handler lifecycle evidence;
- a real Windows no-code handler-return followed by success-gated Agent Bus ACK;
- structured `PASS`, deterministic `REQUEST_CHANGES`, and `BLOCKED` ReviewReport validation and
  fail-closed verdict routing at the deterministic-test level;
- a dedicated default-locale postflight environment boundary plus a trusted Windows Python 3.12
  portability closeout.

PR #12 closed the placeholder-reviewer gap: tool exit zero is no longer treated as a verdict, and
exactly one validated semantic route is selected before the review event can be acknowledged. PR
#13 and PR #14 then closed the default-locale verification prerequisite and full Windows Python
3.12 portability gate. Those claims are backed by deterministic tests and preserved implementation
reports. The 2026-07-26 v5 acceptance then completed one fresh uninterrupted Mac architect →
Windows coder → Mac reviewer → architect `PASS` route with exact remote-SHA proof, durable handler
evidence, ACKed events 94–96, retry count zero, and no last error.

Completed engineering gates:

- [x] Freeze [`docs/tasks/reviewer-verdict-routing.md`](docs/tasks/reviewer-verdict-routing.md)
  against the merged positioning baseline.
- [x] Implement and deterministically test `PASS`, `REQUEST_CHANGES`, and `BLOCKED` routing.
- [x] Verify invalid reports and send failures keep the current review event unacknowledged.
- [x] Prove the verification child boundary with `PYTHONUTF8` absent on Windows Python 3.12.
- [x] Close the full Windows Python 3.12 portability suite and trusted postflight gate.
- [x] Complete one fresh isolated cross-machine semantic `PASS` route through architect ACK.
- [x] Fail closed before dispatch when the TaskCard branch cannot be pushed for remote checkout.
- [x] Verify Windows credential ACLs without treating the target path as a broad `Users` grant.
- [x] Keep configured private Agent Bus traffic out of inherited HTTP proxy routes.
- [x] Isolate ordinary OpenCode Git writes in no-remote event workspaces and keep trusted-runner
  ownership of imported commits and pushes.
- [x] Persist a versioned external run ledger and bounded recovery context packet.
- [x] Gate route coverage, TaskCard stage, attempt/rework budget, replay identity, and terminal
  state before any model process starts.
- [x] Encode reversible diagnostic/endpoint/listener authority while retaining hard stops for
  credentials, destructive actions, historical events, ACK/requeue/redispatch, and trust bypass.
- [x] Add trusted ReviewReport envelope normalization, bounded `artifact_invalid` diagnosis,
  owner-only RunManifest setup/dispatch, and the thin serial `run/status/resume` operator menu.
- [x] Separate read-only upstream and writable contribution-fork remotes; bind reviewer and outbox
  replay to one exact verified PR provenance tuple.
- [x] Prove the post-merge fork publication path on a contributor Windows machine and exact
  persisted PR-head review on Mac; retain fail-closed behavior when GitHub PR visibility lags.
- [x] Recover retained same-delivery coder and reviewer events from durable checkpoints without
  repeating either completed model subprocess; complete PASS routing and architect ACK.
- [x] Bind effective listener `tool`/`model` selection to the integrity-hashed identity of existing
  v1-v3 deliveries before control-plane authorization or any ACK-sensitive recovery/execution step,
  while preserving legacy direct-entry overrides.
- [x] Make Fast model-tool readiness role-scoped: only a non-model architect runtime may declare
  `not-applicable`; coder/reviewer still require a real version-only probe, and the resulting
  role/policy or tool/version facts are bound into the Deep fingerprint.
- [x] Add a reviewer-only Pi adapter with read-only tools, trusted stdout-to-ReviewReport
  persistence, selection-integrity, and same-delivery recovery gates; keep coder support and a
  generic provider registry out of scope.
- [x] Freeze independent coder/reviewer selections in the owner RunManifest and exact committed
  TaskCard; route OpenCode-to-Pi review and Pi-to-OpenCode deterministic rework without changing
  the v3 payload schema or weakening pre-model selection-integrity.
- [x] Preserve one coder-owned no-remote workspace across trusted implementation and one authorized
  v3 rework; bind expected commit/tree evolution separately from immutable delivery identity and
  require exact same-run ledger/checkpoint/PR/Git lineage before the rework provider starts.

Remaining Phase 2 work:

- [x] Complete the five-target CI-only binary distribution feasibility matrix and publish a
  measured Go/No-Go report. This does not create a production ABI, installer, signing pipeline, or
  release commitment. The 15-cell result is `NO_GO_PRODUCTION_BINARY`: no candidate preserved the
  installed-Python interpreter re-entry contract on every target.

- [x] Replace shell/Git-Bash `dispatch.env` sourcing with one strict cross-platform Python
  configuration loader shared by listener, dispatch, bootstrap, and service entry points. No
  PowerShell dependency, credential output, interpolation, or permissive parsing is allowed. See
  [`docs/tasks/config-recovery-maturity-implementation-report.md`](docs/tasks/config-recovery-maturity-implementation-report.md).
- [x] Exercise coder and reviewer recovery with an automated same-delivery fault matrix across
  model/process, artifact/tree, commit, fork, PR, and prepared/attempting/ambiguous/sent outbox
  boundaries. Supported reviewer model paths preserve zero additional invocations after
  `model_started`.
- [x] Add a no-model architect terminal consumer for validated ready/blocked decisions so terminal
  ACK and pending-empty do not depend on a manual handler.
- [x] Isolate architect terminal verification from shared source checkouts; gate listeners on
  role/repository ownership and readiness before Bus connection; make local interrupt exit cleanly.
- [x] Package production operations modules, adapters, guards, service assets, and templates in the
  wheel; verify a fresh installed tree outside the source checkout on all three CI platforms.
- [x] Add one credential-free, cross-platform role profile and the thin installed-wheel
  `awf node doctor/start/status/stop/logs` local user-process surface without adding a scheduler,
  provider registry, GUI, or new Agent Bus responsibility.
- [x] Separate session-bound and native-service node lifecycles; fail closed for remote session
  starts, supervise one profile-derived foreground listener, and keep transport/ACK recovery out of
  the user-managed adapter. Real Windows post-SSH session A/B acceptance remains an external release gate.
- [x] Aggregate listener, workspace, checkpoint, queue, artifact, PR, and CI facts in a read-only
  node status snapshot; distinguish ReviewReport raw `file_sha256` from normalized
  `canonical_report_sha256` and label unknown facts without inference.
- [x] Project those facts into a payload-blind causal run explanation with first blocker, owner,
  model-invocation evidence and one legal next action; keep Feedback delivery state independent
  from business terminal/ACK state.
- [x] Compose the stable contracts behind a thin beginner facade: generated durable profiles,
  default RunManifest/run-contract discovery, causal doctor/status, explicit install-on-start,
  payload-blind run check, and queue-empty drain, while preserving every low-level command.
- [x] Add a credential-free `awf node doctor --json` discovery snapshot so one remote command can
  replace repeated host/path/tool readiness probes across a short serial run, without creating a
  second authority cache or adding Agent Bus runtime semantics.
- [x] Replace the production Bash TaskCard dispatcher with a native Python entry point; retain the
  shell file only as a POSIX compatibility shim and remove Git Bash/WSL from Windows dispatch.
- [x] Record the delivery-scope capacity-isolation metrics available for the accepted live run,
  using the definitions in [`docs/product-metrics.md`](docs/product-metrics.md).
- [x] Complete the first non-infrastructure downstream multi-TaskCard dogfood described in Phase 3.
- [x] Complete the Agent Bus portion of the fresh disposable proof through coder, reviewer, PASS
  decision, and architect ACK without creating a replacement proof event.
- [x] Pin Workflow `awf.handler-argv.v1` to Agent Bus `agent-bus.listen.on-argv.v1` and keep role,
  rework, terminal and Preflight handler inputs structured across the transport process boundary.

This Phase changes the operations surface only. It does not promote runner/listener behavior into
the stable core or modify Agent Bus protocol.

## Phase 3: First Downstream Capacity-Isolation Dogfood ✅ Operational Gate

Select a real downstream software project, not Agent Workflow or its supporting infrastructure.
Create one PhasePlan that can drive multiple bounded TaskCards and compare it with the project's
previous high-value-model-led baseline.

First-run suggestions (adjustable evidence targets, not permanent product contracts):

- [x] Complete at least three real TaskCards.
- [x] Complete at least two without a high-value-model invocation inside their business delivery
  handlers.
- [x] Keep the observed normal `PASS` chains high-value-model-free inside the business delivery
  handlers. No `REQUEST_CHANGES` path was needed in this phase.
- [x] Record every high-value-model invocation inside the business delivery handlers with project,
  TaskCard, role, path class, and reason
  code.
- [x] Allow high-value escalation for genuine `BLOCKED`, architecture reopen, predefined high risk,
  insufficient evidence, or Milestone acceptance.
- [ ] Compare high-value invocations per completed TaskCard and human intervention with the prior
  baseline.

The 2026-08-09 Dousansi phase completed three serial cards with three OpenCode coder calls, three Pi
reviewer calls, zero deterministic rework, zero business-delivery escalation, and zero manual
ACK/requeue/redispatch. The deterministic architect terminal consumer made no model call. Planning,
infrastructure diagnosis, and milestone acceptance outside the delivery handlers were not
instrumented as a comparable call count, so exact token/cost savings and the prior-baseline ratio
remain unclaimed. See the
[acceptance report](docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md).

Do not claim success from total-token reduction alone, and do not require precise provider token,
price, or quota APIs. See [`docs/product-metrics.md`](docs/product-metrics.md).

## Phase 4: Evidence-Driven Helpers 📋

- [ ] Fix only failures or repeated manual burden observed in the downstream run.
- [ ] Repeat a second bounded downstream Phase before generalizing behavior.
- [ ] Add only method-specific, inspectable helpers proven necessary by the runs.
- [ ] Re-evaluate whether any operations convenience belongs in this repository.

## Later: External Runtime Composition

An external runtime may eventually compose Agent Workflow, Agent Bus, and AI Memory. Until the
preceding gates pass:

- no Agent Host architecture or integration;
- no formal Plugin SDK;
- no provider-specific model runner in the core;
- no generic scheduling, arbitrary DAG, database, dashboard, or SaaS surface;
- no Agent Bus or AI Memory protocol redesign for Workflow convenience.

Boundary notes live in [`docs/later/`](docs/later/).
