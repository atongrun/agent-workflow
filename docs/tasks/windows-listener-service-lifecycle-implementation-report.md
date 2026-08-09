# Windows listener service lifecycle implementation report

Date: 2026-08-09

## Problem and evidence

The rc.4 listener stayed healthy while its bootstrap SSH session remained open and was dead after
that session exited. The retained Deep request remained pending with zero model invocations and
zero TaskCard attempts; no historical payload or delivery lifecycle operation was used during this
work.

On the same Windows host, the actual SSH-started Python interpreter reported membership in an
OpenSSH Job with extended flags `0x2800` (`KILL_ON_JOB_CLOSE | BREAKAWAY_OK`). Bounded probes showed
that `CREATE_NEW_PROCESS_GROUP` did not survive session A, while breakaway survived but could not be
stopped from session B through the current Ctrl-Break contract. The historical dead PID was not
available for retroactive kernel inspection, so the incident mechanism remains a high-confidence
inference rather than a direct observation of that exact process.

## Decision and independent review

`docs/runtime-node-lifecycle-architecture.md` compares detach/breakaway, Windows Service, Task
Scheduler, external supervisors, and SSH fail-closed session mode. The first WinSW design was
rejected after operator review exposed that service identity, credential, ACL, and PowerShell-heavy
acceptance work were solving a problem the personal workstation did not have. An independent critic
gave a conditional GO to the smaller Task Scheduler `InteractiveToken` spike, subject to live
post-SSH, stop-tree, restart, and user-session evidence.

## Implementation

- Existing profiles default to `lifecycle.mode=session`.
- Session `start` fails closed under SSH unless `--allow-session-bound` is explicit.
- `awf node foreground` runs the complete profile-derived listener in the manager-owned process,
  publishes launch identity/process evidence, translates POSIX SIGTERM into the existing clean
  listener interrupt path, and removes only its exact process record.
- `awf node reconcile` reads an atomic, profile-bound desired-state JSON record. `running` enters
  the unchanged foreground listener; a clean exit records `stopped`; a non-zero exit preserves
  `running` for bounded recovery.
- `awf node install/start/status/logs/stop/restart/upgrade/uninstall` dispatch to launchd user,
  lingering systemd user, or Windows Task Scheduler user adapters.
- Generated definitions contain no secrets and always target the same profile reconciler.
- Windows reuses the active local console user's `InteractiveToken` and registers a one-minute periodic
  task. Its native definition explicitly selects `IgnoreNew` and unlimited execution; after a crash the
  next trigger re-enters reconcile. It accepts no password, creates no service account, emits no
  PowerShell, and requires no operator-authored XML. `install` leaves the desired state stopped;
  `start` is explicit.
- macOS uses a per-user LaunchAgent and Linux uses a lingering `systemd --user` unit. Both invoke
  the same reconcile command and consume the same JSON profile/desired-state contracts.
- Agent Bus `control:shutdown` remains the graceful remote stop. Local stop first verifies the
  exact profile, launch ID, PID, and lease, then uses native `taskkill /T /F` and Task Scheduler End;
  it fails if any exact record or lease remains.
- Legacy service wrappers/templates now accept only `AWF_PROFILE`; the `just` menu delegates to the
  unified CLI instead of rendering a second environment-variable lifecycle.

No Agent Bus, payload, RunManifest, TaskCard selection, Pi role, checkpoint, outbox, inbox, or ACK
code changed.

## Verification status

- Static Python/JSON parsing and `git diff --check`: pass.
- Local pytest/Ruff: not run, per repository Mac policy.
- GitHub CI at `aa0f943`: all six Linux, Windows, macOS runtime, and installed-wheel jobs passed.
- Independent architecture review: GO before implementation. Independent code review found one
  blocking uninstall/reinstall defect; the fix removes only the exact install record after native
  uninstall and adds reinstall regressions. Final review of the live-acceptance delta returned
  APPROVE with no blocking findings before PR #72 merged as `401a269`.
- Payload-free Windows probes: Task Scheduler work survived its creating SSH session; Scheduler End
  alone orphaned a child and was rejected; exact-bound `taskkill /T /F` followed by End removed the
  complete observed tree. The nominal `RestartOnFailure` setting did not restart a failing action
  and was rejected in favor of periodic reconcile. All probe tasks and files were deleted.

### Real Windows post-SSH acceptance

The test used a separate clone, venv, state root, JSON profile, task name, and an `architect` route
with `tool=none`; it could not invoke a model or process a business TaskCard.

| Check | Result | Evidence |
|---|---|---|
| session A exits completely | pass | `schtasks /Run` returned and the SSH connection closed |
| fresh session B after bounded wait | pass | task result `267009` (running); PID `27900`; launch ID `c64e96b790a04b8b9b9d1e85a8421bc3`; exact lease/profile digest |
| crash recovery within 60 seconds | pass | exact process tree killed; next periodic trigger produced PID `8064` and launch ID `b6ad304c99504e4c94ecf99ccd0bb6e5` with a new exact lease |
| local stop independent of Agent Bus | pass | desired stopped; PID absent; no process record, lease, orphan, or traceback |
| fresh Agent Bus consumption | pass | new empty `control:shutdown` event `149` logged `received`, graceful shutdown, then `ACKed`; pending returned to zero |
| clean uninstall | pass | exact scheduled task, generated XML, and install record absent; desired state and log retained |
| logout/login or reboot recovery | not run | the accepted Windows contract is logged-in local-console scope; this remains an operator acceptance item |

The live task initially exposed `[WinError 6]` only inside Task Scheduler. Direct SSH execution of
the same reconciler worked. Binding both Python streams and native Win32 standard handles to the
profile log fixed the scheduler environment; the successful listener and Agent Bus subprocess then
ran under the task after SSH exit. This is direct evidence for the final fix, not an assumed console
behavior.

The historical retained Deep request was never inspected, ACKed, requeued, resent, or dispatched
again. One earlier custom coder probe saw only redacted event metadata and left the unmatched event
unacknowledged. No model was invoked and no TaskCard attempt was created.
