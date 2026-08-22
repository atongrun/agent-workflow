# TaskCard: RTS-045 Exact Lifecycle Identity Repair

## Task ID

runtime-v2-rts-045-exact-lifecycle-identity-repair

## Goal

Repair the two local exact-install/incarnation joins found by the independent RTS-044 Gate Review:

1. managed exact-stop and exact-dead cleanup must require the process record's current canonical
   state-root path and binding in addition to the existing profile/role/repo/lease/live identity;
2. an installed lifecycle record is current only when its manager identifier and definition path
   match the deterministic current native adapter target, in addition to the existing content digest
   and executable/profile bindings.

This is a bounded L3 authority repair inside the existing lifecycle shape. It creates no new
abstraction, state format, migration or external operation.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base finding head**: `ebfc4e4`
- **Task branch**: `codex/runtime-v2-rts-045-exact-lifecycle-identity-repair`
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`, lifecycle/process section
- **Finding evidence**:
  `.awf/artifacts/review-report-runtime-v2-rts-044-native-lifecycle-conformance.md`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4B

## Frozen repair behavior

### Strict managed process identity

- Reuse the canonical current `node._record_matches_profile` semantics for profile, digest, role,
  repository and explicit state-root mismatch.
- Managed native stop and exact-dead cleanup additionally require both `state_root` and
  `state_root_sha256` to be present and exactly equal to the current canonical profile root/binding.
- Do not change the legacy compatibility behavior of `node._record_matches_profile` or session
  lifecycle paths; strict presence is scoped to managed native signal/cleanup authorization.
- Missing, partial or conflicting process-root evidence denies before native-manager signal and is
  preserved. It cannot be auto-repaired from the lease.

### Exact installed manager target

- Derive expected manager identifier and definition path from the current deterministic adapter for
  the exact profile and resolved native manager; do not add a registry or duplicate path formula.
- `_require_installed` requires exact `manager_id` and definition path before trusting the definition
  digest or authorizing lifecycle actions.
- Upgrade stop may tolerate the already documented stale action argv, but its target identity must
  still bind exact manager, manager identifier, profile and definition path.
- A record-selected alternate file with a self-consistent digest does not authorize the current
  manager target.

## Writable scope

- `docs/tasks/runtime-v2-rts-045-exact-lifecycle-identity-repair.md`
- `src/agent_workflow/node_service.py`
- `tests/test_node_service.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-045-exact-lifecycle-identity-repair.md`
- `.awf/artifacts/review-report-runtime-v2-rts-045-exact-lifecycle-identity-repair.md`

After implementation, CI and independent Review PASS, closeout may additionally update:

- `docs/tasks/runtime-v2-rts-045-exact-lifecycle-identity-repair-report.md`
- `docs/tasks/runtime-v2-rts-044-native-lifecycle-conformance-report.md`
- `.awf/artifacts/review-report-runtime-v2-rts-044-native-lifecycle-conformance.md`
- `docs/plans/runtime-v2-development-plan.md`
- `HANDOFF.md`
- `ROADMAP.md`

## Prohibited actions

- Editing `node.py`, Runtime Core, facade/CLI, status, scripts, schemas, workflows, packaging,
  dependencies or any other test module.
- New `AgentInstallation` class, Store, record, registry, framework, daemon, scheduler, Agent Host,
  onboarding layer, generic extension point or compatibility fallback.
- Record consolidation/deletion, dual write, state migration, guessed repair or silent adoption.
- Native manager, remote host, logout/login, reboot, Agent Bus, event, payload, ACK/retry/requeue,
  Finding, provider, Git/GitHub, launcher, default, release or production-state operation.
- Weakening exact identity, accepting legacy missing root at managed stop, or treating lease facts as
  a replacement for the process record.

## Acceptance criteria

- [x] Task ID equals branch leaf and every changed path is in the frozen writable scope.
- [x] Managed stop and exact-dead cleanup require present, exact process-record state-root path and
      binding while leaving `node._record_matches_profile` and session compatibility unchanged.
- [x] Missing, partial and explicitly drifted process-root facts deny before any systemd, launchd or
      Task Scheduler native call and leave evidence intact.
- [x] `_require_installed` rejects manager-ID drift and a record-selected alternate definition path,
      even when the alternate file and digest are self-consistent.
- [x] Upgrade stop retains its bounded stale-action-record purpose but rejects manager identifier or
      definition-path target drift before native calls.
- [x] Existing current install/stop/reinstall/upgrade behavior remains green for all three adapters.
- [x] Only one or two focused table-driven regressions are added; no broad test-matrix duplication.
- [x] Production implementation grows by no more than 45 nonblank/noncomment lines and focused tests
      by no more than 180; no dependency or persistent representation is added.
- [x] Focused lifecycle tests, Ruff/format and exact-head ordinary cross-platform CI pass.
- [x] Independent L3 Gate Review returns `PASS`; any semantic repair receives focused re-review.
- [x] RTS-044 focused re-review may then close local conformance, while Phase 4B remains open for a
      separately frozen fresh three-OS native-manager acceptance.

## Verification

```text
python -m compileall -q src/agent_workflow/node_service.py tests/test_node_service.py
python -m pytest -q tests/test_node_service.py tests/test_node.py tests/test_facade.py
ruff check src/agent_workflow/node_service.py tests/test_node_service.py
ruff format --check src/agent_workflow/node_service.py tests/test_node_service.py
git diff --check
```

## Failure handling

- Routine test/lint failure: repair within the frozen source/test scope and rerun the affected check.
- Need to change record formats, migrate state, modify `node.py` compatibility or add another owner:
  stop for architecture/owner decision.
- Native manager or external proof need: leave for the separately frozen live acceptance; do not
  operate it here.

## Required output

- one minimal exact-identity repair;
- one or two focused regressions;
- ImplementationReport and independent ReviewReport;
- final RTS-044 focused conformance re-review and the next live-acceptance boundary.
