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

`docs/runtime-node-lifecycle-architecture.md` compares detach/breakaway, native services, external
supervisors, and SSH fail-closed session mode. It keeps interactive compatibility but selects a
native service adapter for persistent nodes. An independent read-only critic initially returned
NO-GO because Windows account identity, process-tree stop, and legacy template migration were not
executable enough. After the document added those contracts, the same critic confirmed every
blocking concern was resolved and returned implementation-readiness GO.

## Implementation

- Existing profiles default to `lifecycle.mode=session`.
- Session `start` fails closed under SSH unless `--allow-session-bound` is explicit.
- `awf node foreground` runs the complete profile-derived listener in the manager-owned process,
  publishes launch identity/process evidence, translates POSIX SIGTERM into the existing clean
  listener interrupt path, and removes only its exact process record.
- `awf node install/start/status/logs/stop/restart/upgrade/uninstall` dispatch to launchd user,
  lingering systemd user, or WinSW adapters.
- Generated definitions contain no secrets and always target the same foreground profile.
- WinSW is supplied and SHA-256-pinned by the operator. Installation rejects account drift and
  never accepts a password or falls back to LocalSystem. Status binds SCM account, live process
  token, process record, profile digest, launch identity, and listener lease.
- Windows stop snapshots the listener process identity and descendants, delegates graceful/forced
  tree handling to WinSW/SCM, and fails if any exact identity, record, or lease remains.
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
- Real Windows administrator/service-account installation and post-SSH session A/B acceptance:
  pending. Until it passes, this implementation must not be described as proven durable in the
  field.
