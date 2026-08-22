# RTS-044 Native Lifecycle Conformance Report

## Result

`PASS` after the bounded RTS-045 repair and focused independent re-review. The existing multi-record
`awf node` surface is the correct lifecycle API shape and needs no new class, Store, authority record
or migration. The initial review's two exact-install/incarnation findings are closed.

This is not Phase 4B completion. Fresh real launchd, systemd-user and Task Scheduler action
sequences plus current-head Windows logout/login recovery remain unproved and belong to one
separately frozen acceptance TaskCard.

No production code, test, dependency, Runtime Core, Agent Bus, Finding, lifecycle state, native
manager, remote host or external service changed during RTS-044.

## Existing API and authority mapping

| Frozen fact | Current owner/API | Current implementation evidence | Focused regression evidence | Adjudication |
|---|---|---|---|---|
| Project, role, repository, state root and profile identity | Immutable installed profile snapshot resolved as `NodeProfile`, plus exact source/name registry | `node.py:46-107`, `255-370` | durable installed snapshot survives deleted authoring profile and retains exact source binding (`tests/test_node_service.py:232-324`) | `SATISFIED` |
| Native installation identity | `awf.node-managed-install.v1` and manager definition | RTS-045 binds manager ID and definition path to the deterministic current adapter target before trusting its digest (`node_service.py:_manager_target/_require_installed`) | managed start ordering plus manager-ID/self-consistent alternate-definition rejection (`tests/test_node_service.py`) | `SATISFIED` |
| Desired lifecycle intent | profile-bound, generationed `awf.node-desired-state.v1` | atomic desired state plus reconcile contract (`node.py:118-173`, `1330-1342`) | profile/digest/generation and stopped/running/crash behavior (`tests/test_node_service.py:95-162`) | `SATISFIED` |
| Process/incarnation evidence | process record plus listener lease and live observation | process binds PID, launch ID, profile/digest, state-root binding, role and repo; managed Windows foreground also binds kernel creation time (`node.py:1217-1296`) | distinct launcher/listener PID, launch-ID drift, dead/orphan preservation (`tests/test_node.py:172-245`, `780-845`) | `SATISFIED` |
| Exact local stop | native adapter after identity join | RTS-045 requires present exact process-record state-root path/binding with profile/digest/role/repo, PID, launch ID, lease, liveness and Windows creation identity before native signal | missing/partial/drifted roots across all three managers make zero native calls and preserve evidence (`tests/test_node_service.py`) | `SATISFIED` |
| Safe stale cleanup | exact dead record/lease pair only | exact-dead cleanup uses the same strict managed process identity; incomplete, mismatched or live facts remain preserved | root-drift table proves cleanup denial; prior orphan/live regressions remain green | `SATISFIED` |
| Factual lifecycle/status | `lifecycle_facts` and read-only status projection | configured, installed, running, connected and dispatch-capable remain orthogonal; one ordered support action is projected (`node.py:825-905`) | current/stale/missing fact table and mutation-free status (`tests/test_node.py:366-429`, `618-654`) | `SATISFIED` |
| Operator action surface | `awf node` adapter protocol and project facade | install/start/status/logs/restart/stop/uninstall are one bounded API over launchd, systemd and Task Scheduler (`node_service.py:402-412`, `945-961`) | manager rendering/routing, install/reinstall, exact denial and seven-command facade regression (`tests/test_node_service.py:426-650`, `tests/test_facade.py:120-173`) | `LOCALLY SATISFIED`; real managers remain open |
| Bus/Workflow/Finding boundary | Agent Bus owns transport; lifecycle owns only local process/incarnation | lifecycle status may label a bounded doctor observation but does not own delivery/ACK/retry/requeue/recovery/dispatch; Finding is absent from normal lifecycle authority | read-only facade test forbids dispatch, resume, Feedback and lifecycle mutations (`tests/test_facade.py:265-293`) | `SATISFIED` |

## Why no new AgentInstallation abstraction was added

The stable API is the exact operator behavior and ownership join, not a new Python class or a single
JSON filename. The Frozen contract explicitly records consolidation of lifecycle records as OQ-3
and forbids deleting a record until replacement fixtures prove equal exact-stop and three-OS
behavior. Adding a second `AgentInstallation` object now would duplicate current authority without
closing any real-manager evidence gap.

The smallest safe architecture remains the existing implementation shape. RTS-045 repaired the two
local defects without a new abstraction or representation.

## Focused current-head verification

An isolated Python 3.12 venv under temporary storage installed the repository's declared dev extras.
The first attempt used the system Python's obsolete pip and failed before project installation; the
current Python 3.12 environment then installed successfully. No repository dependency changed.

- `python -m compileall -q src/agent_workflow/node.py src/agent_workflow/node_service.py`: PASS.
- `python -m pytest -q tests/test_node.py tests/test_node_service.py tests/test_facade.py`:
  **64 passed, 1 skipped** in 1.70 seconds.
- The skip is the platform-opposite process-group branch; current cross-platform CI remains the
  owner of the complementary branch.
- RTS-045 added exactly two table-driven regressions for the missing authority cases. Final focused
  suite: **75 passed, 1 skipped**; full suite: **876 passed, 5 skipped**.
- Exact-head ordinary CI `32544625110` and Binary Feasibility `32544625218`: PASS.

## Closed independent review findings

The following preserves the initial `REQUEST_CHANGES` evidence; RTS-045 closes items 1 and 2.

1. Managed exact-stop validated profile path/digest, role, repository, PID, launch ID, lease,
   liveness and Windows creation identity, but did not validate the process record's explicit
   `state_root` and `state_root_sha256`. Missing or conflicting root facts could therefore reach a
   native manager signal when the lease and remaining fields matched.
2. `_require_installed` trusted the install record's own definition path/digest and did not compare
   `manager_id` or definition path with the deterministic current adapter target. A self-consistent
   but foreign target record could still project `current` and authorize an operation against the
   computed manager target.
3. Desired-state ordering is narrower than a generic “deny before mutation” claim. Managed start
   verifies current installation before writing desired `running`; managed stop intentionally writes
   desired `stopped` before entering the adapter. The repair gate concerns denial before native
   signal/native-manager mutation, not before the owner-intent desired-state write.

## Evidence that remains open

The following cannot be promoted to Phase 4B PASS:

1. Existing launchd/systemd/Task Scheduler unit tests use controlled manager calls and rendering;
   they do not prove a real current-head
   `install -> start -> status -> logs -> restart -> status -> exact stop -> uninstall` sequence.
2. The 2026-08-09 Windows evidence proves post-SSH survival, crash recovery, exact local stop and
   clean uninstall for its historical candidate, but predates later durable-profile and exact-stop
   repairs.
3. That report explicitly records logout/login or reboot recovery as not run.
4. Installed-wheel CI proves package/resource/CLI and selected PID-binding behavior, not real native
   manager mutation.
5. Binary feasibility remains `NO_GO_PRODUCTION_BINARY`; it is a distribution fence, not lifecycle
   acceptance.

## Phase 4B status and successor

Phase 4B remains open. Local exact-install/incarnation conformance, read-only status and strict
Bus/Workflow/Finding ownership are satisfied. The sole next gate is **RTS-046 fresh isolated
three-OS native-manager acceptance**.

RTS-046 must use disposable profile/config/state/log/manager identities and an already available
Agent Bus dependency. It must not install Agent Bus, operate business events, expand Agent Host,
onboarding or Finding, or change Runtime Core. Disruptive logout/login or reboot requires an
explicitly scheduled owner acceptance window.
