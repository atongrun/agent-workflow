# RTS-046 Fresh Native-Manager Acceptance Report

## Outcome

`EXTERNAL_BLOCKED` on Linux qualification.

Windows fresh `-05` real logout/login validation is `PASS`. Phase 4B remains open solely on Linux,
and Phase 5 did not start.

Two preserved macOS scopes remain immutable failures. A third fresh scope resolves only the
owner-authorized client-skew prerequisite and passes real macOS plus Windows manager acceptance,
including the real login boundary under `-05`. Linux remains pre-install blocked.

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
| Linux entry audit | multiple existing Linux user hosts | blocked before install | no existing linger plus no existing AWF/Bus config on suitable hosts |
| Windows login gate | existing Windows interactive-console user | PASS | one owner-authorized logout, RustDesk login and automatic Task Scheduler convergence |

## Environment and identity rules

- Candidate: exact RTS-047 reviewed/CI-green installed application descended from RTS-046.
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

## Remaining blockers

### Linux prerequisites

No audited suitable Linux user host already had both linger enabled and an AWF/Agent Bus
configuration. Enabling linger changes host login/service policy, and deploying/configuring Agent
Bus is outside RTS-046. The systemd acceptance therefore correctly stopped before installation.

### Resolved Windows owner window

The Windows identity matched the current interactive-console user. The owner later supplied exactly
one fresh logout/login window; `-05` used it and passed. No second logout, simulation or inferred
login evidence occurred.

## Safety and cleanup

- No model, provider, business handler, TaskCard run, business event, ACK, retry, requeue, recovery or
  dispatch occurred.
- No Agent Bus server/state/credential, OS security, login policy, linger, Runtime Core, Finding,
  Agent Host or onboarding setting changed. Only isolated client installations/config copies were
  created under explicit authorization.
- No manual process signal, process-name scan, record edit, PYTHONPATH or base-interpreter install
  was used.
- Both macOS definitions/install records/registries were removed through normal exact uninstall.
- Failed-scope logs and desired-state evidence remain retained in disposable local roots.
- Linux created no acceptance manager/state resources. Every completed Windows manager scope was
  removed through exact stop/uninstall; isolated client/workflow roots plus desired/log and immutable
  snapshot evidence remain, with no installed registry reference or Scheduled Task.

## Limitations and legal next action

RTS-046 now proves real launchd steady running/restart/exact-stop and Task Scheduler post-SSH,
restart, real logout/login convergence and exact-stop/uninstall. It still does not prove any
systemd-user sequence. Phase 4B cannot close.

The only legal continuation is a fresh Linux acceptance after the owner provisions the selected
disposable host with the required credential-bearing AWF/Bus configuration through an execution
path permitted by the security layer. Windows needs no further logout/login evidence.

Do not alter Runtime/lifecycle identity, deploy Agent Bus from AWF, or start Phase 5 to clear these
blocks.

Before Phase 5, separately consider a small formal Agent Bus client release (likely v0.3.1) so the
structured contract is identified by a release version instead of only commit/capability evidence.
No release is published or authorized by RTS-046.

## Scope `rts046-live-20260822-04`

### Linux bounded attempt

The owner selected one exact disposable Linux principal and authorized reversible linger. Original
facts were linger `no`, eight enabled user units and absent disposable root/unit/registry. Linger was
enabled only for that user. Because system Python lacked ensurepip/pip, an official standalone
`virtualenv.pyz` was kept inside the disposable root and successfully installed exact Bus/Workflow
clients without OS package changes.

The safety approval boundary then rejected exporting existing credential values into the remote
temporary config. This authorization was not bypassed. No profile, systemd unit, process, lease,
event or lifecycle state was created. The exact root was inventoried and removed, linger restored to
`no`, enabled-unit count reverified as eight, and unit/registry/state absence passed. Linux remains
`EXTERNAL_BLOCKED` before manager acceptance.

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

Windows logout/login acceptance is `PASS`. RTS-046 and Phase 4B remain `EXTERNAL_BLOCKED` only on
the Linux systemd-user acceptance, and Phase 5 did not start.
