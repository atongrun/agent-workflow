# RTS-046 Native-Manager Acceptance ImplementationReport

## Final status

`EXTERNAL_BLOCKED` on the Linux prerequisite, with Windows login evidence
`BLOCKED_BY_OWNER_AUTHORIZATION`. macOS launchd and non-disruptive Windows Task Scheduler acceptance
now pass. Phase 4B is not complete.

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

## Failure classification and next action

- macOS/Windows initial blocker: resolved as isolated client installation skew, without changing the
  server or existing clients;
- Linux: external prerequisite absent (existing linger and AWF/Bus configuration);
- Windows login: explicit owner-authorization window absent.

Agent Workflow does not replace or auto-deploy Agent Bus. The legal next action is an
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

### Linux selected-user result

The selected scope was SSH alias `la-codex-node`, principal `root` (`uid=0`), original linger `no`,
eight existing enabled user units, disposable root
`$HOME/.local/share/awf-rts046-linux-r4-20260822`, unit
`awf-node-rts046-linux-systemd-20260822-04.service` and matching fresh profile name. Root, unit and
profile registry were absent before mutation.

Linger was enabled only for this principal. System Python 3.12 lacked ensurepip/pip, so the first
venv creation stopped before manager/config/state. An official `virtualenv.pyz` was then contained
inside the disposable root and created isolated exact Bus/Workflow environments; source heads were
`6ca8f281...` and `5561e4c...`, and Bus capability passed.

The required credential-bearing config copy to this remote root was rejected by the safety approval
boundary because the owner had not explicitly authorized exporting those secret values to this
destination. No workaround was attempted. Before any systemd profile/install/start:

- the validated disposable root (4,006 entries, 10 symlinks) was removed without following links;
- linger was restored to `no`;
- enabled user-unit count remained 8; and
- disposable unit, registry and lifecycle state remained absent.

Linux therefore remains `EXTERNAL_BLOCKED` before manager mutation.

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
