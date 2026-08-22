# RTS-046 Native-Manager Acceptance ImplementationReport

## Final status

`PASS`. macOS launchd, Linux systemd-user, Windows Task Scheduler and fresh `-05` real logout/login
acceptance pass. Final independent closeout review returned `PASS` with zero blocking findings.
RTS-046 and Phase 4B are complete. Phase 5 did not start.

No model, business event, provider, Runtime Core, Agent Bus server/state/credential mutation or
Finding workflow occurred. Only owner-authorized isolated Agent Bus client installations were added.

## Entry audit

- macOS: current candidate installed into a fresh Python 3.12 venv; existing Agent Bus configuration
  passed credential-safe doctor; launchd GUI domain was available; profile was uninstalled/current
  state stopped before mutation.
- Windows: Python 3.12, Git, Agent Bus, AWF config and Task Scheduler were present; the SSH identity
  matched the active console user. No manager mutation was performed because the exact candidate
  failed on macOS first.
- Linux: every reachable audited host had systemd-user running but existing linger was absent or
  unavailable; no host had an existing AWF config. RTS-046 prohibits enabling linger or creating an
  Agent Bus deployment/config, so Linux stopped before install.

## macOS scope and observed failure

- Scope: `rts046-live-20260822-01`
- Fresh source profile: role `architect`, tool `none`, unique empty control route, fresh state/log
  roots and unique LaunchAgent label.
- `awf node doctor --json`: configured/connected true, model not applicable, installed/running false,
  next action `install`.
- `awf node install`: success; deterministic launchd definition and installed record were current.
- `awf node start`: fail-closed after the bounded listener-lease wait. No process record or lease was
  created.
- Factual status reported installation current, lifecycle running false, zero delivery checkpoints,
  no run/model/terminal facts and exact candidate workspace clean. The normal status projection also
  observed a payload-blind pending count of zero; no explicit queue/history/payload command was run.
- Exact listener log repeated one pre-listener error:
  `ModuleNotFoundError: No module named 'agent_workflow'` while the manager invoked the base Python.

## Root cause

The acceptance app was installed in a fresh venv. Native definition and install-record code uses
`Path(sys.executable).resolve()`. On POSIX, the venv interpreter is a symlink, so this resolves to
the Homebrew base Python path. Agent Workflow is installed only in the venv; launchd therefore
cannot import `agent_workflow.cli` and exits before process/incarnation evidence or Bus listener
entry.

This is a local L3 executable-identity/lifecycle defect, not a launchd, Agent Bus, credential,
business-event or product-boundary failure. Bypassing it with source `PYTHONPATH`, installing the app
into the base interpreter or manually editing the manager definition would manufacture acceptance
and was not attempted.

## Safe cleanup and retained evidence

Because no process record or lease existed, normal exact `awf node uninstall` was used. It removed
only the unique LaunchAgent definition, install record and registries. Post-uninstall checks proved:

- definition absent;
- install record absent;
- process record absent;
- listener lease absent;
- desired-state evidence retained; and
- credential-safe listener log retained.

No stronger kill, PID scan, manual record edit or shared configuration deletion occurred.

## Bounded repair and fresh continuation

RTS-047 preserved the absolute venv interpreter path without resolving its symlink, retained
executable hashing/exact action argv, covered all three renderer formats, passed independent L3
Review, full local tests and exact-head cross-platform CI.

Historical failed macOS scope remains failure evidence and cannot contribute to PASS.

## Fresh scope `rts046-live-20260822-02`

A new venv, profile, route, state/log roots, installed snapshot and LaunchAgent identity were created
after RTS-047 PASS. Doctor again proved configured/connected with no model and no installed/running
state. Install and start reached the installed AWF listener, confirming native venv re-entry.

The listener then exited before creating durable process/lease acceptance because the independently
installed Agent Bus CLI rejected structured `--on-argv` as unsupported and offered only legacy
`--on`. Fallback was forbidden: legacy shell handler syntax would weaken the accepted structured argv
boundary. Factual status showed installed current, running false, no run/checkpoint/model/terminal
facts, clean exact candidate and a payload-blind pending count of zero. No explicit queue/history or
payload command was run.

Normal exact uninstall removed only the unique `-02` definition, install record and registries.
Definition/install/process/lease absence passed; the credential-safe listener log remains retained.

## Windows pre-mutation result

Read-only entry checks proved Python 3.12, Git, AWF config, Agent Bus, running Task Scheduler and an
SSH identity equal to the active interactive-console user. A direct capability check then proved the
installed Agent Bus supports `--ack-on-receive` but not `--on-argv`. No Task Scheduler definition,
profile, state, process, lease or event was created. Windows post-SSH/restart/stop therefore did not
begin, and logout/login remains `BLOCKED_BY_OWNER_AUTHORIZATION`.

## Linux pre-mutation result

Multiple reachable existing Linux user hosts were audited without modification. Suitable Python
hosts had systemd-user running, but none had existing linger enabled and none had an existing AWF
configuration/Agent Bus client binding. One configured host was unavailable. The frozen TaskCard
forbids enabling linger or deploying/configuring Agent Bus, so no checkout, profile, service,
process, lease or event was created.

## Intermediate failure classification and next action

- macOS/Windows initial blocker: resolved as isolated client installation skew, without changing the
  server or existing clients;
- Linux: external prerequisite absent (existing linger and AWF/Bus configuration);
- Windows login: explicit owner-authorization window absent.

At that intermediate point, Agent Workflow did not replace or auto-deploy Agent Bus. The legal next
action was an
already-lingering/configured Linux user host plus a scheduled Windows logout/login window. No Phase 5
work is authorized.

## Owner-authorized client provenance

Local re-verification confirmed Agent Bus PR #27 merged to master commit
`6ca8f2812be0286607bbbe3f14cc51783637b0b5`. That commit implements producer
`awf.handler-argv.v1` / consumer `agent-bus.listen.on-argv.v1`; formal tag v0.3.0 lacks `--on-argv`,
while master still declares version 0.3.0.

- macOS stale client: editable source commit `6b3955d172d1d1709998af3b93205a40f2803b3a`,
  module SHA-256 `492431ab...`, `--on-argv=false`.
- Windows stale client: formal isolated v0.3.0 installation, non-editable module SHA-256
  `95b7ad4a...`, `--on-argv=false`.
- macOS compatible client: fresh isolated venv built from exact `6ca8f281...`; installed module
  SHA-256 `0b2d9a6d...` exactly matched the Git blob; `--on-argv=true`.
- Windows compatible client: fresh isolated venv and clean detached source checkout at exact
  `6ca8f281...`; `--on-argv=true`.

Existing client paths and official configuration remained unchanged. Each acceptance used an
owner-only isolated config copy whose endpoint/token values were preserved and whose only changed
value bound `AWF_BUS_BIN` to the exact compatible client.

## Fresh scope `rts046-live-20260822-03`

### macOS launchd PASS

A third fresh venv/profile/route/state/log/LaunchAgent identity used the exact compatible client.
Capability was verified before manager start. The sequence
`doctor -> install -> start -> status -> logs -> restart -> status -> exact stop -> uninstall`
completed.

- initial running incarnation: process and lease launch IDs matched; canonical state-root bindings
  matched; definition bytes matched the install-record digest; desired state was `running`,
  generation 2;
- restart: generation advanced to 4 and produced a distinct launch ID with matching process/lease
  and the same profile/state-root/definition identity;
- exact stop: process record and lease became absent;
- uninstall: unique LaunchAgent definition and install record became absent.

No handler/model/business event ran. The normal factual status projection observed only a
payload-blind pending count of zero.

### Windows Task Scheduler non-disruptive PASS

Windows used a separate fresh compatible client source/venv, exact Workflow checkout/venv,
owner-only config copy, profile/state/log and Task Scheduler identity. A pre-start PowerShell UTF-8
BOM fixture issue was corrected before doctor; a read-only absent-task probe also produced a local
shell error before doctor. Neither created manager state or changed identity.

SSH session A then completed `doctor -> install -> start` and exited. Fresh session B proved the
listener remained running with exact process/lease launch ID, state-root binding, definition digest,
live process and recorded Windows creation FILETIME. Logs contained listening/connected markers and
no error. Restart produced a distinct launch ID, generation 4, new live exact incarnation and
creation identity. Exact stop/uninstall then proved process, lease, task definition, install record
and scheduled task absent; desired state was stopped at generation 5 and the credential-safe log was
retained.

Logout/login was not attempted and remains `BLOCKED_BY_OWNER_AUTHORIZATION`.

## Agent Bus productization follow-up

Capability/commit probing is sufficient for this acceptance but not a desirable Phase 5 operator
contract. Before Phase 5, consider a small formal Agent Bus client release (likely v0.3.1) that
contains `agent-bus.listen.on-argv.v1` and exposes an unambiguous version. RTS-046 does not publish or
authorize that release.

## Owner-authorized final scope `rts046-live-20260822-04`

### Invalidated Linux assumption

The prior `la-codex-node` subsection is withdrawn: the owner confirmed no such real Agent Workflow
host/topology exists. Its claimed host, linger, unit and environment facts are excluded from
acceptance and cannot support Phase 4B. This is a documentation/topology correction, not a Runtime
architecture change. The only valid Linux evidence is fresh `tx-vps` scope `-06` below.

### Windows pre-logout evidence

Fresh Windows `-04` used a new exact Workflow checkout/venv/config/profile/state/task identity and
the already-proved isolated compatible Bus client. Doctor/install/start passed. Immediately before
logout, fresh read-only evidence recorded:

- profile SHA-256 `bc10e72d...`;
- process and lease launch ID `35c23c3be55a4934a9c975c6295af9c8`;
- matching canonical state-root identity;
- live exact process with creation FILETIME `134318435738857477`;
- desired `running`, generation 2;
- current Task Scheduler manager/definition digest;
- listening/connected log markers with no error;
- exactly one RTS-046 acceptance task, old `-03` absent; and
- interactive console session ID 1 matched the current principal.

No unrelated process/service action occurred. This evidence was committed before the authorized
logout. The next action is the single owner-authorized logout of interactive session 1; connection
loss is expected and not failure. After the owner logs back in, inspect the same `-04` identity,
then exact stop/uninstall.

The system did not provide `logoff.exe`; the first command therefore failed before session mutation.
After revalidating the same profile/launch/lease/state-root/creation/session identity, the native
`WTSLogoffSession(sessionId=1)` API returned success. This records logout dispatch only, not login
continuity. Current status is `WAITING_FOR_OWNER_LOGIN`; do not create or replace the `-04` identity.

### Windows post-login failure

After the owner completed normal interactive login, the same `-04` identity remained installed with
desired `running`, generation 2 and the exact definition/profile/state binding. Console session
changed legitimately from 1 to 2. The old process/lease record remained internally consistent but
its process was dead; status correctly reported `stale` and did not authorize it as running.

The logon-trigger reconcile ran before networking was ready and exited 1 with only
`Agent Bus health probe failed`. A later doctor from SSH passed, proving the readiness failure was
transient. The existing periodic Task Scheduler triggers nevertheless did not create a new
incarnation during two bounded observation windows; LastRun remained the logon attempt, result 1 and
missed-run count increased.

The old recorded PID was then reused by an unrelated process. Live creation FILETIME
`134318441283700333` did not match recorded `134318435738857477`; exact status remained stale. A
normal `awf node stop` wrote desired `stopped`, generation 3, then failed closed before signal with
`managed stop refused an unbound live listener`. No PID/task signal, record edit, restart or uninstall
occurred. Task/record/lease/log/install evidence remains preserved.

This is a new L3 lifecycle defect: post-login transient readiness plus PID reuse leaves no safe
automatic reconcile or exact-stop cleanup convergence. Freeze a bounded repair before any new
acceptance identity.

RTS-048 implemented bounded pre-listener readiness retry and strict creation-aware stale cleanup,
passed independent L3 re-review, 884 local tests, ordinary CI `32551160937` and Binary Feasibility
`32551160941`. Reviewed code then cleaned failed `-04` through normal stop/uninstall: process/lease/
definition/install/task are absent; desired/log evidence remains; no PID signal occurred.

The owner later authorized one new logout only after a mandatory RustDesk recovery preflight.
Read-only evidence at exact HEAD `06f075d737d5cdb77e9630bf8f4fc601793ef266` showed the Windows
`RustDesk` service present, `Running`, `Auto` and backed by a Session 0 process. The Windows desktop
was already locked. RustDesk was intentionally disconnected and reconnected from the Mac, then
successfully controlled the secure screen from the clock page into the PIN prompt.

The executor did not have an authorized Windows PIN/login credential, so it could not unlock the
existing session and verify recovered normal desktop control. This mandatory preflight therefore
stopped as `WAITING_FOR_OWNER_PHYSICAL_ACCESS`. RustDesk was disconnected; fresh `-05` was not
created, no logout occurred, and no Clash/Agent Bus post-unlock network check or lifecycle mutation
started. No RustDesk, security, firewall, Agent Bus or Runtime configuration changed.

## Fresh Windows `-05` pre-logout evidence

The owner accepted the existing RustDesk recovery evidence and authorized one fresh logout/login
without another preflight. Scope `rts046-live-20260822-05` created only a new `%TEMP%` root, exact
clean reviewed Workflow source `59123f2`, fresh venv/config/profile/state/log and Task Scheduler
identity. It reused only the already-proved isolated compatible Agent Bus client at exact source
`6ca8f281...`; `--on-argv` passed before install/start. `-04` remained untouched.

The fresh config copy initially failed strict doctor because its ACL was inherited. Only the new
copy was hardened to an explicit current-user ACL; doctor then passed configured/connected and
model-not-applicable with no model invocation. Install/start produced one exact running identity:

- profile digest `3ea4f074...`, state-root digest `99e48a63...`, definition digest `84629451...`;
- process/lease PID `11028`, launch ID `55bf5a080cb742568f340746f49cd4aa` and matching root/profile/repo;
- recorded/live creation FILETIME `134318495073804833` exact;
- desired running generation 2, current installation and running observation;
- one Interactive root Scheduled Task with two triggers; and
- 13 credential-safe log lines, seven listen/connect markers and zero errors.

Installer and active console user matched in session 2. No event, provider, model, ACK/retry/requeue
or Phase 5 action occurred. The scope is `READY_FOR_AUTHORIZED_LOGOUT` and may advance only through
the one authorized native session-2 logout.

## Fresh Windows `-05` logout/login PASS

The exact pre-logout identity was revalidated, and native `WTSLogoffSession` returned success only
for active console session 2. RustDesk reached the real sign-in screen; the owner-authorized PIN
completed normal interactive login and desktop control, advancing the console to session 3. The PIN
was not persisted or included in evidence. No second logout or reboot occurred.

The existing `-05` logon trigger converged without a manual restart or record edit. Old PID `11028`
was absent. New process/lease PID `17492`, launch `2a7293c12e3d4c93a79b25677386c194`, creation
FILETIME `134318498467181730`, profile and state-root identity all matched live facts. Status was
current/running and a fresh doctor passed Agent Bus health. The existing Clash service remained
running in Session 0. The log had zero reconcile, Bus-readiness or other errors. No transient Bus
failure happened during this login, so the fault was not manufactured; RTS-048 reviewed tests/CI
remain the causal retry/PID-reuse proof while this scope supplies the real boundary acceptance.

Normal exact stop removed the bound process/lease and wrote stopped generation 3. Normal uninstall
removed definition, install record, Scheduled Task and installed-profile registry references. No
RTS-046 task remains. Source profile, strict disposable config, desired/log and the immutable but
unreferenced snapshot remain as evidence. `-04` remains failed forever and untouched.

Windows login acceptance is `PASS`. Phase 5 did not start.

## Fresh Linux `-06` systemd-user PASS

The owner identified the existing `tx-vps` root account as the only valid Linux host/account. The
systemd-user manager was running; linger baseline was `no`; enabled user-unit count/hash was
6/`5430a5ef...`. Existing system `agent-bus.service` was active/running at PID `2652165`; its start,
unit/env hashes and local health were captured without reading events or database state.

One absent disposable root/profile/route/unit was created. Linger changed only `no -> yes -> no`.
Exact clean Workflow `87ceb3a` and compatible Bus `6ca8f281...` sources were installed into isolated
CPython 3.11 venvs using the existing service base runtime without altering it. The Bus client proved
`--on-argv`. A stalled uv 3.12 seed was exact-cmdline terminated; its current temp was removed during
cleanup. Server env was parsed only in remote memory to write one root-owned `0600` architect config;
no value was displayed, logged or exported.

The first doctor denied the disposable key `AWF_ARCHITECT_TOKEN`; a mechanical rename to current
`AWF_ARCH_TOKEN` fixed only that isolated config. Strict doctor then passed configured/connected,
Agent Bus health, model-not-applicable and no invocation before manager state existed.

The complete existing lifecycle passed:

- install: one exact systemd-user unit/install/snapshot/definition, definition digest `b3ec8262...`;
- first start/status: MainPID/process/lease `1681549`, launch `19375d706ca341bca51e92070aa16bce`,
  current/running and exact profile/repo/state-root;
- logs: existing API returned successfully with zero errors;
- restart/status: old PID absent, new MainPID/process/lease `1682597`, new launch
  `2b2a0d9ef69e455b887faa4441c880e6`, preserved exact identity, generation 4;
- exact stop: complete identity revalidated, process/lease absent, stopped generation 5; and
- uninstall: definition/install/registries disabled/absent; exact volatile unit cache reset to
  not-found.

Cleanup removed the root/config/clients, unreferenced snapshot and acceptance-created uv temp.
Linger returned `no`; enabled units returned to the exact six-unit baseline hash. All disposable
process/lease/definition/install/registry/snapshot/unit/process references were absent. Agent Bus
PID/start/health and unit/env hashes matched baseline exactly. No model, event, ACK/retry/requeue,
provider, server or database operation occurred.

Linux acceptance is `PASS`. All frozen Phase 4B criteria are evidenced and final independent
closeout review passed. Phase 5 is not authorized by this report.
