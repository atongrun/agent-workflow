# Runtime node lifecycle architecture

Status: proposed for independent architecture review (2026-08-09)

## Boundary

This document covers supervision of the non-core role listener only. It does not make Agent
Workflow a scheduler, move runtime behavior into Agent Bus, or change event payloads, route/stage
authorization, model selection, checkpoints, outbox/inbox ordering, or success-gated ACK. A native
service manager may start, observe, stop, and restart the listener process; it must never inspect,
ACK, requeue, resend, or reinterpret a delivery.

The stable listener remains one foreground program. Platform supervisors must own daemonization.
This follows launchd and mature supervisor guidance: a supervised process must not detach itself or
fork away from the supervisor.

## Root-cause evidence

Evidence is graded so the historical incident is not overstated.

### Direct incident evidence

The preserved rc.4 dogfood report records one exact sequence:

1. Windows `awf node doctor/start/status` and Fast Preflight were healthy while the bootstrap SSH
   session remained open.
2. After that SSH session exited, a fresh status observed a dead recorded process, an unbound stale
   lease, and no listener.
3. The single disposable Deep request remained pending; there was no handler, checkpoint, artifact,
   model invocation, TaskCard attempt, ACK, requeue, resend, or second dispatch.

That proves session-correlated listener loss. It does not, by itself, identify the Windows kernel
mechanism.

### Direct mechanism evidence

PowerShell/Win32-OpenSSH `latestw_all` commit
[`2143eae`](https://github.com/PowerShell/openssh-portable/commit/2143eae435e3ed93e73426d9138684f98468f6a7)
creates the command shell inside a Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK`, assigns the shell to that
job, and duplicates the job handle into the shell
([`w32-doexec.c` lines 439-463](https://github.com/PowerShell/openssh-portable/blob/2143eae435e3ed93e73426d9138684f98468f6a7/contrib/win32/win32compat/w32-doexec.c#L439-L463)).
Microsoft documents that child processes join their parent's job by default and that
`KILL_ON_JOB_CLOSE` terminates associated processes when the last job handle closes
([Job Objects, updated 2025-07-14](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)).

A read-only probe on the affected Windows host on 2026-08-09 observed the actual Python interpreter
started by a fresh SSH command inside a job whose immediate extended limit flags were `0x2800`:
`KILL_ON_JOB_CLOSE=true`, `BREAKAWAY_OK=true`, `SILENT_BREAKAWAY_OK=false`. `IsProcessInJob` and
`QueryInformationJobObject(JobObjectExtendedLimitInformation)` both succeeded. This is current-host
evidence, not a retroactive query of the already-dead historical listener.

Five short-lived child probes then established the local creation-flag boundary:

| Flags | Child immediate job | Survived session A | Session B local stop |
|---|---|---:|---|
| none | `0x2800` | not tested | not applicable |
| `CREATE_NEW_PROCESS_GROUP` | `0x2800` | no | not applicable |
| `DETACHED_PROCESS` | `0x2800` | not accepted as durable | not applicable |
| `CREATE_BREAKAWAY_FROM_JOB` | outer job `0x1800` | short probe survived | not tested alone |
| `CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP` | outer job `0x1800` | yes | `CTRL_BREAK` failed with `WinError 87` |

All probes had closed stdin, no files, no network or queue access, and bounded natural exits; a
fresh check found no orphan diagnostic PID. Microsoft defines `CREATE_NEW_PROCESS_GROUP` as a
console control-event grouping mechanism, not a persistence boundary, and says `CTRL_BREAK` reaches
only group members sharing the caller's console
([Process Creation Flags, updated 2025-07-14](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags),
[GenerateConsoleCtrlEvent](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent)).

### Root-cause conclusion

- **Proven:** the rc.4 listener was healthy only inside its starting SSH session and was dead after
  that session ended.
- **Proven on the same host/current OpenSSH path:** ordinary children, `DETACHED_PROCESS`, and
  `CREATE_NEW_PROCESS_GROUP` remain job-managed; a new process group does not survive session A.
- **High-confidence inference:** the historical listener inherited the OpenSSH kill-on-close job and
  died when the session-owned job closed. The original dead PID cannot now be queried, so this is
  not labelled a retroactive kernel observation.
- **Proven rejection of a tempting patch:** breakaway can improve survival on this host, but the
  existing session-B `CTRL_BREAK` stop contract no longer works. Adding detach/breakaway flags alone
  would trade one lifecycle bug for an uncontrollable process.

## Lifecycle invariants

1. Agent Bus remains opaque at-least-once transport. Lifecycle commands never read payloads or call
   ACK, requeue, resend, or dispatch.
2. The supervised executable is the foreground listener. No double-fork, `setsid`, detached child,
   or hidden second daemon is permitted under a service manager.
3. A listener is `running` only when manager state (for service mode), a live listener PID, the exact
   role/repository/profile digest, and one current lease agree. PID liveness alone is insufficient.
4. `stop` is local process supervision. It must not depend on `control:shutdown`, and it must not
   report success until the listener and its handler process tree are gone and the matching lease is
   released. A bounded forced termination may fail closed with preserved evidence; it may not forge
   lease cleanup.
5. Crash restart starts the same foreground listener with the same profile. It does not bypass the
   pre-model route/stage/attempt/rework/selection gates or same-delivery checkpoint/outbox recovery.
6. An intentional stop must remain stopped. Restart-on-failure policy must distinguish manager stop
   from unexpected non-zero exit and must use bounded backoff to avoid a credential/tool crash loop.
7. Secrets remain only in the strict owner-only operations configuration or the service manager's
   credential store. Profiles, generated units, command lines, logs, and install records contain no
   token or password.
8. The service identity is least-privileged and owns or can read only its profile, credential file,
   dedicated role checkout, state, logs, selected model configuration, and required executables.
   Windows must not silently default the model-executing listener to `LocalSystem`.
9. Install, upgrade, and uninstall are profile-bound and idempotent. An installed-record digest binds
   the manager identifier, rendered definition, profile path/digest, Python/awf executable, and (on
   Windows) the exact WinSW binary hash.
10. A session-bound start detected inside SSH fails closed unless the operator explicitly chooses a
    temporary session-bound override. It never claims post-SSH durability.

## Supported modes

| Mode | Owner | SSH disconnect | Crash restart | Stop owner | Intended use |
|---|---|---:|---:|---|---|
| `foreground` | invoking terminal | no promise | no | local Ctrl-C / manager signal | debugging and supervisor target |
| `session` | `awf node` user process | unsupported; fail closed by default | no | existing process-group interrupt | short local interactive use |
| `service` | native platform manager | required | bounded | native manager | unattended listener |
| external/manual | operator-selected supervisor | supervisor-defined | supervisor-defined | supervisor-defined | compatibility escape hatch, not an accepted claim |

`foreground` is a command behavior, not a stored profile mode. Existing v1 profiles that omit
`lifecycle` retain `session`, preserving local compatibility while making remote limitations
explicit. The service adapter does not alter the listener argv contract; it derives the complete
argv from the same profile, including v3 remotes, selected tool/model, state root, and optional Deep
Preflight routes.

## Decision matrix

Ratings are relative: 5 is best, except maintenance cost where 5 is most costly.

| Candidate | Portability | post-SSH reliability | stop/restart | least privilege | install UX | testability | compatibility | maintenance cost | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A. subprocess detach/breakaway | 1 | 2 | 1 | 3 | 5 | 3 | 1 | 2 | reject |
| B. WinSW + launchd/systemd service adapter | 4 | 5 | 5 | 3 | 3 | 4 | 4 | 4 | adopt for persistent mode |
| C. external supervisor/manual operator | 3 | 4 | 3 | 3 | 1 | 2 | 5 | 1 | documented escape hatch only |
| D. session process + SSH fail closed | 5 | 1 | 3 | 4 | 4 | 5 | 5 | 1 | retain for interactive mode |

Candidate A is rejected by direct evidence: even when breakaway survives, the existing stop
primitive fails. Candidate C avoids repository code but leaves profile/argv drift, readiness,
status, logs, account identity, and upgrade semantics outside the auditable contract. Candidate D
is necessary for honest compatibility but cannot unblock a remote unattended node. Candidate B is
the only option that owns the full lifecycle without turning Agent Bus into a runtime.

WinSW remains an external dependency rather than a new Python package. The latest stable release is
[`v2.12.0` (2023-01-28)](https://github.com/winsw/winsw/releases/tag/v2.12.0); its v2 XML contract
documents Ctrl-C-then-bounded-termination stop, restart-on-failure, rolling logs, service accounts,
and manager commands
([v2.12.0 XML reference](https://github.com/winsw/winsw/blob/v2.12.0/doc/xmlConfigFile.md)).
NSSM offers similar wrapping, status, restart, and log redirection, but its published download is
substantially older and it is not selected as the primary adapter
([NSSM commands](https://nssm.cc/commands), [downloads](https://nssm.cc/download)).

## Profile and CLI contract

`awf.node-profile.v1` gains one optional, secret-free object:

```json
{
  "lifecycle": {
    "mode": "service",
    "manager": "auto",
    "scope": "user",
    "service_account": ".\\awf-coder",
    "winsw_executable": "C:\\absolute\\path\\WinSW-x64.exe",
    "winsw_sha256": "sha256:<64 lowercase hex>"
  }
}
```

- `mode`: `session` or `service`; omitted means `session`.
- `manager`: `auto`, `launchd`, `systemd`, or `winsw`; `auto` resolves only to the native manager.
- `scope`: `user` or `system`. macOS defaults to a user LaunchAgent; Linux defaults to a user unit
  and requires lingering for post-logout use; Windows SCM/WinSW is system-scoped but must run the
  listener as an explicitly provisioned least-privileged account.
- `service_account`: a non-secret Windows account identity (for example `.\\awf-coder` or a
  managed-service-account name). It is forbidden on non-Windows managers and required for WinSW.
  No password, token, SID credential, or recovery secret is accepted in the profile.
- WinSW path and digest are Windows-service-only. The adapter never downloads or silently upgrades
  the external binary.

Commands remain profile-first:

```text
awf node doctor     --profile <profile>
awf node foreground --profile <profile>
awf node install    --profile <profile>
awf node start      --profile <profile>
awf node status     --profile <profile> [--run <run>] [--json]
awf node logs       --profile <profile> [--lines <n>]
awf node stop       --profile <profile>
awf node restart    --profile <profile>
awf node upgrade    --profile <profile>
awf node uninstall  --profile <profile>
```

For `session`, `install/upgrade/uninstall/restart` are rejected and `start` keeps the current local
user-process behavior. Under detected SSH variables, `start` rejects by default and names
`foreground`, service installation, or an explicit temporary `--allow-session-bound` override.

For `service`, `start/status/logs/stop/restart` delegate to one small platform adapter. The service
definition always invokes `awf node foreground --profile <absolute-profile>` so every manager uses
the same profile-derived listener argv and readiness gates. `install` renders, validates, installs,
and records exact artifacts. `upgrade` requires the service stopped, re-renders from the current
profile/awf/WinSW digests, refreshes/reloads manager state, then starts and revalidates. `uninstall`
stops, verifies stopped plus lease/process-tree cleanup, removes only the exact installed manager
entry, and preserves logs and the install record as recoverable evidence unless an explicit future
purge command is designed.

Windows account credentials are never accepted as CLI arguments or profile fields. If the chosen
WinSW/account flow cannot prompt/store credentials through Windows SCM without writing a password
to XML, installation fails with an exact operator step instead of falling back to `LocalSystem`.
The supported v2 path therefore separates artifact installation from account binding: `awf node
install` renders and validates the password-free service definition, then fails closed until an
administrator binds the pre-provisioned account directly in SCM (or uses a managed service
account) and grants only `Log on as a service` plus the required path ACLs. `status` compares the
profile account with SCM `StartName` and the live listener process-token user. Any disagreement is
`degraded`, never `running`. The install record stores the normalized non-secret account name and
SID when available, but never a credential.

## Platform adapters

### Windows / WinSW

- Verify the supplied WinSW executable and exact SHA-256 before install and every mutating command.
- Generate a per-profile XML and wrapper location outside the role checkout.
- Use automatic start with bounded restart delay and rolling logs.
- Require an operator-provisioned least-privileged service account; reject implicit `LocalSystem`.
- Before installation succeeds, query SCM and verify `StartName` against the normalized profile
  account; after start, verify the listener process token resolves to that same identity.
- `stop` is a manager-owned state machine, not a PID signal shortcut:
  1. snapshot the SCM service PID plus descendants by PID, parent PID, and creation time;
  2. request WinSW/SCM stop, which first sends Ctrl-C to the foreground listener;
  3. during the graceful deadline require the exact lease to disappear and the snapshotted tree to
     exit; never remove a live lease or signal a PID outside that identity snapshot;
  4. if the deadline expires, allow only WinSW/SCM's documented bounded tree termination, then
     re-query SCM and every snapshotted process identity;
  5. return `stopped` only when SCM is stopped, no matching process identity remains, and the lease
     is absent. A live/unknown descendant or lease is `degraded` with evidence preserved.
  Acceptance must prove the normal path reaches listener `finally` lease cleanup before escalation,
  and separately lock the forced, orphan, stale-lease, and PID-reuse refusal paths.

### Existing service templates

The current `scripts/service/*` env-only wrappers and `awf_service.py` are legacy candidate
artifacts, not the new accepted contract. They must not remain as a second service lifecycle.
Implementation either migrates them to generated `awf node foreground --profile
<absolute-profile>` definitions or marks/removes them in the same auditable change. The renderer's
install digest covers manager identifier, complete rendered definition, absolute profile path and
digest, awf/Python identity, account identity, and WinSW binary hash. No template may assemble a
partial listener argv from environment variables.

### macOS / launchd

Use a per-user LaunchAgent for the normal developer-node scope. Apple says user agents are preferred
for per-user background processes, are tied to the logged-in user, receive `SIGTERM` at logout, and
must not daemonize or call `setsid`
([Creating Launch Daemons and Agents, updated 2016-09-13](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)).
The generated plist uses tokenized `ProgramArguments`, explicit working directory and log paths,
and restart-on-unexpected-exit. A system LaunchDaemon is a separate privileged scope, not an
automatic fallback.

### Linux / systemd

Use a user service by default. A user manager normally follows login lifetime; post-logout service
requires `loginctl enable-linger`, which spawns the user manager at boot and retains it after logout
([loginctl](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html)). The adapter
checks lingering and fails closed rather than claiming persistence. The unit runs the listener in
the foreground, uses a bounded `Restart=on-failure`, and relies on the manager process tree/cgroup
for no-orphan stop and journal logs.

## Failure and recovery

- Readiness failure: no listener is started and no service is reported healthy.
- Manager starts but lease/profile binding never appears: status is `degraded`, start fails after a
  bounded deadline, logs are named, and no queue action occurs.
- Listener crash before a handler: manager may restart after backoff; no delivery was ACKed.
- Interruption during a handler: existing checkpoint/outbox/inbox rules remain authoritative. A
  duplicate delivery resumes only from a trusted boundary and never repeats an ambiguous model.
- Manager says stopped but a bound PID/lease remains: stop fails closed and preserves evidence.
- PID is dead but the matching lease remains: status is `stale`; a future start may remove it only
  through the existing locked stale-lease rule after non-signalling liveness checks.
- Profile or installed artifact digest changes: start/status refuse until explicit `upgrade`.
- Repeated crash: bounded restart policy reaches a stable failed state; no unbounded model retry or
  event mutation is introduced.

## Acceptance matrix

Unit and CI coverage must lock schema defaults, manager resolution, profile-derived foreground
argv, SSH fail closed, rendering/escaping, binary digest checks, idempotent install/upgrade,
manager/status/lease agreement, graceful and forced-stop failure paths, crash backoff, uninstall
targeting, secret absence, and v1-v3 plus Mac/Linux command regressions. Complete repository CI must
remain green on Windows, macOS, and Linux installed wheels.

The live Windows acceptance is deliberately stronger than the former same-session smoke:

1. Session A installs/starts the service from a fixed wheel/profile and records manager service ID,
   profile digest, WinSW digest, listener PID, launch identity, and lease.
2. Session A exits completely.
3. After a declared 10-second observation window, fresh session B verifies manager state, the live
   listener PID and launch identity, exact lease/profile binding, and zero unexpected traceback.
4. Only after steps 1-3 establish the durable listener, the already-pending unique Deep request may
   be consumed by the normal listener and success-gated Agent Bus handler path. The operator does
   not inspect its payload or manually ACK, requeue, resend, replace, or issue a second Deep request.
5. Session B performs local `awf node stop`; it must not send `control:shutdown`. The manager,
   listener, handler descendants, process record, and lease converge to stopped with no orphan or
   traceback.
6. Crash/restart and pre-model denial fixtures prove recovery does not invoke a model or change
   TaskCard attempts before authorization.

If Windows administrator/service-account authority is unavailable, implementation and CI may be
reviewed first, but the result remains `live acceptance pending`; the exact elevated install and
session A/B commands must be handed off without claiming success.
