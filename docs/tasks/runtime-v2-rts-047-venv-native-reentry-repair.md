# TaskCard: RTS-047 Native Venv Re-entry Repair

## Task ID

runtime-v2-rts-047-venv-native-reentry-repair

## Goal

Repair the executable-identity defect exposed by the first real RTS-046 LaunchAgent start: native
manager definitions and install records must preserve the absolute venv interpreter path instead of
resolving its symlink to a base interpreter where Agent Workflow is not installed.

The repair retains exact executable-byte hashing, action argv binding, manager-definition identity
and all existing lifecycle authority. It changes no state format, API or product boundary.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Finding head**: `11b0f34`
- **Task branch**: `codex/runtime-v2-rts-047-venv-native-reentry-repair`
- **Failure evidence**:
  `.awf/artifacts/impl-report-runtime-v2-rts-046-native-manager-acceptance.md`
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`, lifecycle/process section
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 4B

## Frozen behavior

- Introduce at most one small internal helper that returns `sys.executable` as a normalized absolute
  path without resolving symlinks.
- Use that same path for launchd/systemd/Task Scheduler action argv and install-record `python`.
- Continue hashing the executable through that path and validate the hash at every current-install
  check. Symlink traversal for reading bytes is permitted; path identity must remain the venv shim.
- Preserve Windows venv redirector behavior and existing process/incarnation identity unchanged.
- Preserve deterministic manager ID/definition path, action argv, AWF version and profile bindings.
- Missing executable, byte drift, argv drift or definition drift remains fail-closed.

## Writable scope

- `docs/tasks/runtime-v2-rts-047-venv-native-reentry-repair.md`
- `src/agent_workflow/node_service.py`
- `tests/test_node_service.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-047-venv-native-reentry-repair.md`
- `.awf/artifacts/review-report-runtime-v2-rts-047-venv-native-reentry-repair.md`

After independent Review and CI PASS, closeout may additionally update:

- `docs/tasks/runtime-v2-rts-047-venv-native-reentry-repair-report.md`
- `.awf/artifacts/impl-report-runtime-v2-rts-046-native-manager-acceptance.md`
- `docs/tasks/runtime-v2-rts-046-native-manager-acceptance.md` (fresh successor scope only)
- `docs/plans/runtime-v2-development-plan.md`
- `HANDOFF.md`
- `ROADMAP.md`

## Prohibited actions

- Editing Runtime Core, node.py, facade/CLI/status, scripts, schemas, workflows, packaging,
  dependencies or another test module.
- PYTHONPATH injection, base-interpreter installation, source-checkout fallback, manual definition
  editing or executable-copy workaround.
- New lifecycle abstraction, record/Store, migration, compatibility fallback, daemon, Agent Host,
  onboarding, Finding Phase B, launcher or distribution design.
- Native manager, remote host, Agent Bus, event, payload, model, logout/login, reboot or production
  operation in this repair TaskCard.
- Weakening executable/profile/manager/definition/process/lease identity or checksum validation.

## Acceptance criteria

- [x] Task ID equals branch leaf and every changed path is within frozen scope.
- [x] Native action argv and install record preserve an absolute venv shim path byte-for-byte and do
      not replace it with the resolved base interpreter path.
- [x] Executable SHA-256 validation still reads the invoked path and rejects byte drift/missing files.
- [x] launchd, systemd and Task Scheduler render the same preserved interpreter identity.
- [x] Existing current install, upgrade, exact-stop and Windows identity tests remain green.
- [x] One focused symlink regression protects argv, definition and install-record/current validation;
      no broad matrix or duplicated lifecycle fixture is added.
- [x] Production net growth is at most 25 nonblank/noncomment lines; focused test growth at most 100;
      no dependency or representation is added.
- [x] Focused/full tests, Ruff/format and exact-head cross-platform CI pass.
- [x] Independent L3 Gate Review returns `PASS`; semantic findings receive focused re-review.
- [x] RTS-046 resumes only with a fresh acceptance identity; failed scope `-01` remains failure
      evidence and never contributes to PASS.

## Verification

```text
python -m compileall -q src/agent_workflow/node_service.py tests/test_node_service.py
python -m pytest -q tests/test_node_service.py tests/test_node.py tests/test_facade.py
ruff check src/agent_workflow/node_service.py tests/test_node_service.py
ruff format --check src/agent_workflow/node_service.py tests/test_node_service.py
git diff --check
```

## Failure handling

- Routine code/test failure: repair inside this scope and rerun only affected checks.
- Need for state migration, API change, base-interpreter install or external manager workaround: stop
  for architecture/owner decision.
- Successful repair does not authorize Windows logout/login or Linux linger changes.

## Required output

- minimal executable-identity repair and focused regression;
- ImplementationReport and independent ReviewReport;
- closeout authorizing one fresh RTS-046 continuation identity only.
