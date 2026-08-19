# `awf.semantic-contract.v1` — Current Python Reference

Status: **Candidate**

Extraction basis: `main@0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2`

Candidate evidence basis: `main@463c195c1404331e690c99a0865debb21e0b67c1` plus disposable
RTS-011 executable acceptance head `2868486263aaf35814719fb9ab085a5787359408`

Maturity rule: this document extracts observed behavior and known safety requirements. It is not a
production ABI, migration authority, replacement design, or authorization to invoke a provider,
operate Agent Bus state, change a service, or mutate a remote repository. RTS-010 and RTS-011 have
now supplied the two Phase 1 reference acceptances required for `Candidate`. It may become `Frozen`
only after the shared-slice,
storage/topology decision, and independent review gates in the Runtime v2 plan.

## 1. Vocabulary and evidence convention

`MUST`, `MUST NOT`, `MAY`, and `OWNER_ONLY` are normative within this Candidate. “Observed” means the
current implementation and cited evidence agree. “Hypothesis” is not a current requirement and
cannot authorize implementation.

Evidence IDs are declared in section 12. Each normative table row cites at least one ID. The
machine-readable fault matrix uses the same IDs and the outcome IDs declared in section 10.

The stable semantic unit is an observable fact and its owner, not a Python function, JSON filename,
route spelling, CLI flag, or storage engine.

## 2. Owners and identity domains

| Identity/fact | Stable identity | Owner | Normative rule | Evidence |
|---|---|---|---|---|
| Project/repository | trusted repository binding and exact remotes | Owner configuration; Git is external truth | A payload cannot introduce or override repository authority. | E-PROV-1, E-PROV-2 |
| Run | `run_id` bound to TaskCard, frozen base, branch, authority and compiled contract | Owner/compiler, then Run transition writer | Existing identity drift MUST deny; a run cannot be reinitialized as a different run. | E-RUN-1, E-RUN-2 |
| Task | exact committed TaskCard plus Artifact allowlist and selections | Owner/Planner | A fresh Executor MUST NOT require chat or hidden memory; exact committed contract is re-read before mutation. | E-METHOD-1, E-ART-1 |
| Role | architect/coder/reviewer execution identity plus exact configured tool/model where applicable | Owner manifest/profile | Delivery route and effective selection MUST agree before provider start or ACK-sensitive replay. | E-RUN-2, E-SEL-1 |
| Input delivery | delivery ID, canonical payload hash, source event ID, type and role | Source Runtime + transport observation | Same ID/same hash is replay; same ID/different hash is conflict and MUST deny. | E-RUN-2, E-DELIVERY-1 |
| Provider invocation | one run/stage/attempt authorization plus the exact input delivery and provider selection | Run transition writer authorizes; executing host owns process facts | Authorization identity MUST be stable across redelivery. Completed or ambiguous invocation MUST NOT be repeated. | E-RUN-2, E-RECOVERY-1 |
| Workspace | exact event-scoped/no-remote workspace or bound durable rework workspace and manifest | Executing trusted handler | Provider cannot mutate trusted Runtime state or authenticated Git remotes; rework MUST reuse exact proved lineage. | E-WORKSPACE-1, E-REWORK-1 |
| Git contribution | upstream/head repositories, remotes, refs, base/head SHAs and PR number | Trusted runner; Git/GitHub are external truth | Every mutation/acceptance boundary MUST re-read and match the exact tuple. | E-PROV-1, E-PROV-2 |
| Artifact | required path, raw bytes/hash, parsed canonical object/hash and producing commit | TaskCard + trusted validator | Provider exit zero is not Artifact validity. Raw-file and canonical hashes remain distinct. | E-ART-1, E-STATUS-1 |
| Agent installation/incarnation | profile/snapshot/install definition, desired state, launch identity, process creation identity, lease and live observation | Host lifecycle manager | PID/name/liveness/desired state alone MUST NOT authorize stop or mutation. | E-LIFE-1, E-LIFE-2 |
| Transport delivery/ACK | Agent Bus record and handler return | Agent Bus | Bus owns delivery/retry/ACK, not Workflow stage or terminal. ACK follows handler success. | E-BUS-1, E-BUS-2 |
| Feedback/Finding | Feedback outbox/ingest identity | Feedback subsystem | Feedback state MUST NOT rewrite business terminal, inbox, or ACK facts. | E-FEEDBACK-1 |

## 3. Workflow transition contract

The Run transition writer is logically singular. This Candidate does not select whether it is a
physical Coordinator, a process, or a store transaction.

| From | Input and required evidence | To/fact | Automatic? | Denial/terminal rule | Evidence |
|---|---|---|---|---|---|
| initialized `implement` | unique coder route; valid delivery; exact contract/selection/provenance; attempt available | implement invocation `authorized` | Yes, once | Unknown/mismatch/corrupt/over-budget denies before provider start. | E-RUN-2, E-ART-1, E-SEL-1 |
| `implement` authorized | trusted implement result, Artifact/postflight/tree/import and exact commit/provenance | review handoff intent | Yes after all required local effects | Exit zero, a commit, or a sent event alone is insufficient. | E-RECOVERY-1, E-PROV-1, E-OUTBOX-1 |
| `implement` | unique reviewer delivery for the exact implementation lineage | review invocation `authorized` | Yes, once | A route, TaskCard, report, selection or PR tuple mismatch denies. | E-RUN-2, E-SEL-1, E-PROV-2 |
| `review` | valid normalized ReviewReport `PASS` | ready decision intent | Yes | Invalid/multiple/missing report MUST NOT route or return success. | E-REVIEW-1 |
| ready decision | exact embedded report, artifacts and PR tuple; durable terminal transition | run `completed` | Yes | Terminal conflict denies; replay of identical terminal is idempotent. | E-TERMINAL-1 |
| `review` | valid `REQUEST_CHANGES` with deterministic failures and remaining budget | rework handoff intent | Yes | Advisory/style-only findings cannot consume rework; missing lineage/budget denies. | E-METHOD-1, E-REVIEW-1 |
| `review` or prior rework | exact previous implement delivery/checkpoint/workspace/commit/PR/Git manifest | rework invocation `authorized` | Yes, once per authorized delivery/budget | Any lineage drift or ambiguous prior invocation denies. | E-REWORK-1, E-RUN-2 |
| `rework` completed | same trusted effect gates as implement | review handoff intent | Yes, once for the authorized rework | Rework unlocks exactly one additional review-stage slot; both distinct review deliveries still use input `attempt=1`. A second slot or input `attempt>1` denies. | E-REWORK-1, E-OUTBOX-1, E-RUN-2, E-RTS011 |
| `review` | valid `BLOCKED` with non-empty reason | blocked decision intent | Yes | BLOCKED is distinct from ordinary deterministic failure. | E-METHOD-1, E-REVIEW-1 |
| blocked decision | exact report/artifact/provenance; durable terminal transition | run `blocked` | Yes | No automatic next task or provider retry. | E-TERMINAL-1 |
| any nonterminal | explicit fail/cancel/reject decision by the authorized owner | `failed`, `cancelled`, or `rejected` | OWNER_ONLY unless a frozen rule names it | Transport failure or missing evidence cannot silently become a business terminal. | E-RUN-1, E-METHOD-1 |
| any terminal | same terminal evidence replay | unchanged terminal | Yes, idempotent | Different state/evidence is a conflict and MUST deny. | E-RUN-1 |
| current task terminal | a new, separately owner-authorized TaskCard/run intent | next task eligible | OWNER_ONLY | Runtime MUST NOT invent work from pending/retained transport state. | E-METHOD-1, E-BUS-2 |

`rejected` appears in two distinct observed domains and MUST NOT be collapsed: pre-invocation gate
decisions record rejected inputs while run terminal `rejected` is an owner/Decider outcome.

Compatibility fact: legacy direct/no-delivery entry can lack delivery-bound effective selection,
and a legacy TaskCard without the explicit reviewer-selection block falls back to the same
tool/model. These are current compatibility debts, not language-neutral requirements; they remain
fail-closed deletion-gate inputs for Phase 6. [E-SEL-1]

## 4. Invocation and effect model

The proposed five-state enum `prepared / started / completed / failed / ambiguous` is **rejected as
a sufficient model**. Current faults require orthogonal facts; for example, `completed` cannot say
whether the result is durable, the Artifact is valid, trusted import occurred, Git/PR provenance is
current, or outgoing intent is durable. `failed` cannot distinguish a trusted non-zero exit from
unknown spawn outcome or invalid Artifact.

An implementation MAY encode the following axes differently, but MUST preserve their distinctions:

| Axis | Required facts | Owner | Evidence |
|---|---|---|---|
| Authorization | absent, authorized, rejected, replay/conflict | Run transition writer | E-RUN-2 |
| Launch/process observation | launch-intent absent/persisted, process-start observed/unobserved, exit observed/unobserved, result ambiguous | Executing host | E-HANDLER-1, E-RECOVERY-1 |
| Provider result | absent, durable result/evidence, non-zero, corrupt/unreadable | Executing host | E-HANDLER-1, E-RECOVERY-1 |
| Artifact | absent, raw-persisted, invalid, normalized/validated, imported | Trusted validator/importer | E-ART-1, E-RECOVERY-1 |
| Trusted local effect | absent, postflight-pass, imported tree, commit | Trusted runner | E-WORKSPACE-1, E-RECOVERY-1 |
| External provenance | unobserved, exact, stale/mismatch, unavailable | Git/GitHub reader | E-PROV-1, E-PROV-2 |
| Handoff intent | absent, prepared, attempting, ambiguous, sent | Source handler/outbox | E-OUTBOX-1 |
| Input completion | absent, completed, conflicting | Destination handler/inbox | E-INBOX-1 |
| Handler outcome | running/unknown, success, failure | Handler process | E-HANDLER-1 |
| Transport | pending/delivered/failed/ACKed/unknown observation | Agent Bus | E-BUS-1, E-BUS-2 |
| Workflow terminal | nonterminal, completed, blocked, failed, cancelled, rejected | Run transition writer/Decider | E-TERMINAL-1 |

Rules:

1. Authorization MUST be durable before provider start. A failed authorization write cannot permit
   a process start. [E-RUN-2]
2. `model_not_started` MAY invoke once. Persisted launch intent (`model_started`) with no trusted
   recoverable result is ambiguous and MUST NOT auto-invoke, whether an OS process start was
   observed or not. Later phases skip the provider and revalidate every downstream fact.
   [E-RECOVERY-1]
3. A recoverable completed provider process may resume only from the exact durable workspace/result
   identity. Missing or drifted evidence fails closed. [E-RECOVERY-1, E-WORKSPACE-1]
4. A non-zero exit is evidence of failure, not authorization to retry the same delivery. [E-RECOVERY-1]
5. Runtime/Bus/Git/GitHub/OS facts never become one “success” boolean. [E-STATUS-1, E-BUS-1]

## 5. Current checkpoint, result, outbox, inbox, terminal, and ACK boundaries

### 5.1 Recovery checkpoint phases

Every phase is monotonic and binds the immutable input delivery, source commit, branch, provenance,
state root, and optional exact rework lineage. Replaying a completed phase with different facts
MUST deny. [E-RECOVERY-1]

| Role | Phase | Durable meaning | Safe automatic action after restart | Evidence |
|---|---|---|---|---|
| coder/reviewer | `model_not_started` | checkpoint exists; provider start not recorded | invoke once after all current gates revalidate | E-RECOVERY-1 |
| coder/reviewer | `model_started` | launch intent/workspace identity is durable **before** the adapter call; actual process start is a separate RunEvidence fact | recover only separately proved same-event/role/process zero-exit plus exact workspace result, otherwise fail ambiguous; never invoke again | E-RECOVERY-1, E-HANDLER-1 |
| coder/reviewer | `model_completed` | provider returned zero and durable workspace/result evidence exists | skip provider; revalidate workspace and continue trusted validation/import | E-RECOVERY-1 |
| coder only | `postflight_completed` | frozen verification/allowed-path/secret/diff contract passed | skip provider/postflight result; continue exact trusted import | E-ART-1, E-RECOVERY-1 |
| coder/reviewer | `model_imported` | trusted tree or ReviewReport bytes/hash imported | continue only if imported facts still match | E-WORKSPACE-1, E-RECOVERY-1 |
| coder only | `commit_created` | trusted commit binds imported tree and required Lore evidence | verify external fork head; never ask provider to recreate | E-PROV-1, E-RECOVERY-1 |
| coder only | `fork_sha_verified` | freshly fetched contribution-fork SHA equals trusted commit | create/verify exact PR tuple | E-PROV-1, E-RECOVERY-1 |
| coder/reviewer | `pr_tuple_verified` | current exact upstream/head repo/ref/SHA/PR tuple verified | prepare the one semantic downstream intent | E-PROV-2, E-RECOVERY-1 |
| coder/reviewer | `outbox_prepared` | immutable downstream envelope/intention is durable | revalidate evidence; retry send with stable delivery identity | E-OUTBOX-1 |
| coder/reviewer | `outbox_sent` | send command reported success and sent outbox is durable | do not resend; complete exact source inbox if not already complete | E-OUTBOX-1, E-INBOX-1 |

Open question OQ-1: the current checkpoint writes `model_started` immediately before the provider
wrapper starts the process. A crash in that gap is conservatively ambiguous. The Candidate preserves
that denial; the shared slice must test whether a future `authorized/prepared/start-observed`
representation can reduce the gap without permitting duplicate invocation.

### 5.2 Outbox and inbox

| Fact | Normative meaning | Legal next action | Evidence |
|---|---|---|---|
| outbox absent | no durable downstream intent | continue only from the exact preceding checkpoint | E-OUTBOX-1 |
| `prepared` | complete immutable envelope/provenance is durable; no send result | verify current evidence, send same identity | E-OUTBOX-1 |
| `attempting` | send began; result was not durably classified | treat as ambiguous; idempotent resend only with same stable delivery and verified evidence | E-OUTBOX-1 |
| `ambiguous` | send failed/raised or success is unknown | same as attempting; never create replacement identity to force progress | E-OUTBOX-1 |
| `sent` | send returned success and sent status is durable | do not resend; finish exact input inbox | E-OUTBOX-1 |
| inbox `completed` | this role completed the exact input delivery/hash | return handler success on identical replay; conflicting input denies | E-INBOX-1 |

Current automatic resend of `attempting/ambiguous` is legal only because the downstream delivery ID
is deterministic, the outbox envelope is immutable, and the destination's run gate/inbox dedupe the
same identity. It does not assert exactly-once transport. [E-OUTBOX-1, E-INBOX-1, E-RUN-2]

### 5.3 Terminal, handler success, and ACK

1. Architect validates the exact terminal delivery/report/artifacts/provenance in an isolated
   workspace. [E-TERMINAL-1]
2. The run terminal ledger is durably and idempotently written before terminal inbox completion.
   [E-TERMINAL-1]
3. The exact input inbox is completed before the role handler returns success. [E-INBOX-1]
4. Agent Bus may ACK only from handler success; Workflow does not write ACK. [E-BUS-1]
5. `sent`, inbox completion, handler success, ACK, terminal, CI green, and merge remain different
   facts. [E-STATUS-1, E-BUS-2]

OQ-2: Agent Bus ACK is currently proved by external transport records/reports rather than an AWF
authoritative record. A future implementation must preserve that ownership; it may store an ACK
observation as evidence but cannot make it Workflow authority.

## 6. Artifact, workspace, Git, and rework lineage

- Provider commands MUST use structured argv/stdin/file boundaries; business input MUST NOT be
  interpreted by a shell. Renderers are pure and cannot mutate Runtime state. [E-PROCESS-1]
- Model processes receive credential-stripped environments and no authenticated remote. The trusted
  runner alone validates/imports the delta, commits, pushes, creates/verifies PRs, and records the
  exact facts. [E-WORKSPACE-1]
- Allowed paths, verification commands, secret scan, report presence, trackedness, raw bytes/hash,
  parsed object and canonical hash are separate gates. [E-ART-1]
- A reviewer verdict is authoritative only after the trusted normalizer validates exactly one
  bounded ReviewReport. Tool exit zero is not a verdict. [E-REVIEW-1]
- Rework binds the exact prior implement delivery, checkpoint digest, state root, durable workspace,
  source/implementation commit, imported tree, PR tuple and Git manifest. Any missing, non-unique,
  stale or mismatched fact denies before provider start. [E-REWORK-1]
- `REQUEST_CHANGES` permits bounded deterministic failures only. Rework does not authorize new
  product scope or a different implementation lineage. [E-METHOD-1, E-REWORK-1]

## 7. Lifecycle and process/incarnation contract

Configured, installed, running, connected and dispatch-capable are orthogonal observations.
[E-LIFE-1]

- Managed installation is current only when the installed snapshot/registry/install record/native
  definition and exact bindings agree. Missing, stale or unreadable evidence cannot authorize
  start/stop/upgrade. [E-LIFE-1]
- Running requires exact profile digest, role, repository, state root, launch identity, process
  creation identity where supported, listener lease and live observation. A launcher PID may differ
  from the interpreter PID; stable launch identity binds them. [E-LIFE-2]
- Stop/mutation MUST NOT use only PID, process name, liveness, desired state or directory scanning.
  Unknown or live mismatched identity preserves evidence and denies. [E-LIFE-2]
- Lifecycle code MUST NOT read business payloads or ACK/requeue/recover/dispatch deliveries.
  Handler checkpoint/outbox/inbox and Bus semantics remain independent. [E-LIFE-1]

OQ-3: current exact lifecycle identity spans multiple persistent records. Consolidation is a target
hypothesis; no record may be deleted until a replacement fixture proves the same exact-stop and
three-OS behavior.

## 8. Status and recovery authority

Status is a read-only projection over lifecycle, run ledger, delivery records, workspace, artifacts,
Git/GitHub, queue observations and independent Feedback state. [E-STATUS-1]

- Status MAY label a fact `unknown`, `unavailable`, `stale`, `not_recorded`, `blocked`, `active`, or
  terminal and name one legal next action.
- Status MUST NOT ACK, requeue, recover, redispatch, flush Feedback, mutate lifecycle, invoke a
  provider, or turn a stale/cache observation into authorization.
- An active run's displayed `next_action` may be copied from the authority-owned context packet.
  Status MUST label its source and MUST NOT treat the string as a freshly revalidated mutation
  command.
- Deleting or corrupting a derived status view MUST NOT delete or reinterpret authoritative recovery
  state.
- Automatic recovery is limited to exact same-identity checkpoint/outbox/inbox paths enumerated in
  section 5. Ambiguous provider invocation, conflicting terminal, unknown provenance, incompatible
  state/schema, historical delivery, and destructive migration are OWNER_ONLY decisions.

Feedback capture failure is best-effort only after a valid report has been safely stripped and
validated. A malformed reserved Finding envelope or a failure to separate it from the business
Artifact remains an Artifact failure; “independent” does not mean malformed business evidence may
pass. [E-FEEDBACK-1, E-ART-1]

## 9. External truth and availability

| External system | Owned fact | Runtime obligation | Unavailable/stale behavior | Evidence |
|---|---|---|---|---|
| Provider CLI/process | process creation and exit | record exact local observation; never infer exit from Artifact existence | ambiguous/deny replay | E-HANDLER-1, E-RECOVERY-1 |
| Agent Bus | delivery, retry, handler-success ACK, pending/failed | stable idempotent envelope; observe payload-blind state only where needed | preserve local intent/input and report unavailable | E-BUS-1, E-BUS-2 |
| Git | objects, refs, worktree/index | re-read exact commit/tree/ref/remotes at every trust boundary | deny mutation/acceptance | E-PROV-1, E-WORKSPACE-1 |
| GitHub | PR tuple, state, CI | exact-number lookup and full tuple verification; keep recorded/live facts separate | deny terminal/merge acceptance or label unavailable | E-PROV-2, E-STATUS-1 |
| OS/native manager | definition, process, creation identity, liveness | join exact recorded identity with live observation | deny mutation; preserve records | E-LIFE-1, E-LIFE-2 |
| Filesystem | atomic local records, durability, corruption | regular-file/root/checksum/format validation and fail closed | deny; no guessed repair | E-RUN-1, E-RECOVERY-1 |

Program rollback MUST NOT roll back, downgrade, or silently reinterpret Runtime/Bus state. Schema or
compatibility uncertainty denies and preserves exact evidence.

## 10. Normalized outcomes

These IDs are the only top-level results used by the fault matrix:

| Outcome ID | Meaning |
|---|---|
| `SAFE_CONTINUE` | Continue from the exact next durable boundary with no repeated external effect. |
| `SAFE_IDEMPOTENT_REPLAY` | Return/reapply the same already-completed semantic result without new provider/Git/transport effect. |
| `SAFE_STABLE_RESEND` | Retry only the same immutable, idempotent outgoing delivery after evidence revalidation. |
| `DENY_BEFORE_PROVIDER` | Fail closed before any provider invocation is authorized/started. |
| `AMBIGUOUS_NO_REPLAY` | Preserve evidence and refuse automatic provider replay. |
| `DENY_BEFORE_MUTATION` | Refuse Git/lifecycle/terminal/other mutation because identity or evidence is not exact. |
| `HANDLER_FAILURE_NO_ACK` | Required local/handoff effect is incomplete; handler fails so Bus cannot success-ACK. |
| `TERMINAL_IDEMPOTENT` | Identical terminal replay returns the existing decision. |
| `TERMINAL_CONFLICT` | A different terminal state/evidence is refused and preserved for owner decision. |
| `OWNER_DECISION_REQUIRED` | Existing evidence cannot uniquely authorize a safe mutation/recovery. |
| `EXTERNAL_OBSERVATION_UNKNOWN` | Projection reports unavailable/unknown without mutating authority. |

## 11. Facts, current reference gaps, hypotheses, and open questions

Observed facts:

- Python is the only production Runtime; Agent Bus is independent transport. [E-BUS-1]
- Current semantics use a RunLedger plus per-delivery checkpoint/outbox/inbox and distinct
  lifecycle/evidence views. [E-RUN-1, E-RECOVERY-1, E-LIFE-1]
- One historical three-card PASS exists, but it predates final remediation and contains no rework.
  It is not RTS-010/011 evidence. [E-BUS-2]
- RTS-010 supplies one fresh post-remediation real business PASS with exact provider counts,
  provenance, terminal, external ACK and queue evidence. [E-RTS010]
- RTS-011 supplies one complete disposable deterministic rework loop with four real local child
  processes, durable restart/lineage/handoff/terminal evidence, and explicitly synthetic
  provider intelligence, transport send/ACK and GitHub provenance. [E-RTS011]

Resolved Phase 1 reference gaps retained as regression cases:

- **CG-1 — resolved by PR #100 plus RTS-011.** One authorized rework now unlocks exactly one
  follow-up review-stage slot without raising the per-delivery attempt limit; the complete loop,
  restart, duplicate, lineage-drift, handoff and terminal behaviors are executable regressions.
  [E-RUN-2, E-REWORK-1, E-RTS011]
- **CG-2 — resolved by PR #97 and RTS-010.** Handler reconstruction recovers and preserves the
  immutable compiled-contract SHA from the current ledger packet; fresh real acceptance reached
  terminal without deleting the binding. [E-RUN-1, E-RUN-2, E-RTS010]

Current reference gaps (mapped faults, not accepted semantics):

- **CG-3 — durable recovery is not uniform across providers/routes.** Current v3 OpenCode/Pi paths
  have checkpoints; the Codex reviewer compatibility path does not use the same durable checkpoint,
  and v1/v2 do not carry all v3 provenance/checkpoint facts. The Candidate MUST NOT claim the v3 phase
  graph covers every existing route/provider. [E-RECOVERY-1]
- **CG-4 — authorization can precede checkpoint creation.** A crash after RunLedger authorization
  but before a recovery checkpoint/outbox/inbox exists leaves a duplicate with no safe automatic
  worker recovery. Budget consumption is durable even if later lineage/provider-preflight fails.
  Preserve evidence and deny; do not erase the attempt. [E-RUN-2, E-RECOVERY-1]
- **CG-5 — some trusted local-effect/write gaps lack explicit reconciliation fixtures.** These
  include coder trusted import before `model_imported`, reviewer report copy/parse before its shared
  `model_imported` phase, and Pi zero-exit evidence before captured stdout persistence. Current safe
  fallback is no provider replay; later fault fixtures must distinguish recoverable exact state from
  ambiguity. [E-RECOVERY-1, E-ART-1]
- **CG-6 — terminal causality is a multi-record join.** Architect terminal has no separate
  pre-invocation gate identity; it relies on delivery integrity, exact ReviewReport/Artifact/PR
  facts, reviewer outbox lineage, idempotent terminal and inbox. This is not one atomic causal
  transition. [E-TERMINAL-1, E-OUTBOX-1]
- **CG-7 — `failed`, `cancelled`, and terminal `rejected` lack shipped handler transitions.** Gate
  `rejected` is a nonterminal per-input decision. These terminal labels remain reserved/method-level
  until a later contract/evidence gate defines their authority and evidence. [E-RUN-1, E-RUN-2]
- **CG-8 — local durable state has no safe cross-host adoption protocol.** Moving a logical role to
  another machine cannot silently adopt its old checkpoint/outbox/inbox/workspace. [E-RECOVERY-1]

Hypotheses requiring later gates:

- Python cannot be simplified enough.
- Rust or Go materially reduces ownership or distribution cost.
- SQLite removes enough named local fault windows to justify migration.
- A physical always-on Coordinator is needed.
- One compiled RunSpec or four state classes are sufficient.
- `run/status/stop` removes user decisions rather than hiding support complexity.

Open questions carried to later phases:

- OQ-1 authorization-to-process-start ambiguity window (section 5.1).
- OQ-2 representation of transport ACK observation without stealing Bus authority (section 5.3).
- OQ-3 lifecycle record consolidation while preserving exact stop (section 7).
- OQ-4 next-task eligibility is owner intent, but the future compiled representation and UI are not
  selected.
- OQ-5 a local transaction may combine transition and intent, but cannot include provider, Bus,
  Git/GitHub, OS or another host; storage comparison must name only windows it actually removes.
- OQ-6 postflight retry attempts are recorded but no general retry ceiling/owner action is frozen.
- OQ-7 `model_imported` has role-specific meaning (Git tree import for coder, normalized report
  import for reviewer) and cannot be one language-neutral atomic state without explicit subfacts.
- OQ-8 an exact per-event ACK observation contract is external and version-dependent; pending-zero
  alone cannot be promoted to ACK or Workflow completion.
- OQ-9 current run IDs are task/branch-leaf-derived rather than repository-qualified; collision in a
  shared state root safely denies as identity drift but leaves a multi-project UX decision.

## 12. Evidence catalog

| ID | Current evidence |
|---|---|
| E-METHOD-1 | `constitution.md` sections 4–13; `tests/test_awf_role.py::test_reviewer_routes_exactly_one_valid_verdict` |
| E-RUN-1 | `scripts/awf_control_plane.py::RunLedger.initialize/recover/mark_terminal/finalize_merge`; `tests/test_control_plane.py::test_packet_is_bounded_and_recoverable_from_a_fresh_session`; `test_terminal_ledger_and_summary_are_durable_and_idempotent` |
| E-RUN-2 | `scripts/awf_control_plane.py::RunLedger.pre_invocation_gate`; `tests/test_control_plane.py::test_gate_rejects_missing_route_before_authorization`; `test_gate_rejects_over_budget_terminal_and_replay`; `tests/test_awf_role.py::test_delivery_id_reuse_with_different_payload_fails_closed` |
| E-DELIVERY-1 | `scripts/awf_role.py::validate_input_delivery/complete_inbox/inbox_completed`; `tests/test_awf_role.py::test_delivery_selection_mismatch_fails_before_ack_sensitive_lifecycle` |
| E-RECOVERY-1 | `scripts/awf_role.py::_CODER_RECOVERY_PHASES/_REVIEWER_RECOVERY_PHASES`, `advance_recovery_checkpoint`, `recovery_model_policy`, `recover_completed_model_checkpoint`; `tests/test_awf_role.py::test_same_delivery_crash_replay_matrix_preserves_phase_and_model_count`; `test_v3_reviewer_ambiguous_model_started_checkpoint_fails_cleanly`; `test_tool_failure_replay_never_reinvokes_model` |
| E-OUTBOX-1 | `scripts/awf_role.py::prepare_outbox/deliver_outbox/resume_outbox/reconcile_recovery_checkpoint_with_outbox`; `tests/test_awf_role.py::test_v3_outbox_replay_revalidates_same_provenance_without_model`; `test_prepared_outbox_replay_reconciles_checkpoint_before_send`; `test_coder_ambiguous_outbox_replays_before_checkout` |
| E-INBOX-1 | `scripts/awf_role.py::complete_inbox/inbox_completed`; `tests/test_awf_role.py::test_architect_terminal_consumer_completes_and_replays_without_model`; `test_completed_reviewer_delivery_skips_model_and_send` |
| E-HANDLER-1 | `scripts/awf_role.py::RunEvidence/spawn/main`; `docs/tasks/durable-handler-exit-evidence.md`; `tests/test_awf_role.py::test_controlled_subprocess_persists_real_pid_and_return_code`; `test_handler_main_persists_exit_for_success_and_failure` |
| E-PROCESS-1 | `scripts/awf_executor.py`; `scripts/agent_adapters/`; `tests/test_runtime_command_boundary.py::test_production_code_never_uses_implicit_shell_execution`; `test_agent_adapter_renderers_are_pure_operations_modules` |
| E-ART-1 | `scripts/awf_role.py::parse_postflight_contract/run_postflight_delta_gates/import_model_report/mark_artifact_invalid`; `tests/test_awf_role.py::test_full_valid_postflight_flow`; `test_artifact_invalid_checkpoint_is_bounded_and_preserves_report_binding`; `test_reviewer_rc_zero_without_report_cannot_route_pass` |
| E-REVIEW-1 | `scripts/awf_role.py::parse_review_report/normalize_machine_review_envelope/role_reviewer`; `docs/tasks/reviewer-verdict-routing-implementation-report.md`; `tests/test_awf_role.py::test_invalid_review_report_fails_before_send`; `test_each_reviewer_route_send_failure_is_nonzero` |
| E-WORKSPACE-1 | `scripts/awf_role.py::prepare_model_workspace/import_model_delta/assert_model_workspace_state`; `docs/tasks/executor-git-write-guard-implementation-report.md`; `tests/test_awf_role.py::test_coder_runs_model_in_no_remote_workspace_then_trusted_runner_pushes`; `test_assert_model_workspace_state_rejects_head_or_remote_change` |
| E-PROV-1 | `scripts/awf_role.py::push_and_verify_fork_head/verify_pr_remote_tuple`; `docs/tasks/fork-pr-trusted-runner-implementation-report.md`; `tests/test_awf_role.py::test_fork_push_fresh_sha_equality_proceeds_to_exact_pr`; `test_pr_tuple_mismatch_fails_closed` |
| E-PROV-2 | `scripts/awf_role.py::verify_pr_head/prepare_terminal_workspace`; `tests/test_awf_role.py::test_v3_architect_terminal_fetch_and_verification_stay_outside_dirty_source`; `test_pr_create_returns_exact_number_without_branch_list_rediscovery` |
| E-REWORK-1 | `docs/tasks/implement-rework-workspace-transition-implementation-report.md`; `scripts/awf_role.py::resolve_fresh_rework_workspace_lineage/restore_rework_workspace_lineage`; `tests/test_awf_role.py::test_rework_restores_unique_implement_lineage_and_rejects_git_drift`; `test_tool_opencode_exec_injects_bounded_rework_feedback` |
| E-TERMINAL-1 | `scripts/awf_role.py::role_architect`; `scripts/awf_control_plane.py::RunLedger.mark_terminal`; `tests/test_awf_role.py::test_architect_persists_terminal_ledger_and_summary_before_inbox`; `test_architect_terminal_consumer_rejects_report_drift_without_completing_inbox` |
| E-SEL-1 | `scripts/awf_role.py::validate_delivery_selection/validate_frozen_role_selection`; `tests/test_awf_role.py::test_delivery_selection_mismatch_fails_before_ack_sensitive_lifecycle`; `test_matching_delivery_reviewer_emits_validated_effective_identity` |
| E-LIFE-1 | `docs/runtime-node-lifecycle-architecture.md`; `src/agent_workflow/node.py::lifecycle_facts/start/stop`; `tests/test_node.py::test_lifecycle_facts_keep_configured_installed_and_running_orthogonal`; `test_start_fails_before_spawn_when_readiness_fails` |
| E-LIFE-2 | `docs/tasks/durable-profile-exact-stop-implementation-report.md`; `docs/tasks/windows-venv-pid-binding-implementation-report.md`; `tests/test_node.py::test_stop_refuses_live_pid_without_matching_listener_lease`; `test_listener_snapshot_accepts_distinct_pid_with_bound_launch_identity` |
| E-STATUS-1 | `src/agent_workflow/status.py::snapshot/_causal_status`; `tests/test_status.py::test_live_pr_and_ci_are_separate_from_recorded_facts`; `test_snapshot_reports_rejected_pre_model_event_without_payload_or_mutation`; `test_business_terminal_keeps_feedback_pending_independent` |
| E-FEEDBACK-1 | `scripts/awf_feedback.py`; `docs/tasks/dogfood-finding-phase-a-implementation-report.md`; `tests/test_status.py::test_business_terminal_keeps_feedback_pending_independent` |
| E-BUS-1 | `docs/runtime-execution-architecture.md`; `docs/tasks/structured-handler-contract-implementation-report.md`; `tests/test_awf_role.py::test_each_reviewer_route_send_failure_is_nonzero`; handler-success ACK ownership is external to this repository's Runtime code |
| E-BUS-2 | `docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md`; `docs/tasks/fresh-machine-usability-acceptance-closeout-report.md`; both reports explicitly separate historical business PASS/no-model transport evidence from new authorization |
| E-RTS010 | `docs/tasks/runtime-v2-rts-010-fresh-pass-acceptance-report.md`; fresh post-remediation business PASS with exact provider counts, Git/GitHub provenance, terminal, external ACK and scoped queue evidence |
| E-RTS011 | `docs/tasks/runtime-v2-rts-011-deterministic-rework-acceptance-implementation-report.md`; `tests/test_runtime_v2_rts011_acceptance.py`; `tests/fixtures/runtime_v2_scripted_provider.py`; PR #100 review-capacity regressions; complete disposable bounded rework acceptance with synthetic external boundaries |

## 13. Candidate change control

Phase 2 observations may correct this Candidate but MUST preserve failed evidence. A correction must
name the old claim, observed counterexample, revised rule, affected fault cases, and whether a new
fundamental invariant was discovered. Candidate is not Frozen and authorizes no production
migration, default switch or release action.
