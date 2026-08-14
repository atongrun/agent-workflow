# Runtime node lifecycle architecture

Status: accepted; real post-SSH lifecycle acceptance passed (2026-08-09)

## Decision

The listener is one foreground program behind a small, payload-blind desired-state reconciler owned
by a native **user supervisor**. Agent Bus transports deliveries but never owns the process.
Interactive `awf node start` remains session-bound and fails closed inside SSH.

The normal Windows workstation path uses Task Scheduler with the active local console user's
`InteractiveToken` and a one-minute periodic trigger. It does not install a Windows Service, create another account, move model or Git
credentials, or invoke PowerShell. A system service is deferred until a real requirement says the
listener must run before any user logs in.

## What failed

Evidence is graded so a plausible mechanism is not presented as a historical observation.

### Proven from the rc.4 incident

1. The Windows listener, launch identity, lease, status, and Fast Preflight were healthy while the
   SSH session that started it remained open.
2. After that session exited, a fresh observation found the process dead and its record/lease stale.
3. The one Deep request remained pending. There was no handler, model invocation, TaskCard attempt,
   ACK, requeue, resend, or second dispatch.

### Proven later on the same host

The affected OpenSSH path places ordinary children in a kill-on-close Job Object. A bounded probe
showed `CREATE_NEW_PROCESS_GROUP` did not escape it. Breakaway survived but could not be stopped by
the existing session-B `CTRL_BREAK` contract. Detach/breakaway is therefore not an accepted daemon
mechanism.

On 2026-08-09 a separate no-model listener was started by Task Scheduler from SSH session A. After
that session exited, session B proved the task, real interpreter PID, process creation identity,
profile digest, launch ID, lease, and read-only Agent Bus connectivity. A forced process-tree crash
recovered with a new exact launch identity on the next one-minute trigger. Local stop removed the
tree and lease without a control event; a later fresh empty `control:shutdown` event was consumed,
ACKed, and changed desired state to stopped. The exact task definition and install record were then
uninstalled while logs remained.

### Root cause

The lifecycle owner was wrong. An SSH-owned process cannot honestly promise to outlive SSH. The fix
is to transfer ownership to a persistent local supervisor, not to add another creation flag.

## Product environment and guarantee

Normally the Mac and Windows nodes communicate only through Agent Bus. SSH is an exceptional
diagnostic channel, not a bootstrap or control-plane dependency.

| Mode | Owner | SSH exit | Crash restart | Logout / reboot |
|---|---|---:|---:|---|
| `foreground` | terminal or external supervisor | no promise | supervisor-defined | supervisor-defined |
| `session` | `awf node` child | unsupported; SSH start fails closed | no | no |
| `managed` | native user supervisor + JSON reconciler | must survive | bounded | platform contract below |

`managed` resolves to:

- Windows: Task Scheduler, active local console `InteractiveToken`, one-minute trigger, least privilege. `IgnoreNew`
  prevents parallel instances. A dead listener or reconciler is relaunched within the declared
  60-second window while that local console user is logged in. Logout ends the guarantee;
  boot-before-login and RDP-only sessions are unsupported.
- macOS: per-user LaunchAgent, following the user's login lifecycle.
- Linux: `systemd --user`; post-logout operation requires lingering and fails closed without it.

This matches the personal-workstation topology and preserves the same user profile, model CLI
configuration, Git/SSH identity, repo permissions, and Agent Bus configuration. It avoids the real
cost of a Windows Service: provisioning those resources for a different identity.

## Invariants

1. Lifecycle code never reads, ACKs, requeues, resends, or dispatches an Agent Bus delivery.
2. A node profile must declare one absolute `state_root`. Node start resolves it once, records its
   credential-free binding, and passes the exact path through listener argv and every generated
   business/preflight handler. Process record, listener lease, RunEvidence, RunLedger context,
   delivery checkpoint, business outbox, Feedback Outbox, readiness, and status all bind that same
   root. An argv/environment/durable-record disagreement fails before Bus connection or provider
   invocation. Direct script entry retains only the explicit compatibility order
   `--state-root` -> `AWF_STATE_ROOT` -> platform default.
3. Every supervisor runs exactly `awf node reconcile --profile <absolute-path>`. Reconcile reads one
   atomic JSON desired-state record and either exits stopped or runs the unchanged foreground
   listener; neither layer detaches.
4. Running requires agreement among installed definition digest, process record, profile digest,
   live PID, exact `launch_id`, role/repo, and lease. PID liveness alone is insufficient.
5. Only one manager instance is allowed; an existing live listener wins over another start.
6. Agent Bus `control:shutdown` remains the normal remote graceful-stop path. A successful clean
   listener exit records desired `stopped`; a non-zero exit preserves desired `running`. `awf node
   stop` records stopped before its independent local manager action and never depends on the
   control event. It succeeds only after
   the exact recorded process tree is dead. Stale state is removed only when launch identity matches
   and all bound PIDs are proven dead; live or unknown identity fails closed.
7. Crash reconcile uses the same foreground command. Existing checkpoint/outbox/inbox and success-gated ACK
   semantics remain authoritative.
8. Definitions, profiles, argv, install records, and logs contain no password or token.
9. Install, upgrade, and uninstall are profile-bound and idempotent. Uninstall touches only its exact
   recorded manager identifier and preserves business state and logs.
10. Operator lifecycle truth is five orthogonal facts. `configured` covers only the
    profile/config/tool/workspace boundary; `installed` comes from the native install record plus
    definition digest; `running` retains the exact profile/process/lease/launch agreement;
    `connected` is a bounded live Bus observation; and `dispatch_capable` requires current Fast
    validation of the bound Deep proof. False, unknown, and stale facts are not collapsed.

## Decision matrix

Maintenance cost 5 is worst.

| Candidate | post-SSH | Same user config | Stop/status | Install UX | Cost | Decision |
|---|---:|---:|---:|---:|---:|---|
| subprocess detach/breakaway | 2 | 5 | 1 | 5 | 2 | reject |
| WinSW/SCM under service identity | 5 | 1 | 5 | 1 | 5 | defer until pre-login operation is required |
| Task Scheduler periodic reconcile | 4 | 5 | 4 | 5 | 3 | Windows managed default |
| external/manual supervisor | manager-defined | 4 | 2 | 1 | 1 | escape hatch only |
| session process + SSH fail closed | 1 | 5 | 4 | 5 | 1 | retain for interactive work |

Task Scheduler is the shortest adequate path because this node is a logged-in personal workstation,
not a headless server. Microsoft documents that `InteractiveToken` requires an existing logged-in
user. The generated native definition explicitly selects `IgnoreNew` and unlimited action runtime;
a payload-free live probe proved that
nominal `RestartOnFailure` did not restart an action returning 1 on the target host, so this design
does not claim or use it. The periodic trigger re-enters the idempotent JSON reconciler instead:

- [Task Scheduler logon type](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-logontype-principaltype-element)
- [Task Scheduler settings](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-settings-tasktype-element)
- [Task Scheduler XML schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema)
- [`schtasks` command](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks)

S4U is rejected because Microsoft states it has no network or encrypted-file access. Password logon
adds credential storage. `LocalSystem` and `NetworkService` do not share the operator's model, Git,
or config identity and would reintroduce the provisioning work this design removes.

## Profile and CLI

Omitting `lifecycle` remains session-bound:

```json
{"lifecycle": {"mode": "managed", "manager": "auto", "scope": "user"}}
```

No Windows account, password, supervisor binary, or platform credential appears in the profile.
`auto` resolves to `task-scheduler`, `launchd`, or `systemd`. Desired state is another versioned
JSON record containing only state, absolute profile path, profile digest, and generation.

The common commands are `doctor`, `foreground`, `reconcile`, `install`, `start`, `status`, `logs`, `stop`,
`restart`, `upgrade`, and `uninstall`, all under `awf node --profile <profile>`. Windows calls
`schtasks.exe` directly with structured argv to register an internally generated native task
definition. That definition sets a one-minute/current-user schedule, `IgnoreNew`, and `PT0S`
unlimited execution; its action is the exact reconcile argv. Profiles and desired state remain
portable JSON. Operators do not write XML, and PowerShell is neither generated nor invoked.
`install` leaves desired state stopped; `start` is the explicit transition to running. Installation
is an explicit idempotent prerequisite: `start` never creates or rewrites a definition, and a
missing install record fails before desired-state or manager mutation with the exact
`awf node install --profile <profile>` action on every manager.
The already supported Agent Bus `control:shutdown` may stop it gracefully from another node;
`awf node start` asks the local supervisor to resume it.

## Failure and recovery

- No active local console user: on-demand start fails before launch. Periodic reconciliation resumes
  within 60 seconds after the configured user logs into the local console again.
- Manager starts without lease readiness: start times out, status is degraded, and no queue action
  occurs.
- Listener/reconciler exits non-zero: desired state remains running and the next Windows trigger, or
  native launchd/systemd restart, reconciles it.
- Stop: exact live PID, profile digest, launch binding, and lease are rechecked. Live or unknown state preserves
  evidence; only dead exact-bound stale files may be removed.
- Handler interruption: durable checkpoint/outbox/inbox recovery and Agent Bus redelivery remain
  authoritative. The supervisor never manufactures an ACK.

## Acceptance gate

Windows support is not accepted from CI or a same-SSH smoke. It requires:

1. Session A installs/starts the node, then exits completely.
2. After a declared window, session B verifies task definition, listener PID/creation identity,
   profile digest, launch ID, lease, and read-only Agent Bus connectivity.
3. A new disposable event is consumed exactly once with no duplicate model call.
4. Killing the listener and reconciler proves recovery within 60 seconds and a new consistent
   launch identity.
5. Local stop proves no traceback, descendant, or stale state without `control:shutdown`.
6. Logout ends the Windows guarantee; next login proves automatic recovery.
7. macOS and Linux retain the common schema and CLI in CI.

Items 1-5 passed on 2026-08-09 with a separate `architect`/`tool=none` profile; the disposable event
was empty `control:shutdown` event 149. Item 6 remains an explicit operator check because the
Windows guarantee begins only after local-console login. Item 7 passed in the six-job GitHub CI
matrix. The historical pending Deep request remained untouched: lifecycle work did not inspect,
ACK, requeue, resend, or dispatch it again.
