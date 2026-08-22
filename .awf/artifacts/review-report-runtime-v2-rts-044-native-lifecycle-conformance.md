# RTS-044 Independent Native Lifecycle Conformance ReviewReport

## Verdict

`REQUEST_CHANGES`

The current multi-record `awf node` surface is an acceptable single behavioral/API boundary and
does not need an `AgentInstallation` class, new Store or migration. Two local L3 identity joins are
incomplete, so RTS-044 cannot pass until one bounded repair is implemented and independently
re-reviewed.

## Findings

### P1 — managed process/incarnation root identity is incomplete

The Frozen contract and RTS-044 require process record, state-root binding, lease and live
observation to agree before native signal. `_bound_live_listener_pid` validates process-record
profile path/digest, role and repository but does not validate its `state_root` or
`state_root_sha256`. The lease is checked separately, so an explicitly missing or conflicting
process root can reach systemd, launchd or Task Scheduler signaling when the remaining identity
matches. Existing tests cover profile-digest drift but not process-root absence/drift with zero
native calls.

The exact-dead stale-state cleanup repeats the partial record check, so it may also remove a dead
record whose root evidence is not exact.

### P1 — installed manager target and definition path are not verified

The install record writes `manager_id`, definition path and definition digest. `_require_installed`
does not compare `manager_id` or definition path with the deterministic current adapter target; it
only hashes the record-selected path. A self-consistent foreign target record can therefore project
`current` and authorize a lifecycle action against the adapter's separately computed target. No
focused regression covers either drift.

### P2 — evidence wording exceeded implemented ordering

Managed start verifies current installation before writing desired `running`, but managed stop,
restart and uninstall intentionally write desired `stopped` before adapter validation. The exact
claim is denial before native signal or native-manager mutation, not denial before every local
desired-state mutation. The conformance report was corrected accordingly.

## Accepted boundaries

- Multiple existing lifecycle records may jointly implement one behavior/API boundary; Frozen OQ-3
  does not require a new class or consolidation.
- Read-only lifecycle/status behavior, Agent Bus transport ownership, Workflow authority and
  optional Finding separation show no scope violation.
- Historical Windows, mocked manager and binary No-Go evidence is correctly excluded from current
  Phase 4B PASS.
- The focused **64 passed, 1 skipped** run is proportionate but cannot cover the two missing cases.
- Phase 4B correctly remains open.

## Required repair

Freeze one bounded TaskCard that:

1. requires strict current process-record state-root path/binding for managed stop and exact-dead
   cleanup while leaving explicitly scoped legacy compatibility unchanged elsewhere;
2. compares install-record `manager_id` and definition path to the current deterministic adapter
   identity before treating installation as current or signaling its target; and
3. adds only focused regressions proving missing/drifted root and manager-target/definition-path
   facts produce zero native calls.

No AgentInstallation abstraction, record migration, native-manager operation, Agent Bus change or
product decision is required.

<!-- awf-review-report
{
  "verdict": "REQUEST_CHANGES",
  "reviewed_head": "146853c",
  "critical": 0,
  "high": 2,
  "medium": 1,
  "low": 0,
  "next_gate": "runtime-v2-rts-045-exact-lifecycle-identity-repair"
}
-->
