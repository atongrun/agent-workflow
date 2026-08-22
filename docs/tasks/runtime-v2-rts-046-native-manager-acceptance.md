# TaskCard: RTS-046 Fresh Native-Manager Acceptance

## Task ID

runtime-v2-rts-046-native-manager-acceptance

## Goal

Complete the remaining Runtime v2 Phase 4B evidence with one fresh, no-model, no-business-event
acceptance of the existing lifecycle API on real macOS launchd, Linux systemd-user and Windows Task
Scheduler managers. Preserve exact installed/profile/process/incarnation identity and record the
Windows owner-authorization boundary honestly.

This TaskCard validates existing behavior. It adds no Runtime, lifecycle abstraction, Agent Bus
feature, onboarding system, Agent Host, Finding workflow, distribution candidate or production
default.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Candidate base**: `3cc5e5f14c179f7ba10a24f42c4b90e01094a663`
- **Task branch**: `codex/runtime-v2-rts-046-native-manager-acceptance`
- **Acceptance scope**: `rts046-live-20260822-01`
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`, lifecycle/process section
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4B
- **Prerequisite**: RTS-044 local conformance and RTS-045 exact-identity repair are `PASS`

Agent Bus is an already available, independently versioned communication dependency. RTS-046 may
use an existing credential/config binding solely to let a fresh lifecycle listener connect on one
unique empty control route. It must not install, upgrade, configure or absorb Agent Bus.

## Acceptance environments

Use one exact candidate checkout/installed app and fresh, disposable, credential-safe profile,
state, log and native-manager identities per host:

- current macOS user session: native launchd user LaunchAgent;
- one existing Linux user host: native lingering systemd-user service;
- one existing Windows interactive-console user host: native Task Scheduler `InteractiveToken`
  task.

Every profile uses `role=architect`, `tool=none`, no model and a unique route under the acceptance
scope. The repository checkout is clean and exact candidate. State/log/config references remain
outside the repository. No event is created or consumed.

## Required real actions

### macOS

```text
doctor -> install -> start -> status -> logs -> restart -> status -> exact stop -> uninstall
```

Record manager definition/install-record identity, desired generation, process/lease/launch identity,
live observation and exact post-stop/uninstall absence.

### Linux

Use the same complete sequence on native systemd-user. `doctor` must confirm existing linger; RTS-046
must not enable linger or modify login/security policy. Restart must produce a new exact launch
identity and status must converge to running before exact stop/uninstall.

### Windows

Use the same complete sequence on native Task Scheduler. Record deterministic task identity,
definition/install record, process creation FILETIME, process/lease/launch identity and exact stop.
Prove start in SSH session A survives its complete exit and is observed from fresh session B. Prove
restart creates a new exact launch identity while preserving the selected profile/state contract.

Logout/login or reboot recovery is a separate owner-authorization boundary inside this acceptance.
It may run only in an explicitly scheduled owner window. Without that window, stop before the
disruptive action, preserve all completed evidence and report `BLOCKED_BY_OWNER_AUTHORIZATION`.

## Identity and safety gates

Before every native mutation:

- resolve exact profile, installed snapshot/registry, install record and native definition;
- require candidate/application executable and definition digests to match the record;
- for live stop/restart require exact process record, canonical state-root binding, launch ID,
  listener lease, live observation and Windows creation identity where applicable;
- reject and preserve evidence on any mismatch; do not force kill, scan by process name, weaken
  identity, rewrite records or repair from another record.

After clean completion, enumerate the exact disposable paths/manager target and remove only those
targets through the normal `stop`/`uninstall` contract. Do not delete shared configuration, Agent Bus
state, historical evidence or unrelated manager definitions.

## Writable repository scope

- `docs/tasks/runtime-v2-rts-046-native-manager-acceptance.md`
- `.awf/artifacts/impl-report-runtime-v2-rts-046-native-manager-acceptance.md`
- `.awf/artifacts/review-report-runtime-v2-rts-046-native-manager-acceptance.md`

After all required evidence and independent Review, closeout may additionally update:

- `docs/tasks/runtime-v2-rts-046-native-manager-acceptance-report.md`
- `docs/plans/runtime-v2-development-plan.md`
- `HANDOFF.md`
- `ROADMAP.md`

## Prohibited actions

- Any edit under `src/`, `scripts/`, `tests/`, schemas, workflows, packaging, dependencies or CI.
- New AgentInstallation abstraction, lifecycle API, record/Store, daemon, scheduler, Agent Host,
  plugin framework, onboarding system or generic extension point.
- Agent Bus installation/configuration/upgrade; event send/read/ACK/retry/requeue/recover/dispatch;
  queue/history/payload inspection; model or business handler execution.
- Runtime Core, transport, RunStore, provider, workspace/Git, Artifact, Finding Phase B/triage/GitHub
  publication, launcher, distribution, default, migration, release or production-state change.
- System security/login-policy modification, linger enablement, credential disclosure, manual record
  editing, process-name/PID-only signaling or simulated logout/login evidence.
- Logout/login, reboot or equivalent session disruption without explicit owner authorization.

## Acceptance criteria

- [ ] Task ID equals branch leaf; repository changes remain documentation/evidence only and in scope.
- [ ] Every host proves exact candidate/application/profile/manager-definition identity before start.
- [ ] macOS launchd completes the full real action sequence with correct running/restart/stop facts.
- [ ] Linux systemd-user completes the full sequence, including a new exact restart incarnation.
- [ ] Windows Task Scheduler completes install/start/status/logs/restart/status/exact-stop/uninstall,
      and session-B evidence proves the session-A listener survived SSH exit.
- [x] Windows logout/login evidence is either real and owner-authorized or explicitly remains
      `BLOCKED_BY_OWNER_AUTHORIZATION`; it is never simulated or inferred.
- [x] All stops are exact-bound; PID/name/liveness/desired state alone never authorizes signaling.
- [x] No Agent Bus business event, payload, ACK/retry/requeue or model invocation occurs.
- [x] Normal `run/status/stop` boundaries and optional Finding separation remain unchanged.
- [x] Credential/private-path-safe evidence records environments, commands, observations, limits and
      exact cleanup state without publishing secrets or private endpoints.
- [x] Independent Gate Review returns `PASS` only if every Phase 4B criterion is proved; otherwise it
      returns the exact blocked status without weakening the contract.
- [x] Phase 5 is not started under any outcome.

## Failure handling

- Pre-start setup/manager failure: diagnose and repair only disposable environment facts; do not
  weaken identity or change product code.
- Post-start identity/stop ambiguity: preserve evidence, do not use a stronger kill primitive or
  manual record repair; report `EXTERNAL_BLOCKED`.
- Missing Windows owner window: complete safe non-disruptive legs, stop
  `BLOCKED_BY_OWNER_AUTHORIZATION`, update HANDOFF/ROADMAP/plan/report, and await authorization.
- Frozen contract or architecture conflict: stop for owner/ADR; do not implement around it.

## Required output

- one credential-safe acceptance report with scope, environment, commands, observations,
  cleanup/retention and limitations;
- one independent Gate ReviewReport;
- aligned HANDOFF, ROADMAP and plan status;
- Phase 4B `PASS` only with genuine Windows login evidence, otherwise preserved owner block.

## Owner-authorized client-skew continuation

After scopes `-01` and `-02` were preserved as failures, the owner independently verified and
authorized a client-only compatibility continuation:

- **Fresh acceptance scope**: `rts046-live-20260822-03`
- **Agent Bus repository**: `atongrun/agent-bus`, default branch `master`
- **Exact compatible source**: `6ca8f2812be0286607bbbe3f14cc51783637b0b5`
- **Producer contract**: `awf.handler-argv.v1`
- **Consumer contract**: `agent-bus.listen.on-argv.v1`

The compatible client must be installed into new isolated macOS and Windows environments. Existing
client installations, server code/deployment/database, endpoint/token values, retained events,
queues and ACK state are read-only. The disposable acceptance profiles must bind the exact isolated
client executable and prove `--on-argv` before manager start. No legacy `--on` fallback exists.

Agent Bus master still declares project version 0.3.0 while the formal v0.3.0 tag lacks this
contract, so capability plus exact source/module provenance is required. A small formal client
release is a later productization item; RTS-046 does not publish one.

Linux and Windows logout/login boundaries are unchanged. Scope `-03` may proceed through compatible
client setup and non-disruptive manager actions, but may not enable Linux linger or trigger Windows
logout/login without their existing prerequisites/owner window.
