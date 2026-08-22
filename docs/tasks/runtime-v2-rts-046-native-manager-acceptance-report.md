# RTS-046 Fresh Native-Manager Acceptance Report

## Outcome

`EXTERNAL_BLOCKED` on Linux qualification.

Windows fresh repair validation is separately `OWNER_AUTHORIZATION_REQUIRED`. Phase 4B remains open
and Phase 5 did not start.

Two preserved macOS scopes remain immutable failures. A third fresh scope resolves only the
owner-authorized client-skew prerequisite and passes real macOS plus non-disruptive Windows manager
acceptance. Linux remains pre-install blocked.

## Acceptance scope

| Scope | Environment | Result | Durable meaning |
|---|---|---|---|
| `rts046-live-20260822-01` | macOS arm64, Python 3.12, fresh installed venv, unique launchd profile/state/log/label | failed before listener entry | exposed venv symlink resolution defect; never PASS |
| RTS-047 repair | local/CI five-target evidence | PASS | preserves invoked venv interpreter path; does not itself prove manager acceptance |
| `rts046-live-20260822-02` | macOS arm64, new venv/profile/state/log/label | failed at Agent Bus listener capability | confirms executable repair; never PASS |
| `rts046-live-20260822-03` | exact compatible isolated Bus clients; new macOS and Windows identities | macOS PASS; Windows non-disruptive PASS | only successful manager evidence |
| `rts046-live-20260822-04` | Windows real logout/login | failed post-login recovery; exactly cleaned after repair | never PASS |
| RTS-048 repair | local/CI five-target evidence | PASS | bounded login readiness and creation-aware stale cleanup |
| Linux entry audit | multiple existing Linux user hosts | blocked before install | no existing linger plus no existing AWF/Bus config on suitable hosts |
| Windows login gate | existing Windows interactive-console user | owner-blocked after safe lifecycle PASS | logout/login owner window absent |

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

### Windows owner window

The Windows identity matched the current interactive-console user, and all non-disruptive Task
Scheduler gates passed. No owner-authorized logout/login window was supplied. Logout/login was not
simulated, inferred or triggered.

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
- Linux created no acceptance manager/state resources. Windows manager/state resources were removed
  through exact stop/uninstall; its isolated client/workflow roots and log remain for owner-window
  continuation evidence.

## Limitations and legal next action

RTS-046 now proves real launchd steady running/restart/exact-stop and Task Scheduler post-SSH,
restart and exact-stop. It still does not prove any systemd-user sequence or Windows logout/login.
Phase 4B cannot close.

The only legal continuation is a new fresh acceptance identity after all external prerequisites are
provided:

1. an already-lingering Linux user host with existing AWF/Bus configuration; and
2. an explicitly scheduled Windows logout/login authorization window.

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

The current owner continuation prohibits another logout, so fresh `-05` was not created. Windows
logout/login acceptance remains `OWNER_AUTHORIZATION_REQUIRED` for a new controlled window.
