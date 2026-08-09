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

Remaining Phase 2 work:

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
- [x] Aggregate listener, workspace, checkpoint, queue, artifact, PR, and CI facts in a read-only
  node status snapshot; distinguish ReviewReport raw `file_sha256` from normalized
  `canonical_report_sha256` and label unknown facts without inference.
- [x] Add a credential-free `awf node doctor --json` discovery snapshot so one remote command can
  replace repeated host/path/tool readiness probes across a short serial run, without creating a
  second authority cache or adding Agent Bus runtime semantics.
- [x] Replace the production Bash TaskCard dispatcher with a native Python entry point; retain the
  shell file only as a POSIX compatibility shim and remove Git Bash/WSL from Windows dispatch.
- [ ] Record the capacity-isolation metrics defined in
  [`docs/product-metrics.md`](docs/product-metrics.md) for the accepted live run.
- [ ] Complete the first non-infrastructure downstream multi-TaskCard dogfood described in Phase 3.
- [x] Complete the Agent Bus portion of the fresh disposable proof through coder, reviewer, PASS
  decision, and architect ACK without creating a replacement proof event.

This Phase changes the operations surface only. It does not promote runner/listener behavior into
the stable core or modify Agent Bus protocol.

## Phase 3: First Downstream Capacity-Isolation Dogfood 📋 Product Gate

Select a real downstream software project, not Agent Workflow or its supporting infrastructure.
Create one PhasePlan that can drive multiple bounded TaskCards and compare it with the project's
previous high-value-model-led baseline.

First-run suggestions (adjustable evidence targets, not permanent product contracts):

- [ ] Complete at least three real TaskCards.
- [ ] Complete at least two without a high-value-model invocation.
- [ ] Keep normal `PASS` and deterministic `REQUEST_CHANGES` chains high-value-model-free.
- [ ] Record every high-value-model invocation with project, TaskCard, role, path class, and reason
  code.
- [ ] Allow high-value escalation for genuine `BLOCKED`, architecture reopen, predefined high risk,
  insufficient evidence, or Milestone acceptance.
- [ ] Compare high-value invocations per completed TaskCard and human intervention with the prior
  baseline.

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
