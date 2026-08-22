# TaskCard: RTS-044 Native Lifecycle Conformance Gate

## Task ID

runtime-v2-rts-044-native-lifecycle-conformance

## Goal

Adjudicate the existing installed `awf node` lifecycle surface against the local, authority-critical
parts of the Frozen Runtime v2 Phase 4B contract. Reuse current implementation and accepted evidence,
run focused current-head conformance tests, and name the exact remaining fresh native-manager
acceptance without adding another lifecycle abstraction or representation.

This TaskCard is an evidence/conformance milestone. It does not claim Phase 4B complete and does not
operate a native manager, remote host, Agent Bus delivery, business event or production state.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `7b120bf0d613de0ca09f0cae859e78f9faa3aaf0`
- **Task branch**: `codex/runtime-v2-rts-044-native-lifecycle-conformance`
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`, lifecycle/process section
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4B
- **Current implementation**: `src/agent_workflow/node.py` and
  `src/agent_workflow/node_service.py` (read-only for this TaskCard)

Phase 4A is closed. Agent Bus remains an independently versioned communication dependency. Finding
remains an optional maintenance capability outside normal `run/status/stop`; neither boundary is
changed here.

## Frozen adjudication boundary

The independent Reviewer must determine whether the existing lifecycle API already proves:

1. one public operator surface (`awf node` plus project-level `start/status/stop`) over exact
   installed-profile, native-definition, desired-state and process/incarnation facts;
2. immutable installed profile/registry binding and an install record that binds manager,
   profile/source/digest, definition/digest, executable/digest, AWF version and exact action argv;
3. running/incarnation identity as a join of profile digest, role, repository, state root, launch ID,
   process record, listener lease, liveness and Windows process-creation identity where available;
4. denial before native signal or mutation when any required identity is absent, stale, corrupt or
   mismatched; PID, process name, desired state or liveness alone is never sufficient;
5. read-only lifecycle/status projection that keeps configured, installed, running, connected and
   dispatch-capable orthogonal and names one safe support action;
6. no lifecycle ownership of business payloads, delivery, ACK, retry, requeue, recovery, dispatch,
   Workflow Stage, RunStore or optional Finding state; and
7. the existing multiple lifecycle records remain compatibility evidence under Frozen OQ-3 rather
   than a reason to invent or migrate to a new `AgentInstallation` record.

The Review must also identify evidence that cannot be promoted to current Phase 4B PASS:

- mocked/render-only manager tests are not real launchd/systemd/Task Scheduler acceptance;
- the 2026-08-09 Windows proof predates later durable-profile/exact-stop changes;
- Windows logout/login or reboot recovery is explicitly untested;
- binary feasibility remains a distribution No-Go and is not lifecycle acceptance.

## Writable scope

- `docs/tasks/runtime-v2-rts-044-native-lifecycle-conformance.md`
- `docs/tasks/runtime-v2-rts-044-native-lifecycle-conformance-report.md`
- `.awf/artifacts/review-report-runtime-v2-rts-044-native-lifecycle-conformance.md`
- `docs/plans/runtime-v2-development-plan.md` (gate status/next TaskCard only after Review PASS)
- `HANDOFF.md` (gate status/next TaskCard only after Review PASS)
- `ROADMAP.md` (gate status/next TaskCard only after Review PASS)

## Prohibited actions

- Any edit under `src/`, `scripts/`, `tests/`, schemas, workflows, packaging, dependencies or CI.
- A new `AgentInstallation` class, lifecycle Store, registry, daemon, scheduler, Agent Host, plugin
  framework, generic onboarding layer or extension framework.
- Consolidation, migration, dual write, deletion or cleanup of profile, install, desired, process,
  lease, log or compatibility records.
- Native manager install/start/restart/stop/uninstall, logout/login, reboot or remote-host operation.
- Agent Bus installation/modification; event send/read/ACK/retry/requeue/recover/dispatch; retained or
  business payload access.
- Runtime Core, transport, RunStore, provider, workspace/Git, Artifact, Finding Phase B, launcher,
  distribution, default, release or production-state change.
- Treating old live evidence, green CI, PID/liveness or pending-zero as stronger authority than it is.

## Acceptance criteria

- [ ] Task ID equals the branch leaf and every changed path is inside the writable scope.
- [ ] A current-source evidence matrix maps each frozen adjudication item to exact implementation,
      focused regression and prior independent/live evidence without duplicating its claim.
- [ ] Focused current-head `node`, `node_service` and facade lifecycle tests pass without adding tests.
- [ ] The report concludes whether the existing multi-record `awf node` surface satisfies the local
      AgentInstallation/incarnation API criterion without a new abstraction.
- [ ] Exact-stop authorization is shown to require the full identity join and to deny before native
      signal for incomplete, stale or mismatched evidence.
- [ ] Lifecycle/status read-only and Bus/Workflow/Finding ownership boundaries remain unchanged.
- [ ] The report explicitly leaves real three-manager actions and fresh Windows logout/login evidence
      open; Phase 4B is not marked complete.
- [ ] Independent Gate Review returns `PASS`; documentation-only findings receive focused repair and
      re-review only when materially necessary.
- [ ] `git diff --check`, credential/private-path scan and documentation link checks pass.
- [ ] The sole successor is a separately frozen fresh isolated three-OS native-manager acceptance;
      no remote or disruptive operation is authorized by this card.

## Verification

```text
python -m compileall -q src/agent_workflow/node.py src/agent_workflow/node_service.py
python -m pytest -q tests/test_node.py tests/test_node_service.py tests/test_facade.py
git diff --check
```

The test run protects existing behavior only; it must not be expanded with duplicate cases. Full CI
is required only if current-head repository policy triggers it for the final documentation candidate.

## Failure handling

- Documentation/evidence mismatch: repair narrowly and rerun the affected static check.
- Focused test failure in unchanged production code: diagnose; do not edit implementation in this
  TaskCard. Freeze a separate bounded repair only if the defect is local and the Frozen boundary
  remains intact.
- Need for new authority, record migration, Agent Bus behavior or product scope: stop for an ADR or
  owner decision.

## Required output

- one lifecycle conformance report;
- one independent Gate ReviewReport;
- minimal plan/HANDOFF/ROADMAP update after PASS naming the fresh live acceptance successor.
