# RTS-046 Independent Native-Manager Acceptance ReviewReport

## Verdict

`PASS_FOR_BLOCKED_ADJUDICATION`

Zero remaining findings after one focused evidence-safety repair. Evidence supports macOS and
non-disruptive Windows PASS, Linux `EXTERNAL_BLOCKED`, and Windows logout/login
`BLOCKED_BY_OWNER_AUTHORIZATION`. It does not support Phase 4B PASS.

## Adjudication

1. **macOS `-01` — permanent failure evidence.** The fresh installed venv failed because native argv
   resolved its interpreter symlink to a base Python without Agent Workflow. RTS-047 repaired this
   exact defect; `-01` is not acceptance.
2. **macOS `-02` — independent external block.** A completely fresh scope entered installed AWF,
   proving RTS-047, then stopped before stable incarnation because the independent Agent Bus client
   lacks required `--on-argv`. Current listener construction makes structured argv unconditional;
   legacy `--on` fallback would weaken the boundary.
3. **Windows — correctly pre-mutation blocked.** Entry identity, console-user and Task Scheduler
   facts were suitable, but the same Agent Bus capability was absent. No profile/definition/service/
   process/lease was created. Logout/login also lacks an owner-authorized window.
4. **Linux — correctly pre-install blocked.** No audited suitable host already combined linger and
   AWF/Bus configuration. Enabling or deploying either is explicitly outside scope.
5. **Cleanup/no-event — supported.** Both macOS scopes used normal exact uninstall; definitions,
   install records, process records and leases were absent, while failure logs remained. No model,
   business event, ACK/retry/requeue/recovery or dispatch occurred.
6. **Phase result — not complete.** The plan requires real action sequences on all three managers and
   live Windows post-SSH/login evidence. Those facts are absent and cannot be inferred from CI,
   doctor, mocks or the repair.

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

Linux remains pre-install blocked, and Windows logout/login was not attempted.

Initial focused review found real usernames in executable paths. They were replaced by `$HOME`,
`%LOCALAPPDATA%` and `%TEMP%` expressions while retaining exact source/hash/capability/install-type/
version provenance. Focused re-review closed the finding.

## Legal continuation

External/operator prerequisites must be aligned without expanding Agent Workflow ownership:

- an already-lingering Linux user host with existing AWF/Bus configuration; and
- an explicitly scheduled Windows logout/login window.

RTS-046 may then continue only with another fresh identity. Phase 5 is not authorized.

<!-- awf-review-report
{
  "verdict": "PASS_FOR_BLOCKED_ADJUDICATION",
  "critical": 0,
  "high": 0,
  "medium": 0,
  "low": 0,
  "task_status": "PARTIAL_PASS_LINUX_EXTERNAL_BLOCKED",
  "owner_status": "BLOCKED_BY_OWNER_AUTHORIZATION",
  "phase_4b": "OPEN",
  "phase_5": "NOT_STARTED",
  "closed_high": 1,
  "focused_rereview": "PASS"
}
-->
