# RTS-045 Exact Lifecycle Identity Repair Closeout

## Result

`PASS`. The two independent RTS-044 exact-install/incarnation findings are closed without changing
the existing lifecycle API, record formats, compatibility ownership or product boundary.

## Closed defects

- Managed stop and exact-dead cleanup now require present, exact process-record state-root path and
  binding in addition to profile/digest/role/repo, PID, launch ID, lease, liveness and Windows
  creation identity.
- Current installation now binds the record's manager identifier and definition path to the
  deterministic current adapter target before trusting its digest or authorizing an action.
- Upgrade stop retains its narrow stale-action-record purpose while rejecting manager-ID or
  definition-target drift.

Missing, partial or conflicting identity is preserved and denied before native-manager calls. No
fact is reconstructed from the lease, no alternate definition file becomes authority, and no state
format or compatibility behavior was migrated.

## Verification

- Focused lifecycle suite: **75 passed, 1 skipped**.
- Full repository suite: **876 passed, 5 skipped**.
- Compileall, Ruff, Ruff format and `git diff --check`: PASS.
- Independent L3 Gate Review at `37ea274`: `PASS`, zero findings.
- Exact-head ordinary CI `32544625110`: PASS, including Windows recovery/configuration and all
  installed-wheel jobs.
- Exact-head Binary Feasibility `32544625218`: PASS across every native/Rust cell and aggregate.
- Production net growth: +17 lines; focused test growth: 103 lines; no dependency or representation.

## Scope and rollback

Only `node_service.py`, its focused test module and TaskCard/evidence documents changed. Reverting
the repair restores the prior validation behavior and requires no state rollback because no record
format, manager installation or production state was changed.

No native manager, remote host, logout/login, reboot, Agent Bus event, Finding, Runtime Core,
launcher, migration, default or release operation occurred.

## Phase 4B boundary

RTS-044 local lifecycle conformance is now `PASS`: the existing multi-record `awf node` behavior is
the selected AgentInstallation/incarnation API shape, with exact-stop and read-only ownership
protected. Phase 4B itself remains open.

The sole next milestone is a separately frozen **RTS-046 fresh isolated three-OS native-manager
acceptance**. It must prove real launchd, systemd-user and Task Scheduler action sequences at one
exact installed candidate, plus current Windows post-SSH/restart/exact-stop/logout-login evidence.
It must assume Agent Bus is already available and must not install it, operate business events,
expand Agent Host/onboarding/Finding, or alter Runtime Core. Disruptive logout/login or reboot still
requires an explicitly scheduled owner acceptance window.
