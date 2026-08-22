# RTS-045 Exact Lifecycle Identity Repair ImplementationReport

## Result

Candidate repair complete for the two independent RTS-044 findings. The existing lifecycle API and
record formats are unchanged; managed native authorization now joins the missing exact facts.

## Repair

### Managed process/incarnation root

One shared managed-record predicate now reuses `node._record_matches_profile` and additionally
requires both process-record `state_root` and `state_root_sha256` to be present and exactly equal to
the current canonical profile root/binding.

Both `_bound_live_listener_pid` and `_clear_exact_dead_stale_state` use that predicate. Missing,
partial or drifted process-root facts therefore deny before systemd, launchd or Task Scheduler calls
and cannot be removed as exact dead state. The broader legacy/session compatibility behavior in
`node._record_matches_profile` is unchanged.

### Installed manager target

One small helper derives the current manager identifier and definition path from the existing
Systemd, Launchd or Task Scheduler adapter properties. `_require_installed` now binds those two
values in addition to its existing profile, executable, action argv and content-digest facts.
`_require_upgrade_target` retains its bounded stale-action purpose but also requires the same
deterministic definition target and rejects a caller/record manager-ID mismatch.

A record-selected alternate definition file is no longer authoritative even when its bytes and
recorded digest agree.

## Focused regressions

Two table-driven tests were added:

1. missing, partial and drifted process-root evidence across all three manager adapters produces
   zero native calls, preserves the process record and is ineligible for exact-dead cleanup;
2. manager-ID drift and a self-consistent alternate definition path both fail current-install and
   upgrade-target validation.

No existing test was weakened or duplicated into another module.

## Verification

- Python 3.12 compileall: PASS.
- `tests/test_node_service.py tests/test_node.py tests/test_facade.py`:
  **75 passed, 1 skipped**.
- Ruff: PASS.
- Ruff format check: PASS.
- `git diff --check`: PASS.
- Full repository suite: **876 passed, 5 skipped**.
- Exact-head ordinary CI `32544625110`: PASS across Linux, Windows recovery/configuration, macOS
  runtime and all three installed-wheel jobs.
- Exact-head Binary Feasibility `32544625218`: PASS across all five native cells, all five retained
  Rust oracle cells and both aggregates.
- Production diff: 33 additions / 16 deletions, net +17 and within the 45-line budget.
- Focused test diff: 103 additions, within the 180-line budget.
- No dependency, format, persistent representation, migration or external operation was added.

The skipped test is the platform-opposite process-group branch; ordinary cross-platform CI owns its
complementary execution.

## Scope

Changed implementation paths are only `src/agent_workflow/node_service.py` and
`tests/test_node_service.py`, plus frozen TaskCard/evidence artifacts. No native manager, remote
host, Agent Bus, event, Finding, Runtime Core, migration, launcher or production state was operated.

## Review gate

Independent L3 Gate Review returned `PASS` with zero findings at `37ea274`. It verified denial before
native calls, unchanged legacy/session compatibility, preserved install/reinstall/upgrade behavior
and closure of both RTS-044 findings.
Phase 4B remains open after this repair; fresh real three-OS native-manager and Windows login
acceptance remains a separate gate.
