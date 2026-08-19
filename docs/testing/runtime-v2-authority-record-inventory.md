# RTS-001 Current Authority, Evidence, and Record Inventory

Status: **Draft inventory** for `main@0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2`

This inventory counts persistent record *families*, not filenames. Multiplicity is explicit: a
label that occurs once per run, delivery, role, host, or profile is not “one state object” in an
operational deployment. External truth is listed separately and is never hidden to reduce the
reported count.

Classifications:

- `intent`: owner-authorized desired work/configuration;
- `authority`: may permit/deny a Workflow or lifecycle mutation;
- `evidence`: durable observation required to prove an external/local effect;
- `derived`: rebuildable read-only projection;
- `cache`: time-bounded reusable observation that cannot authorize when stale;
- `external`: fact owned outside Agent Workflow.

Many files contain more than one classification. The table names the strongest semantic role and
notes secondary roles.

## 1. Workflow, invocation, and delivery records

| Family | Class | Logical owner | Current representation / creator | Multiplicity | Required joins / recovery role | Evidence |
|---|---|---|---|---|---|---|
| TaskCard | intent | Owner/Planner | committed Markdown plus `awf-postflight`; `scripts/awf_taskcard.py`, `awf_role.py::parse_postflight_contract` | per task/version | RunManifest, compiled contract, exact Git commit, report paths, selections | `constitution.md` §5; `tests/test_awf_role.py::test_parse_valid_contract` |
| Owner RunManifest | intent | Owner | `.awf/run-manifest.json`; `src/agent_workflow/manifest.py` and CLI setup | per run/project | TaskCard, profiles, authority manifest, repository, routes, state root | `docs/tasks/compiled-run-consumption-gate-implementation-report.md` |
| Compiled RunContract/report | evidence + gate input | Compiler/owner | `.awf/run-contract.json`; `src/agent_workflow/manifest.py` | per compiled run intent | canonical hashes of manifest, TaskCard, profiles, authority/state root | `docs/tasks/read-only-run-contract-compiler.md` |
| Authority manifest | authority | Owner | `awf.authority-manifest.v1`; `scripts/awf_control_plane.py::load_authority_manifest` | per run/config | hash/allowed operations embedded in context packet | `tests/test_control_plane.py::test_checked_in_authority_manifest_is_bound_into_recovery_packet` |
| Strict operations configuration | configuration authority, not stage authority | Local OS user | owner-only `dispatch.env`; `scripts/awf_config.py` | normally per user/config target | Bus endpoint/token references, runtime binaries and profile config; joins listener/preflight/Feedback but cannot authorize Workflow stage | `docs/tasks/config-recovery-maturity-implementation-report.md` |
| RunLedger | authority | logical Run transition writer | `<state>/control-plane/runs/<run>/ledger.json`; `RunLedger` | per run | context packet, delivery gate decisions, terminal, later PR/CI/merge evidence | `tests/test_control_plane.py::test_packet_is_bounded_and_recoverable_from_a_fresh_session` |
| Context packet sidecar | derived/cache mirror | Run transition writer | `context-packet.json`; the authoritative copy/digest is embedded in the ledger | per run, replaced per transition | diagnostic/recovery handoff projection only; `RunLedger.recover` reads and verifies the embedded packet, and the mirror may briefly lead the ledger after a crash | same test; `RunLedger.recover` |
| Run summary | derived | Run transition writer | `summary.json`; `RunLedger._terminal_summary` | per terminal run | ledger terminal evidence only; cannot authorize recovery | `tests/test_control_plane.py::test_terminal_ledger_and_summary_are_durable_and_idempotent` |
| Gate decisions/events/transitions | authority audit | Run transition writer | arrays inside RunLedger | per input attempt/decision | delivery ID/hash, route, stage, budget, terminal state | `tests/test_control_plane.py::test_gate_rejects_over_budget_terminal_and_replay` |
| RunEvidence log | evidence | executing handler | canonical v3 `<state>/event-<event-id>/handler.log`, with legacy default-root layout under `runs/event-<event-id>`; `awf_role.py::RunEvidence` | per event/role input (one current file pair per event directory) | process PID/exit, handler phases and trusted effects; not itself stage authority | `docs/tasks/durable-handler-exit-evidence.md` |
| Handler result | evidence | executing handler | atomic `result.json` beside the RunEvidence log | per event/role input | latest aggregate handler phase/rc and process evidence | `tests/test_awf_role.py::test_handler_main_persists_exit_for_success_and_failure` |
| Recovery checkpoint | authority + evidence | executing trusted handler | `<state>/checkpoint/<role>/<delivery-key-hash>.json` | per input delivery/role/host | immutable input/provenance/state root; provider/workspace/result/import/Git/outbox phases | `awf_role.py::_RECOVERY_PHASES_BY_ROLE`; crash replay matrix test |
| Business outbox | intent + evidence | source trusted handler | `<state>/outbox/<role>/<delivery-key-hash>.json` | per input delivery requiring handoff | immutable downstream envelope, provenance, checkpoint, send attempt/status | `tests/test_awf_role.py::test_v3_outbox_persists_complete_provenance_tuple` |
| Business inbox | authority/evidence | destination trusted handler | `<state>/inbox/<role>/<delivery-id-hash>.json` | per completed input delivery | exact delivery ID/hash and role; permits identical handler replay to return success | `awf_role.py::complete_inbox/inbox_completed` |
| Durable model workspace | evidence + local effect surface | executing handler | event-scoped clone under state root | per provider invocation; implement workspace may span one exact rework | checkpoint workspace path/manifest, source commit, imported tree, Git-control digest | `docs/tasks/implement-rework-workspace-transition-implementation-report.md` |
| Workspace/Git manifests | evidence | trusted handler | facts embedded in checkpoint plus Git object database | per invocation/transition | exact workspace, semantic index, tree, commit and no-remotes facts | `tests/test_awf_role.py::test_trusted_commit_advances_same_durable_model_workspace` |
| Artifact files and normalized objects | evidence | provider produces; trusted validator imports | committed ImplementationReport/ReviewReport plus checkpoint/terminal hashes | per task attempt/review | TaskCard path allowlist, raw file hash, canonical object hash, commit/PR tuple | `tests/test_status.py::test_review_artifact_distinguishes_file_and_canonical_hashes` |
| Terminal evidence | authority | Run transition writer/Decider | terminal object in ledger plus summary projection | per run | ReviewReport, artifacts, exact PR tuple; CI/merge remain later distinct facts | `tests/test_awf_role.py::test_architect_persists_terminal_ledger_and_summary_before_inbox` |
| Feedback outbox | intent/evidence, independent | source Finding capture | `awf.feedback-outbox.v1` under state root | per occurrence | exact pending/sent occurrence; no business completion join | `scripts/awf_feedback.py` |
| Feedback ingest | evidence/dedupe, independent | reporter handler | `awf.feedback-ingest.v1` under state root | per ingested occurrence | durable before reporter handler success/ACK | `docs/tasks/dogfood-finding-phase-a-implementation-report.md` |
| Feedback rejection | evidence, independent | source capture | `awf.feedback-rejection.v1` | per rejected candidate | bounded diagnosis only; cannot fail or complete business work | `scripts/awf_feedback.py` |

## 2. Host lifecycle and readiness records

| Family | Class | Logical owner | Current representation / creator | Multiplicity | Required joins / recovery role | Evidence |
|---|---|---|---|---|---|---|
| Authoring NodeProfile | intent | Owner | credential-free profile JSON in platform config home | per project/role/profile | repository/remotes, tool/model, lifecycle, state-root; source for explicit install/upgrade | `src/agent_workflow/node.py::load_profile` |
| Installed profile snapshot | authority | host lifecycle manager | content-addressed snapshot in AWF config home | per installed profile digest | source/name registries, install record, native definition | `docs/tasks/durable-profile-exact-stop-implementation-report.md` |
| Profile source/name registries | authority index | host lifecycle manager | credential-free registry files | per source alias/name | select exactly one installed snapshot; no directory-scan recovery | same report |
| Native install record | authority | host lifecycle manager | install metadata/digests/manager identifier | per installation | snapshot, Python/action, native definition/digest, manager truth | `docs/runtime-node-lifecycle-architecture.md` |
| Native manager definition | external-backed authority evidence | native OS manager | launchd plist/systemd unit/Task Scheduler task | per installed profile | install record plus live manager read | node lifecycle architecture |
| Desired state | intent | local operator/lifecycle manager | desired-state JSON | per installed profile | installed identity and reconcile loop; never proves running | `tests/test_node.py::test_lifecycle_facts_keep_configured_installed_and_running_orthogonal` |
| Process record | evidence + mutation gate | lifecycle manager | process JSON with launcher PID/group/launch ID | per incarnation | installed profile, exact launch identity, listener lease, live PID/creation facts | `tests/test_node.py::test_stop_refuses_to_signal_a_mismatched_process_record` |
| Listener lease | evidence + mutation gate | listener process | lease JSON with interpreter PID/role/repo/profile/state root/launch ID | per live incarnation | process record and live observation; PID/name alone insufficient | `tests/test_node.py::test_stop_refuses_live_pid_without_matching_listener_lease` |
| Service/listener logs | evidence | manager/listener | platform log paths | per profile/incarnation | diagnostic only; never authorizes stop or business recovery | `src/agent_workflow/node.py::logs` |
| Doctor/readiness output | derived observation | read-only doctor | bounded machine-readable output; not persisted by Runtime as authority | per command observation | current profile/config/workspace/Bus/tool version; a caller-held copy cannot authorize after facts change | `tests/test_node.py::test_doctor_json_emits_secret_free_reusable_snapshot` |
| Fast Preflight output | derived observation | preflight runner | bounded credential-free command output; not an independent authority family | per execution | host/path/tool/Bus/workspace/queue facts used in the exact Deep evaluation | `docs/tasks/fresh-machine-usability-acceptance-closeout-report.md` |
| Deep proof/cache | cache/evidence | preflight runner | HMAC-bound no-model request/result proof | per exact source/target fingerprint/TTL | Fast facts, exact scoped queues, handler child results and Bus observations | same acceptance report |
| Per-probe source/target result | evidence | source/target preflight handlers | `<state>/preflight/probes/<probe>/source-result.json` and `target-result.json` | up to two per disposable probe | exact late-result recovery without resending the probe | `scripts/awf_preflight.py`; `docs/tasks/deep-late-result-recovery-implementation-report.md` |
| Latest Deep report | cache | source preflight runner | `<state>/preflight/latest-deep.json` | zero or one per state root | TTL/fingerprint-bound permission observation; stale/unreadable cannot authorize | `src/agent_workflow/node.py::_preflight_observation` |

## 3. External truth (never AWF-owned authority)

| System | External facts | AWF use | Failure behavior | Evidence |
|---|---|---|---|---|
| Agent Bus | event/delivery record, pending/delivered/failed, retry/error, handler-success ACK | carry opaque idempotent envelopes; payload-blind observations for gates/status | local intent/input preserved; no manual ACK/requeue/replacement | `docs/runtime-execution-architecture.md`; business/no-model acceptance reports |
| Provider CLI/process | executable/auth, actual process creation/exit, provider-side session/result | structured invocation and local evidence | start/exit uncertainty becomes ambiguity; no automatic repeat | durable handler evidence + crash replay tests |
| Git | object database, refs, index/worktree, remote configuration | exact checkout/import/commit/push/fetch verification | mismatch/unavailable denies mutation or acceptance | fork/PR implementation report |
| GitHub | PR identity/state/base/head tuple, CI/check conclusions, merge | exact-number lookup and trust-boundary re-read | mismatch/unavailable denies terminal/merge evidence update | `awf_role.py::verify_pr_head`; status tests |
| Native OS manager/process table | definition, task/unit/job state, PID/creation identity/liveness | exact installation/incarnation observation and action | unknown/mismatch denies action and preserves records | node lifecycle architecture and exact-stop tests |
| Filesystem/OS | durability, atomic replace, permissions/locks | local authority/evidence storage | corrupt/unreadable/symlink/root mismatch denies; no guessed repair | control-plane and role record loaders/tests |

## 4. Named recovery joins and baseline pressure

| Recovery case | Minimum current joins | Count note |
|---|---|---|
| Duplicate input before provider start | delivery envelope + RunLedger gate events/decisions + checkpoint/inbox/outbox presence | at least 2 internal families; may be 4 after partial work |
| Provider start ambiguous | RunLedger authorization + recovery checkpoint + handler process log/result + durable workspace | at least 4 internal families plus live/process evidence when recoverable |
| Completed provider before import | checkpoint + handler result/log + workspace manifest + Artifact bytes | at least 4 internal families |
| Commit/PR handoff recovery | checkpoint + workspace/Git manifest + Git refs + GitHub PR tuple + outbox + inbox | 4 internal families plus 2 external systems |
| Reviewer verdict recovery | checkpoint + durable reviewer workspace/report + PR tuple + outbox + inbox + RunLedger | at least 5 internal families plus Git/GitHub |
| Terminal replay | terminal ledger + terminal workspace/artifacts/PR tuple + inbox + handler outcome + Bus ACK observation | 3 internal families plus Git/GitHub/Bus |
| Exact managed stop | authoring/installed profile identity + registries + install record + native definition + desired/process/lease + live OS observation | at least 7 record families plus OS truth |
| Causal status | lifecycle families + RunLedger/context + checkpoint/outbox/inbox + workspace/artifacts + queue + Git/GitHub + Feedback | read-only join across most domains; it is not authority |

Static inspection identifies 28 separately persisted AWF-written/consumed families when embedded
ledger subrecords are counted with the ledger, the packet/summary mirrors remain derived, and
non-persistent doctor/Fast/node/status views are excluded from the count. Those emitted views remain
in the table to make the authority boundary explicit. The tables also name embedded semantic
subrecords and external facts because a raw file count would hide real recovery joins. Multiplicity remains
per-run, per-delivery, per-role, per-profile, per-incarnation and per-host. Some distinctions are
legitimate; later phases must measure eliminated ownership/fault windows rather than rename files.

## 5. Baseline commands, prerequisites, and support surface

Current steady-state synthetic beginner path: `awf init`, `doctor`, `start`, `run check`, `run`,
`status`, `stop` (seven commands), with setup/plan/dispatch/preflight/resume/feedback and eleven node
commands remaining as support/admin surfaces. The measured benchmark records five decision groups;
the 0.0379-second synthetic execution time is not a human/product metric.

Direct prerequisites remain Python 3.11+, an installed Agent Workflow wheel/environment, separately
distributed Agent Bus, provider CLI/auth, Git/remotes/auth, GitHub CLI/auth for PR flows, and a
supported user service manager for managed lifecycle. Exact production dependency and LOC metrics
from the double review are baseline observations, not RTS-001 acceptance targets: 12 `src` Python
files, 20 operations Python scripts, 19 test modules, 478 statically counted tests, and 31,867 Python
lines across `src`, `scripts`, and tests.

## 6. Classification/open questions

1. RunLedger is current Workflow authority; checkpoint is executing-host authority for whether a
   provider may be repeated. Neither can replace the other without a language-neutral fixture.
2. Context packet/summary, registry indexes, readiness reports and status are candidates for derived
   consolidation, but stale/deleted derived data must deny or rebuild—not authorize.
3. Outbox/inbox/checkpoint file-order windows are candidates for one local journal/store. Provider,
   Bus, Git/GitHub, OS and cross-host effects remain external transactions.
4. Lifecycle's many records repaired real exact-identity failures. A smaller representation is a
   hypothesis until it proves install/incarnation/live exact-stop semantics on all claimed OSes.
5. Feedback is independent optional product state. Reducing/externalizing it is an owner product
   boundary decision, not a storage cleanup.
