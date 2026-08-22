# RTS-046 Fresh Native-Manager Acceptance Report

## Outcome

`PASS`. Fresh macOS launchd, Linux systemd-user and Windows Task Scheduler/login acceptance now
jointly satisfy RTS-046 and the frozen Phase 4B exit criteria. Phase 4B is closed. Phase 5 did not
start and requires a separate owner-approved plan.

Two preserved macOS scopes remain immutable failures. A third fresh scope resolves only the
owner-authorized client-skew prerequisite and passes real macOS plus Windows manager acceptance,
including the real login boundary under `-05`. Owner-corrected Linux scope `-06` is the only valid
Linux acceptance.

## Acceptance scope

| Scope | Environment | Result | Durable meaning |
|---|---|---|---|
| `rts046-live-20260822-01` | macOS arm64, Python 3.12, fresh installed venv, unique launchd profile/state/log/label | failed before listener entry | exposed venv symlink resolution defect; never PASS |
| RTS-047 repair | local/CI five-target evidence | PASS | preserves invoked venv interpreter path; does not itself prove manager acceptance |
| `rts046-live-20260822-02` | macOS arm64, new venv/profile/state/log/label | failed at Agent Bus listener capability | confirms executable repair; never PASS |
| `rts046-live-20260822-03` | exact compatible isolated Bus clients; new macOS and Windows identities | macOS PASS; Windows non-disruptive PASS | only successful manager evidence |
| `rts046-live-20260822-04` | Windows real logout/login | failed post-login recovery; exactly cleaned after repair | never PASS |
| RTS-048 repair | local/CI five-target evidence | PASS | bounded login readiness and creation-aware stale cleanup |
| `rts046-live-20260822-05` | Windows real logout/login with reviewed RTS-048 code | PASS | only successful Windows login acceptance |
| discarded Linux assumption | `la-codex-node` | invalid topology; excluded | owner confirmed no such real host/topology exists |
| `rts046-live-20260822-06` | `tx-vps`, existing root systemd-user, local existing Bus server | PASS | only valid Linux acceptance; full lifecycle and exact cleanup |
| Windows login gate | existing Windows interactive-console user | PASS | one owner-authorized logout, RustDesk login and automatic Task Scheduler convergence |

## Environment and identity rules

- Candidate: exact RTS-047/RTS-048 reviewed, CI-green application; `-06` installed exact clean
  Workflow head `87ceb3a` containing reviewed Runtime code `59123f2`.
- Every macOS scope used a fresh venv, source profile, installed snapshot/registry, state root, log,
  empty control route and deterministic LaunchAgent label.
- Profiles used `role=architect`, `tool=none`; no provider/model was applicable.
- Existing Agent Bus configuration was used only as the unchanged source for isolated owner-only
  copies. Existing Bus installs were not upgraded; only new isolated clients were installed. No
  endpoint/token change or event operation occurred.
- Repository worktree remained clean at the exact acceptance head.

Endpoints, usernames and credentials are deliberately omitted. Exact executable paths are included
only where the owner explicitly required client provenance; other environment identity uses opaque
digests and boolean/payload-blind observations.

## Commands exercised

### macOS `-01`

```text
fresh venv install
awf node doctor --json
awf node install
awf node start
awf node status --json
awf node logs
awf node uninstall
exact definition/install/process/lease absence checks
```

Doctor passed configuration, workspace and Agent Bus health with model not applicable. Start timed
out before a listener lease. Logs proved the native definition invoked the resolved base Python,
which could not import the venv-installed application. Normal uninstall succeeded; definition,
install record, process record and lease were absent afterward, while desired/log evidence remained.

### RTS-047 validation

```text
compileall
focused node/node_service/facade pytest
full pytest
ruff check
ruff format --check
git diff --check
ordinary cross-platform CI
five-target Binary Feasibility
independent L3 review
```

All passed. The failed `-01` scope was not retried or reused.

### macOS `-02`

```text
new venv install
awf node doctor
awf node install
awf node start
awf node status
awf node logs
awf node uninstall
exact definition/install/process/lease absence checks
```

The listener entered installed AWF, proving RTS-047. Agent Bus then rejected `--on-argv` before a
stable listener incarnation. Status remained installed/current but running false, with no
run/checkpoint/model/terminal facts. Its normal read-only projection observed pending count zero;
no direct queue/history/payload command occurred. The exact disposable definition/install/process/
lease state was absent after normal uninstall, and the log was retained.

### Linux and Windows entry checks

Linux commands were limited to OS/Python/Git presence, systemd-user health, existing linger and
existing config/client presence. Windows commands were limited to OS/Python/Git, existing config,
Task Scheduler service, console-user equality and Agent Bus listener-help capability. No manager
install/start/stop/restart/uninstall command ran on either host.

## Resolved Agent Bus client skew

Agent Bus master/PR/tag facts were re-verified locally. Exact master
`6ca8f2812be0286607bbbe3f14cc51783637b0b5` contains producer `awf.handler-argv.v1`, consumer
`agent-bus.listen.on-argv.v1` and `--on-argv`; v0.3.0 does not. Master still reports version 0.3.0.

Credential-free provenance proved the macOS client was an editable install at older source commit
`6b3955d...`, while Windows used a formal non-editable v0.3.0 venv; both lacked the capability.
Owner-authorized fresh isolated client venvs were built from exact `6ca8f281...`. macOS installed
module hash matched the exact Git blob, and both hosts proved `--on-argv` before manager start.
Existing clients, formal config, Bus server/deployment/database, endpoint/token values, events,
queues and ACK state were untouched. Isolated owner-only config copies preserved every value except
their explicit `AWF_BUS_BIN` binding.

| Host/client | Exact executable | Capability | Source/package provenance |
|---|---|---|---|
| macOS stale | `$HOME/AI/01_Project/agent-bus-single-card-20260802/.venv/bin/agent-bus` | `--on-argv=false` | editable source `6b3955d...`; CLI SHA-256 `492431ab...`; version 0.3.0 |
| Windows stale | `%LOCALAPPDATA%\agent-bus\venvs\v0.3.0\Scripts\agent-bus.exe` | `--on-argv=false` | non-editable v0.3.0; CLI SHA-256 `95b7ad4a...` |
| macOS compatible | `/private/tmp/awf-rts046-bus-mac03.KPNsvr/venv/bin/agent-bus` | `--on-argv=true` | exact source `6ca8f281...`; CLI SHA-256 `0b2d9a6d...` equals Git blob |
| Windows compatible | `%TEMP%\awf-rts046-win-r3-bus-20260822\venv\Scripts\agent-bus.exe` | `--on-argv=true` | clean exact source `6ca8f281...`; installed CLI SHA-256 `dd16e118...`; version 0.3.0 |

No legacy `--on` fallback or second implementation was introduced.

## Scope `rts046-live-20260822-03`

### macOS launchd

The fresh exact candidate and compatible client completed:

```text
capability -> doctor -> install -> start -> status -> logs
-> restart -> status -> exact stop -> uninstall
```

The first running incarnation had matching process/lease launch ID and state-root binding, current
definition/install digest and desired generation 2. Restart advanced generation to 4 and produced a
distinct exact launch ID. Stop removed process/lease; uninstall removed the unique definition and
install record. No log error, handler, model or business event occurred.

### Windows Task Scheduler

The fresh Windows scope used exact Agent Bus source/venv and exact Workflow source/venv. Before any
manager mutation, a PowerShell UTF-8 BOM profile fixture was corrected without changing its semantic
identity; a failed read-only missing-task probe also had no side effect.

SSH session A completed doctor/install/start and exited. Session B observed a live listener with
matching process/lease launch ID, canonical state-root identity, current definition digest and
Windows creation FILETIME. Restart advanced desired generation from 2 to 4 and produced a distinct
live exact launch identity. Exact stop/uninstall then left process, lease, task definition, install
record and scheduled task absent; desired state was stopped at generation 5 and the log remained.

No logout/login was attempted.

## Corrected Linux topology

The earlier `la-codex-node` assumption was not real repository/host topology. Its claimed Linux
environment facts are withdrawn and cannot contribute to acceptance. The owner identified the only
valid host as `tx-vps`, where the current root account owns the systemd-user manager and the existing
system `agent-bus.service` remains an external dependency. One OS account hosting multiple Workflow
roles does not collapse role/profile identity.

### Resolved Windows owner window

The Windows identity matched the current interactive-console user. The owner later supplied exactly
one fresh logout/login window; `-05` used it and passed. No second logout, simulation or inferred
login evidence occurred.

## Safety and cleanup

- No model, provider, business handler, TaskCard run, business event, ACK, retry, requeue, recovery or
  dispatch occurred.
- No Agent Bus server/state/credential, Runtime Core, Finding, Agent Host or onboarding setting
  changed. Windows and Linux used isolated client/config copies under explicit authorization.
  Linux linger changed only `no -> yes -> no` for the selected existing account.
- No manual process signal, process-name scan, record edit, PYTHONPATH or base-interpreter install
  was used.
- Both macOS definitions/install records/registries were removed through normal exact uninstall.
- Failed-scope logs and desired-state evidence remain retained in disposable local roots.
- Linux `-06` and every completed Windows manager scope were removed through exact stop/uninstall.
  The Linux disposable root, credential copy, clients, snapshot and volatile failed-unit cache were
  also removed after exact validation; unrelated user units and the Bus Server remained unchanged.

## Limitations and legal next action

RTS-046 proves real launchd, systemd-user and Task Scheduler lifecycle, including distinct restart
incarnations, exact stop/uninstall, Windows SSH-session survival and real logout/login recovery.
Together with RTS-044/045 local conformance and RTS-047/048 repairs, all Phase 4B exit criteria are
satisfied. The next legal action is the separate Phase 5 replanning/owner gate; this closeout does
not authorize Phase 5 implementation, release, default, migration or launcher work.

Before Phase 5, separately consider a small formal Agent Bus client release (likely v0.3.1) so the
structured contract is identified by a release version instead of only commit/capability evidence.
No release is published or authorized by RTS-046.

## Scope `rts046-live-20260822-04`

### Invalidated Linux assumption

The previous Linux subsection was based on the now-corrected `la-codex-node` assumption. The owner
confirmed that no such real host/topology exists. Those claimed host, linger, unit-count, environment
and cleanup facts are withdrawn and excluded from every PASS claim. They did not prove Linux
systemd-user behavior. Valid Linux evidence is only scope `-06` below.

### Windows pre-logout checkpoint

Windows created one new `-04` Workflow/profile/state/Task Scheduler identity using the compatible
isolated Bus client. Doctor/install/start passed. Before logout, the listener was running with:

- profile SHA-256 `bc10e72d...`;
- identical process/lease launch ID `35c23c3be55a4934a9c975c6295af9c8`;
- matching state-root binding and current definition digest;
- recorded creation FILETIME and live exact process;
- desired `running`, generation 2;
- listening/connected log markers and no error; and
- one acceptance task, old `-03` absent, console session ID 1 exact.

This checkpoint precedes the single owner-authorized logout. After manual login, the same `-04`
identity must supply continuity/recovery evidence before exact stop/uninstall. No reboot is
authorized.

The system had no `logoff.exe`, so the first exact-session command failed before logout. A second
same-shell identity check passed, and native `WTSLogoffSession` returned success for console session
1. This proves logout dispatch, not recovery. The acceptance is now `WAITING_FOR_OWNER_LOGIN` and
must resume the unchanged `-04` profile/task/state after the owner logs in interactively.

### Windows post-login failure

After real login, the same task/profile/definition/desired identity remained. Console session 2 was
the legitimate successor to session 1. The old process and lease records still matched each other,
but the original process was dead; status reported `stale`.

The logon trigger attempted reconcile while Agent Bus health was transiently unavailable and exited
1. A subsequent doctor passed, but scheduled periodic triggers did not form a new incarnation in two
bounded waits. The old PID was later reused: live creation FILETIME differed from the recorded
FILETIME, and exact identity correctly refused it.

Normal stop wrote desired `stopped`, generation 3, then failed closed before any signal because the
listener was not an exact live incarnation. The Scheduled Task, install record, stale process/lease
and logs remain preserved; no restart, manual record cleanup or uninstall was attempted.

`-04` therefore fails the logout/login acceptance. A narrow L3 repair is required before a fresh
identity may continue.

RTS-048 supplied that repair and passed independent review plus exact-head CI. Reviewed code was
installed into the original `-04` venv solely for cleanup. Normal stop/uninstall removed the process
record, lease, task definition, install record and Scheduled Task; desired/log evidence remains and
no PID signal occurred.

The owner later authorized one new logout only after a mandatory RustDesk recovery preflight.
At exact repository HEAD `06f075d737d5cdb77e9630bf8f4fc601793ef266`, read-only Windows evidence
showed the `RustDesk` service existed, was `Running`, used `Auto` start and owned a live Session 0
process. The Windows desktop was already locked when RustDesk connected. The connection was
intentionally closed, re-established from the Mac, and could control the secure screen from the
clock page into the PIN prompt.

The preflight did not PASS: no authorized Windows PIN/login credential was available to the
executor, so it could not unlock the existing session and confirm recovered normal desktop control.
Because the machine was already locked, this run also did not manufacture a new lock transition.
RustDesk was disconnected, and execution stopped as `WAITING_FOR_OWNER_PHYSICAL_ACCESS`. Fresh
`-05` was not created, no logout occurred, and the post-unlock Clash/Agent Bus network check was not
started. No RustDesk, Windows security, firewall, lifecycle, Agent Bus or Runtime configuration was
changed.

## Scope `rts046-live-20260822-05`

### Windows pre-logout checkpoint

The owner accepted the preserved RustDesk recovery evidence and authorized exactly one fresh
logout/login sequence without another lock/reconnect preflight. A new disposable root, source,
venv, credential copy, profile, state, log and Task Scheduler identity were created; no `-04`
resource was reused or rewritten. The installed Runtime source was exact clean reviewed commit
`59123f262ce4a2e2ef719af1efdc5fd5342f9fb3`. The isolated Agent Bus source remained exact
`6ca8f2812be0286607bbbe3f14cc51783637b0b5`, and its bound executable proved `--on-argv` before
install/start.

The first doctor denied the newly copied credential file because it inherited an ACL. Only that new
disposable file was changed to the required explicit current-user ACL; the next strict doctor passed
with `configured=true`, `connected=true`, Agent Bus layer `pass`, model layer `not_applicable` and
`model_invoked=false`. No manager or lifecycle state existed before that repair.

Immediately before the authorized logout, exact evidence recorded:

- profile `rts046-win-task-20260822-05`, profile SHA-256
  `3ea4f0740128fc5a6558a7707108bd311193467b9d72ae06930e9416e6960908`;
- state-root SHA-256 `99e48a6304698bebc8de27975fd45527510712a8e04e3f77eafb586158a0bd25`;
- install manager `task-scheduler`, exact manager ID, current definition digest
  `846294511ddc07cb3ee4bbca84f72f7a3042e1ce498f4abe485bc7e120453d4c` and matching bytes;
- exact venv Python digest present, action argv bound to that Python, the immutable installed profile
  snapshot, task reconcile and the `-05` log;
- process PID `11028` and lease PID `11028`, identical launch ID
  `55bf5a080cb742568f340746f49cd4aa` and matching profile/repo/state-root identity;
- recorded/live Windows creation FILETIME `134318495073804833` exact;
- desired `running`, generation 2; factual installation `current`, running observation `running`;
- exactly one `-05` Scheduled Task at root path, `Interactive` logon type, two triggers and running
  state;
- credential-safe listener log with 13 lines, seven listen/connect markers and zero `ERROR`; and
- current console user matched the installer principal in active console session 2.

No model, provider, business event, ACK/retry/requeue/recovery or Phase 5 action occurred. This
checkpoint is `READY_FOR_AUTHORIZED_LOGOUT`; only native `WTSLogoffSession` for the revalidated
active console session may advance it.

### Windows logout/login PASS

Native `WTSLogoffSession` returned success only after revalidating the exact session-2 console,
profile, state-root, launch, creation, desired and task identity. RustDesk then reconnected to the
normal Windows sign-in screen. The owner-authorized PIN completed a real interactive login; it was
not stored or written to evidence. The normal desktop became controllable and the active console
advanced legitimately from session 2 to session 3. No second logout or reboot occurred.

Without a manual restart or record edit, the same `-05` Scheduled Task logon trigger converged to a
new listener:

- old PID `11028` was absent and was never signaled after login;
- new process/lease PID `17492`, launch ID `2a7293c12e3d4c93a79b25677386c194` and creation FILETIME
  `134318498467181730` matched the live process exactly;
- profile and state-root digests remained identical to the pre-logout checkpoint;
- installation stayed `current`, running observation became `running`, and desired remained
  `running`, generation 2;
- the task logon run began at `2026-08-22T05:24:05Z`; the exact listener process began at
  `2026-08-22T05:24:06.718173Z`;
- the credential-safe log grew to 33 lines with 19 listen/connect markers and zero task-reconcile,
  Agent Bus readiness or other `ERROR` lines; and
- a fresh `awf node doctor` passed `configured`, `connected` and Agent Bus health while model status
  remained `not_applicable`/not invoked.

The real login encountered no transient Bus failure, so no fault was manufactured merely to enter
the retry branch. The reviewed RTS-048 focused/full/CI evidence remains the proof of the bounded
transient retry and PID-reuse denial cases; this fresh acceptance proves that code converges across
the actual logout/login boundary. The existing Clash service remained running in Session 0, and the
live Agent Bus health probe passed without changing Clash or Bus configuration.

Normal exact stop removed PID `17492`, its process record and lease, and wrote desired `stopped`,
generation 3. Normal uninstall then removed the native definition, install record, Scheduled Task
and installed-profile registry references. No RTS-046 Scheduled Task remains. The immutable snapshot
file, source profile, strict credential copy, desired state and 35-line zero-error log remain in the
disposable root as bounded evidence; the snapshot has zero registry references and cannot authorize
an installed lifecycle. `-04` remains permanently failed and untouched.

Windows logout/login acceptance is `PASS`. Phase 5 did not start.

## Scope `rts046-live-20260822-06`

### tx-vps Linux systemd-user PASS

The owner corrected the topology to the existing `tx-vps` host and current root account. Minimal
entry checks proved systemd-user running, linger `no`, six enabled user units, and an existing active
system `agent-bus.service`. The server baseline recorded PID `2652165`, its start identity, healthy
local endpoint and SHA-256 digests of the existing unit/env files. No Agent Bus CLI was installed for
root, while the server env contained a locally reusable architect token map under owner-only `0600`
permissions.

Scope `-06` declared one absent disposable root/profile/route/unit. Linger changed temporarily from
`no` to `yes`. Exact clean Workflow head `87ceb3a0a5b0d6bb919c1d426bcebd02b326c5cb`
and Agent Bus source `6ca8f2812be0286607bbbe3f14cc51783637b0b5` were installed into isolated
CPython 3.11 venvs. The host system Python 3.10 was ineligible; the accepted venvs therefore used the
already-present Agent Bus base CPython 3.11 without changing the service environment. A stalled uv
3.12 seed process was exact-cmdline terminated and its acceptance-created temp directory later
removed. The compatible client proved `--on-argv`.

The server env was parsed only in remote memory to create a unique root-owned `0600` config. No
endpoint/token value appeared in argv, output or evidence. The first doctor rejected one mechanical
key-name mismatch before manager state; renaming only that disposable key produced a strict PASS:
configured/connected true, Agent Bus layer pass, model not applicable/not invoked, and next action
install. Profile digest was `8514e0b5...`; state-root digest was `64e3fff6...`.

The required sequence then completed:

```text
doctor -> install -> start -> status -> logs -> restart -> status -> exact stop -> uninstall
```

- install created only unit `awf-node-rts046-linux-systemd-txvps-20260822-06.service`, exact
  install/snapshot records and definition digest `b3ec8262...`; enabled user units moved 6 -> 7;
- first start reached truthful current/running with systemd MainPID, process and lease PID `1681549`,
  launch `19375d706ca341bca51e92070aa16bce` and exact profile/repo/state-root join;
- restart removed that PID and produced new MainPID/process/lease `1682597`, new launch
  `2b2a0d9ef69e455b887faa4441c880e6`, preserved identity and desired generation 4;
- logs were read through the existing lifecycle API and contained zero `ERROR` lines;
- pre-stop exact process/lease/MainPID/launch/state-root identity was revalidated; normal stop removed
  PID/process/lease and wrote desired `stopped`, generation 5;
- normal uninstall removed definition/install/registry and disabled the unit; exact `reset-failed`
  cleared only the deleted unit's volatile failed cache, yielding unit status not-found; and
- no model, business handler, event, ACK, retry, requeue, recovery or provider action occurred.

Final cleanup removed the unique root (including the credential copy and both clients), the
unreferenced immutable profile snapshot and the identified uv temp. Linger returned to `no`. Enabled
user units returned to six with exact baseline hash `5430a5ef...`. Root, process, lease, definition,
install, registry, snapshot, unit and process references were absent. Agent Bus Server active/running
state, PID/start identity, health and unit/env hashes exactly matched the baseline. No server code,
config, database, token, event, queue or ACK state was modified or inspected.

Linux systemd-user acceptance is `PASS`. Final independent Gate Review returned `PASS` with zero
blocking findings. RTS-046 and Phase 4B are complete. Phase 5 did not start.
