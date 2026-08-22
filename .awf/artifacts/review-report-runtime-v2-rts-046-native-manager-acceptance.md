# RTS-046 Independent Native-Manager Acceptance ReviewReport

## Verdict

`PASS`

Final independent closeout review found zero blocking findings. Fresh valid macOS, owner-corrected
`tx-vps` Linux, Windows Task Scheduler/post-SSH and Windows `-05` logout/login evidence jointly
satisfy every frozen Phase 4B exit criterion. RTS-046 and Phase 4B are complete. Phase 5 did not
start.

## Initial blocked adjudication (historical)

1. **macOS `-01` — permanent failure evidence.** The fresh installed venv failed because native argv
   resolved its interpreter symlink to a base Python without Agent Workflow. RTS-047 repaired this
   exact defect; `-01` is not acceptance.
2. **macOS `-02` — independent external block.** A completely fresh scope entered installed AWF,
   proving RTS-047, then stopped before stable incarnation because the independent Agent Bus client
   lacks required `--on-argv`. Current listener construction makes structured argv unconditional;
   legacy `--on` fallback would weaken the boundary.
3. **Windows — initially pre-mutation blocked.** Entry identity, console-user and Task Scheduler
   facts were suitable, but the same Agent Bus capability was absent. No profile/definition/service/
   process/lease was created. Logout/login also lacks an owner-authorized window.
4. **Linux — initial audit incomplete.** The later `la-codex-node` assumption was invalid and is
   withdrawn; final valid evidence comes only from owner-corrected `tx-vps` scope `-06`.
5. **Cleanup/no-event — supported.** Both macOS scopes used normal exact uninstall; definitions,
   install records, process records and leases were absent, while failure logs remained. No model,
   business event, ACK/retry/requeue/recovery or dispatch occurred.
6. **Phase result at that time — not complete.** Real three-manager and Windows login facts were then
   absent and could not be inferred from CI, doctor, mocks or the repair. Later fresh scopes close
   those exact gaps below.

## Owner-authorized client-skew continuation

Agent Bus master `6ca8f281...` and PR #27 were re-verified locally. Master contains the pinned
producer/consumer contracts and `--on-argv`; formal v0.3.0 does not, while both report version 0.3.0.
Credential-free provenance proved stale macOS/Windows installations and exact isolated compatible
clients without modifying the old clients, server, database, configuration values, events or ACK
state.

Fresh `rts046-live-20260822-03` then proved:

- macOS launchd full lifecycle, distinct restart incarnation, exact stop and uninstall;
- Windows Task Scheduler session-A-to-B survival, creation identity, distinct restart incarnation,
  exact stop and uninstall; and
- no model, business event or legacy handler fallback.

At that intermediate point, Linux remained pre-install blocked and Windows logout/login had not run.

Owner-authorized `-04` performed a real Windows logout/login and exposed transient login readiness
plus PID-reuse stale convergence. Status rejected the reused PID; normal stop wrote desired stopped
then denied without signal. RTS-048 repaired only bounded pre-listener readiness and strict
creation-aware stale cleanup. Independent re-review, exact-head CI and Binary Feasibility passed.
Reviewed code then removed only failed `-04` manager evidence with no PID signal; `-04` remains
failure evidence forever.

The then-assumed Linux target and its claimed restore facts are now invalidated by the owner topology
correction and contribute nothing to acceptance.

Initial focused review found real usernames in executable paths. They were replaced by `$HOME`,
`%LOCALAPPDATA%` and `%TEMP%` expressions while retaining exact source/hash/capability/install-type/
version provenance. Focused re-review closed the finding.

## Historical interim continuation

At that intermediate point, the remaining prerequisites were:

- a platform-approved credential path into the exact disposable Linux root; and
- a new explicitly scheduled Windows logout/login window for fresh `-05`.

RTS-046 later continued through fresh `-05` and owner-corrected `-06`. Phase 5 remained unauthorized.

## Final owner-corrected Linux closeout review

The owner clarified that `la-codex-node` is not a real Agent Workflow host/topology. Every claimed
Linux fact from that assumption is now explicitly invalidated and excluded in the TaskCard,
acceptance report, ImplementationReport, HANDOFF, ROADMAP and plan. It contributes nothing to PASS.

Fresh `rts046-live-20260822-06` instead used the existing `tx-vps` root/systemd-user and unchanged
system Agent Bus Server. Independent review verified:

- exact Workflow `87ceb3a` and compatible Bus `6ca8f281...` provenance;
- strict no-model doctor and full install/start/status/logs/restart/status/exact-stop/uninstall;
- first PID/lease/MainPID `1681549`, launch `19375d...`, followed by distinct PID/lease/MainPID
  `1682597`, launch `2b2a0d...`, with stable profile/repository/state-root identity;
- pre-stop exact identity join, stopped generation 5 and no PID/liveness-only authorization claim;
- normal uninstall plus exact volatile unit-cache reset, then complete disposable root/config/client/
  snapshot/process/lease/definition/install/registry/unit absence;
- linger and enabled-user-unit count/hash restored exactly; and
- Agent Bus Server PID/start/health/unit/env hashes unchanged, with no event, queue, database, ACK,
  retry, requeue, provider or model operation.

Together with valid macOS `-03`, Windows `-03`/`-05`, RTS-044/045 conformance, RTS-047 venv repair
and RTS-048 login recovery, this satisfies all Phase 4B exit criteria. Documentation/evidence is the
only repository change, secrets/endpoints are absent, and Phase 5 remains explicitly out of scope.

<!-- awf-review-report
{
  "verdict": "PASS",
  "critical": 0,
  "high": 0,
  "medium": 0,
  "low": 0,
  "task_status": "COMPLETE",
  "owner_status": "NO_OPEN_PHASE_4B_OWNER_ACTION",
  "phase_4b": "CLOSED",
  "phase_5": "NOT_STARTED",
  "closed_high": 1,
  "focused_rereview": "PASS",
  "final_closeout_review": "PASS",
  "rts048_ci_run": "32551160937",
  "rts048_binary_run": "32551160941"
}
-->
