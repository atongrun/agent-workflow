# Roadmap

## Product Gates

1. **Use first, abstract second.** A requirement enters the stable core only after real use proves
   it belongs there.
2. **Engineering feasibility is not product value.** Cross-machine dispatch and ACK prove transport
   boundaries. Downstream value requires evidence that frequent high-value-model participation was
   replaced by a lower-cost execution/review chain without losing completion quality.

Before UI, a generic engine, arbitrary DAGs, Plugin SDK, Agent Host integration, or broad runtime
automation, complete one downstream Phase that records model role, invocation class, escalation
reason, deterministic rework, human intervention, and TaskCard completion.

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
- [ ] Compare Python simplification, storage and any native candidate on the same no-model slice;
  make language/store/Coordinator/product-boundary decisions only at the later owner gate.

Current last passed TaskCard gate is RTS-022A. PR #104 preserves all 14 Candidate rows across five
native Rust targets with zero dependencies and `python_invoked=false`; its strict aggregate returned
`RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE`. Pre-closeout head `3be3263` passed ordinary CI run
`32322178827` and Binary Feasibility run `32322178851`. The 3,471-line numerator exceeds the frozen
threshold, so the separately frozen RTS-022B maintainer-fault gate is mandatory before RTS-024. No
Store, language, Coordinator, production default, migration, release or destructive action is
authorized. See the
[development plan](docs/plans/runtime-v2-development-plan.md) and
[RTS-022A closeout](docs/tasks/runtime-v2-rts-022-rust-shared-slice-implementation-report.md).

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
