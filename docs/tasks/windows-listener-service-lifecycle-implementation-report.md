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

- Static Python/JSON parsing: pass.
- `git diff --check`: pass.
- Local pytest/Ruff: not run, per repository Mac policy.
- Three-platform GitHub CI: pending.
- Independent code review: pending after CI.
- Payload-free Windows probes: Task Scheduler work survived its creating SSH session; Scheduler End
  alone orphaned a child and was rejected; exact-bound `taskkill /T /F` followed by End removed the
  complete observed tree. The nominal `RestartOnFailure` setting did not restart a failing action
  and was rejected in favor of periodic reconcile. All probe tasks and files were deleted.
- Real Windows listener post-SSH, crash-restart, clean Agent Bus shutdown, and fresh disposable
  consumption acceptance: pending. Until it passes, this implementation is not proven durable.
