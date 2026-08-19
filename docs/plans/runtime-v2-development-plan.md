# Agent Workflow Runtime Simplification and Runtime v2 Decision Plan

Status: Active gated repository plan after independent double review. Last passed gate:
**RTS-001 / Phase 0 Draft TaskCard (`PASS`, 2026-08-19)**; PR #96's CI gate is green and awaits
final integration. It is not an ADR and authorizes no production implementation, model invocation,
queue operation, migration, or release action by itself.

Date: 2026-08-19

Basis:

- [Original architecture Review](../reviews/2026-08-18-global-architecture-product-simplicity-runtime-rewrite-review.md)
- [Independent adversarial double review](../reviews/2026-08-19-runtime-v2-adversarial-double-review.md)
- Current repository truth: `main@0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2`
- [HANDOFF](../../HANDOFF.md)
- [ROADMAP](../../ROADMAP.md)

## 1. Plan Decision

Proceed with a bounded **Runtime simplification and implementation-choice program**.

Do not preselect:

- a full rewrite;
- Rust over Go or Python restructuring;
- SQLite over atomic files or an append-only journal;
- a physically singular always-on Coordinator;
- exactly four authoritative state classes;
- `run/status/stop` as the entire support and administration surface.

Python remains the only production Runtime until a later explicit cutover. Rust is a gated native
candidate. Go is a bounded fallback/candidate if Rust-specific delivery or maintenance thresholds
fail. Python internal refactoring is a first-class possible outcome. Python plus a native launcher is
the distribution fallback when architecture is acceptable and packaging is the remaining blocker.

The desired outcome is smaller ownership and a simpler user journey, not a language migration.

## 2. Scope and Non-Goals

### In scope

- language-neutral Workflow, invocation, ACK, provenance, and recovery semantics;
- current authority/evidence/ownership/fault inventory;
- one fresh post-remediation real PASS business acceptance;
- one deterministic current-Python rework acceptance;
- one shared local no-model vertical-slice fixture;
- bounded Python, Rust, and conditional Go comparisons;
- storage and Coordinator-topology decisions based on fault evidence;
- a steady-state `awf run/status/stop` golden path with explicit support surfaces;
- eventual isolated migration, native lifecycle, distribution, dogfood, cutover, and cleanup only if
  earlier gates pass.

### Out of scope unless a later gate explicitly authorizes it

- Agent Host, scheduler, arbitrary DAG, provider/plugin registry, dashboard, or SaaS control plane;
- Agent Bus protocol redesign or ownership of Workflow stage;
- Rust rewrite of Agent Bus;
- new provider support beyond currently evidenced Codex/OpenCode/Pi needs;
- production migration during a prototype phase;
- automatic recovery of retained or ambiguous business deliveries;
- dual writes between Python and a candidate Runtime;
- silent fallback between Runtimes;
- live release publication, signing-account use, or remote service changes;
- deletion of current compatibility or safety state before its item-specific gate.

## 3. Non-Negotiable Semantic Invariants

Every implementation option must prove the same observable outcomes:

1. One stable authorization identity for each provider invocation.
2. No repeat of a completed or ambiguous invocation on duplicate/redelivered input.
3. `started` without a trusted recoverable result never auto-replays.
4. Unknown, stale, mismatched, corrupt, or conflicting authority fails closed.
5. Required local durable effects and downstream handoff intent precede handler success; Agent Bus ACK
   remains transport-owned and follows handler success.
6. Workflow terminal, Agent Bus ACK, provider exit, Artifact validity, Git commit, PR/CI, and Feedback
   state remain distinct facts.
7. Structured argv/stdin/file boundaries are used; business input is not interpreted by a shell.
8. Workspace, run, role, process/incarnation, Git remote, commit, PR, CI, and Artifact provenance are
   exact-bound before mutation or terminal acceptance.
9. `REQUEST_CHANGES` authorizes only bounded rework on the exact previous implement lineage.
10. Status is a read-only projection and cannot authorize or perform recovery.
11. Agent Bus remains independently released, at-least-once, and transport-only.
12. Program rollback does not roll back or silently reinterpret Runtime/Bus state.

Representations may change only after language-neutral fixtures prove these outcomes.

## 4. Contract Maturity and Authority

The semantic contract uses three explicit maturity states:

| State | Meaning | May production implementation depend on it? |
|---|---|---|
| `Draft` | Extracted from current code/reports; gaps and hypotheses are allowed and labeled. | No. Documentation, fixtures, and isolated experiments only. |
| `Candidate` | Corrected by fresh PASS and deterministic rework acceptance; fault mapping independently reviewed. | Only a disposable implementation-choice slice. |
| `Frozen` | Shared slice and storage/topology decision pass; every normative transition has conformance evidence. | Yes, after an owner-approved ADR/TaskCard. |

Neither this plan nor either Review is a product ADR. Runtime becoming a first-class product layer,
or reducing/externalizing Runtime scope, requires a separate owner decision.

## 5. Measurement Baseline

Before changing production behavior, record these values in a versioned baseline report:

- logical authority domains and their owners;
- persistent record families classified as authority, intent, evidence, derived view, cache, or
  external observation;
- number of stores/files joined for each named recovery case;
- current normal-path commands and human decisions;
- support-path commands for install/auth/Git/Bus/workspace/ambiguity/rework/upgrade/multi-project cases;
- direct production dependencies, production non-comment lines, test/fixture counts, and supported
  platform gates;
- fault outcome and legal next action for every semantic-contract case;
- distribution prerequisites and artifact count.

State-class count is reported with per-worker/per-host multiplicity. External truth is listed
separately and never hidden to make the target count smaller.

## 6. Phase Plan

### Phase 0 — Draft the Semantic and Fault Contract

Entry criteria:

- Current HEAD and original Review basis are recorded.
- Original Review remains Draft and unmodified.
- No production implementation work is active under this plan.

#### RTS-001 — `awf.semantic-contract.v1` Draft

At double-review time this was the only immediate execution item. A later owner continuous-execution
authorization supersedes only that stop boundary: after a TaskCard passes, execution may continue to
the first next card whose entry criteria and action-specific authority are satisfied. It does not
weaken phase gates or production/default/release/migration/destructive boundaries.

Execution result: **PASS**. The Draft, 39-case fault matrix and 28-family inventory are versioned in
[`runtime-v2-semantic-contract.md`](../runtime-v2-semantic-contract.md),
[`runtime-v2-fault-matrix.md`](../testing/runtime-v2-fault-matrix.md), and the
[`RTS-001 implementation report`](../tasks/runtime-v2-semantic-contract-draft-implementation-report.md).
Independent Review 2 returned `PASS` with zero findings. Current Python correctness gaps remain
explicit faults for Phase 1; they were not waived or repaired by this documentation gate.

Integration note: PR #96's ordinary cross-platform CI and four of five native cells passed. The
macOS arm64 native cell failed three bounded attempts at the same external
`python-build-standalone` GitHub API `403 rate limit exceeded` boundary. A later evidence-only commit
triggered fresh runs that passed ordinary CI, all five native cells and the aggregate job, clearing
the external block without a workflow change. Do not start live RTS-010 execution until the final
reviewed head integrates.

Deliverables:

- `docs/runtime-v2-semantic-contract.md` with status `Draft`;
- `docs/testing/runtime-v2-fault-matrix.md`;
- a current authority/evidence/record inventory generated from named code paths and reports.

Required contents:

- run/task/role/invocation identities and owners;
- implement/review/rework/blocked/rejected/completed and next-task eligibility;
- current checkpoint, result, validation, trusted import, outbox, inbox, terminal, and ACK boundaries;
- provider start/exit/result ambiguity;
- Git/GitHub/Agent Bus/OS/provider external truth;
- exact workspace/Git/rework lineage;
- legal status projections and owner-only recovery decisions;
- facts labeled separately from target hypotheses.

Exit criteria:

- Every normative Draft transition cites current code, test, or versioned report evidence.
- Every current checkpoint/outbox/inbox phase maps to an outcome or an explicit open question.
- The five-state invocation proposal is expanded or rejected wherever it cannot represent a current
  fault without collapsing distinct effects.
- No CLI hierarchy, file layout, route name, Python class, SQLite table, or language choice is frozen.
- Independent review finds no unmapped known production fault boundary.
- No production code, Runtime state, queue, provider, service, or remote repository is changed.

Go/No-Go:

- **GO:** Draft is complete; proceed to reference acceptance.
- **NO-GO:** Continue Draft extraction only; do not prototype a replacement Runtime.

### Phase 1 — Validate the Current Python Reference

Dependencies: Phase 0 exit passes. Live actions require their own owner-approved TaskCards and fresh
isolated identities.

#### RTS-010 — Fresh post-remediation real PASS TaskCard

Scope: one genuinely useful bounded downstream business task on `main@0ed7812` or later.

Exit criteria:

- Fresh run, branch, delivery identities, model-call counters, and scoped queue baselines are recorded.
- Exactly one implement invocation and one reviewer invocation occur on the PASS path.
- Trusted commit, push, remote SHA, PR tuple, green CI, ReviewReport hashes, terminal decision,
  handler-success ACK, and scoped queue return agree.
- No historical/retained delivery is read, ACKed, requeued, recovered, redispatched, or replaced.
- The first fail-closed boundary is preserved without manual completion.
- A credential-free acceptance report records evidence and limitations.

#### RTS-011 — Deterministic rework acceptance on Python

Scope: one disposable repository and scripted provider; no production repository/event/credential.

Scenario:

```text
implement -> review REQUEST_CHANGES -> one authorized rework -> review PASS -> terminal
```

Exit criteria:

- Invocation count is exactly one implement, one rework, and two reviews.
- Rework binds the exact prior implement delivery, workspace, commit, PR tuple, checkpoint digest, and
  Git manifest.
- Duplicate/redelivery before rework does not start another provider.
- Restart after provider result resumes the same durable state.
- Required outgoing intent, handler success, ACK observation, inbox completion, and terminal ordering
  match the Draft contract.
- The acceptance artifact records which paths are synthetic and makes no real-business claim.

Phase 1 exit criteria:

- RTS-010 and RTS-011 both pass.
- The semantic contract is revised from observed differences and marked `Candidate`, not `Frozen`.
- No new fundamental safety invariant remains undocumented.
- Any failure returns the plan to Phase 0/1; it does not authorize a workaround or rewrite.

### Phase 2 — Compare Simplification Options on One Shared Slice

Dependencies: Phase 1 passes. All slices are disposable and must not read or migrate production state.

#### Shared slice contract

One disposable local Git repository must execute:

```text
awf run
  -> compile immutable run intent
  -> scripted implement invocation
  -> validate/import Artifact and trusted local Git effect
  -> scripted reviewer PASS
  -> terminal
awf status
awf stop
```

No Agent Bus, real provider, GitHub, service manager, or remote Git write is in this slice.

The same fixture injects at least these faults:

1. crash after authorization but before process start;
2. crash after process start before result persistence;
3. provider exit with missing/invalid Artifact;
4. crash after result persistence before validation/import;
5. crash after trusted local effect before outgoing intent persistence;
6. duplicate input before and after completion;
7. corrupt/stale local state;
8. Git/workspace identity drift before terminal acceptance.

#### RTS-020 — Python simplification slice

Purpose: establish whether module/state/CLI restructuring can meet the target without a rewrite.

Constraints:

- isolated experimental module or branch; no production default switch;
- one logical transition writer and one per-invocation journal API;
- no new facade over current facade, provider registry, scheduler, ORM, or async framework;
- current external-boundary fixtures reused where applicable.

Exit criteria:

- The shared normal path and all eight fault outcomes pass.
- The slice uses one normal command and status names one legal next action for each injected failure.
- Authority/record/join measurements are compared with the baseline.
- The report identifies whether remaining complexity is language, compatibility, packaging, lifecycle,
  or external truth.

#### RTS-021 — Storage comparison

Compare the smallest credible atomic-file/journal design and SQLite behind the same slice API.

SQLite is selected only if:

- it removes at least two named current local file-order recovery windows;
- it does not claim atomicity across provider, Bus, Git, GitHub, OS, or another host;
- Windows locking/restart, corruption detection, backup/restore, and schema migration tests pass;
- deleting a derived view cannot lose authoritative recovery state;
- stale cache/state can deny but cannot authorize.

Otherwise retain the simpler atomic-file/journal option. The store choice is recorded in the later
architecture ADR, not inferred from language.

#### RTS-022 — Rust slice, conditional

Run only if RTS-020 shows a native rewrite may materially improve ownership or distribution.

Budget and stop conditions:

- at most two focused implementation TaskCards before the decision review;
- no more than six direct production dependencies in the slice; each requires license, maintenance,
  platform, and supply-chain notes;
- no async Runtime, ORM, embedded Git, plugin framework, generic provider registry, or unsafe
  platform/service framework;
- stop Rust if any supported CI OS still fails the shared slice after the budget, if safe lifecycle or
  process work requires the prohibited expansion, or if production non-comment LOC exceeds 1.5 times
  the Python slice without eliminating an ownership boundary or prerequisite;
- stop Rust if an independent maintainer cannot diagnose and repair one injected fault in one bounded
  review/fix TaskCard using the documented state/evidence.

The numeric thresholds are explicit planning risk budgets, not claims that Rust should naturally meet
them.

#### RTS-023 — Go slice, conditional fallback

Run the same shared slice once if Rust stops for Rust-specific build, dependency, ownership, or team
maintenance reasons and a native Runtime still has measured value.

Exit criteria:

- Same fixtures, measurements, and external boundaries as Python/Rust.
- No weakening of exhaustive transition handling, ambiguity, provenance, or exact identity.
- If Go also fails the shared criteria in one focused TaskCard, return to Python restructuring or the
  native-launcher path; do not open a second native framework effort.

#### RTS-024 — Implementation-choice decision

Decision outcomes:

- **PYTHON REFACTOR:** Python meets semantics/UX and native distribution is not a current requirement.
- **PYTHON + NATIVE LAUNCHER:** Python meets architecture criteria and distribution is the remaining
  blocker; run one candidate against the existing five-target readiness matrix.
- **RUST:** Rust passes its budget and materially improves at least one measured ownership,
  prerequisite, or distribution dimension without safety regression.
- **GO:** Go passes after Rust-specific stop and has lower measured delivery/maintenance cost.
- **REDUCE SCOPE:** keep method/invocation/provenance core and externalize optional Feedback and/or
  lifecycle/distribution responsibilities.
- **STOP:** semantics are still unstable or no candidate improves the current product.

Phase 2 exit criteria:

- One written comparison uses the same fixture and discloses unequal evidence.
- Storage and logical-versus-physical Coordinator decisions cite fault results.
- Owner accepts a product-boundary and implementation-choice ADR.
- Semantic contract is marked `Frozen` only after independent architecture and adversarial review.
- No production Runtime v2 implementation begins on a conditional, tied, or undocumented result.

### Phase 3 — Build the Selected Local Runtime Boundary

Dependencies: Phase 2 explicit GO and owner-approved TaskCards.

This phase applies to the selected Python, Python/launcher, Rust, Go, or reduced-scope outcome. It does
not assume a rewrite.

Deliverables:

- one enforceable Runtime package/module boundary with no `src` to bare packaged-script import cycle;
- immutable compiled RunSpec semantics without duplicate user-visible authority;
- Run transition and per-invocation journal/store interfaces selected in Phase 2;
- current OpenCode coder and Pi reviewer behavior only where the Frozen contract requires it;
- isolated workspace and trusted local Git lifecycle;
- PASS, REQUEST_CHANGES, bounded rework, BLOCKED, and terminal transitions;
- steady-state `run/status/stop` plus documented onboarding/support/admin surfaces.

Exit criteria:

- All Frozen semantic and eight shared fault fixtures pass.
- Provider renderers cannot mutate Runtime state and receive a fully bound InvocationSpec.
- No real provider is repeated after completed or ambiguous state.
- Status is mutation-free under API/static boundary tests.
- Normal local journey uses `run/status/stop`; scenario tests cover install/auth/Git/dirty workspace/
  ambiguity/rework/multi-project errors through explicit support actions.
- Current Python production remains the default unless the selected outcome is Python refactoring;
  no silent cross-Runtime fallback or dual write exists.

Rollback:

- Delete/revert the isolated candidate; production state and defaults were not migrated.
- If Python was refactored in place, every PR is independently reversible and old representations are
  retained until replacement fixtures pass and no live run depends on them.

### Phase 4 — Add Transport, Then Native Lifecycle

Dependencies: Phase 3 passes. Transport and lifecycle are sequential subphases, not one PR.

#### Phase 4A — Agent Bus/cross-machine

Exit criteria:

- One versioned command/result envelope has a stable idempotency key and no Workflow-stage authority.
- Local outgoing intent and transition commit atomically where the chosen store permits; Bus send/ACK
  remains explicitly external.
- Malformed/mismatched delivery fails before provider start.
- Fresh isolated Mac-to-Windows no-model request/result proves real child subprocesses,
  handler-success ACK, and scoped queues `0/0 -> 0/0`.
- Production/retained events remain untouched; Agent Bus is independently versioned.

#### Phase 4B — Native lifecycle

Exit criteria:

- One AgentInstallation/incarnation API preserves project, agent, executable, manager definition,
  desired state, process creation identity where available, and live observation.
- PID, process name, liveness, or desired state alone cannot authorize stop or mutation.
- install/start/status/logs/restart/stop/uninstall pass on claimed macOS, Linux, and Windows managers.
- Windows post-SSH session, restart, exact stop, and login lifecycle have live evidence where CI cannot
  prove them.
- Lifecycle code cannot read, ACK, requeue, recover, or dispatch business deliveries.
- The three-command golden path still works; OS-specific failures expose safe support actions.

Phase 4 rollback:

- Roll back Runtime artifact/version before Agent Bus compatibility where ordering requires it.
- Never roll back Workflow/Bus state. A previous program may resume only if its schema/envelope
  compatibility was proven before upgrade.
- Unknown compatibility fails closed and leaves exact state/evidence intact.

### Phase 5 — Distribution, Real Dogfood, and Default Decision

Dependencies: Phase 4 passes. Release work starts only for the target matrix actually claimed.

Exit criteria:

- Installed artifacts run from an unrelated directory with declared prerequisites and no hidden
  source checkout.
- Checksums, SBOM, provenance/attestation, and claimed signing/notarization/timestamp evidence exist.
- Immutable versioned install, compatibility precheck, program rollback without state rollback, and
  clean uninstall pass.
- One fresh real PASS business dogfood passes with no hidden Python fallback when a native candidate is
  being evaluated.
- Real or controlled rework passes on the selected implementation with exact lineage and invocation
  counts.
- Comparative acceptance reports commands, decisions, prerequisites, model invocations, manual
  interventions, fault outcomes, state/ownership counts, artifact count, and independent diagnosis.
- Independent review recommends either default switch, continued Python default, reduced scope, or
  stop. A green build alone is insufficient.

Go/No-Go:

- **SWITCH:** selected implementation meets or exceeds current Python semantic/safety evidence and the
  owner explicitly accepts the default change.
- **KEEP PYTHON:** candidate does not materially improve measured product dimensions.
- **STOP/REDUCE:** distribution/lifecycle cost exceeds the accepted product boundary.

Publishing release assets remains a separate owner-authorized action.

### Phase 6 — Compatibility and Old-Runtime Closeout

Dependencies: explicit default-switch decision and a bounded coexistence window.

Per-item deletion gate:

1. classify the item as current production, historical compatibility, safety semantics, evidence,
   developer tooling, or optional product;
2. identify retained runs/deliveries/state and obtain owner abandonment/migration authority;
3. add or cite a language-neutral replacement fixture for every safety behavior;
4. prove replacement behavior and rollback before deletion;
5. delete representation and compatibility tests only after the replacement gate;
6. update current architecture/HANDOFF/ROADMAP/release truth in the same closeout.

Required dispositions:

| Item | Earliest deletion condition |
|---|---|
| v1/v2 routes | No retained dependency; mismatch/ACK/selection fixtures pass. |
| v3 route | New transport passes real cutover and retained-state closeout. |
| legacy TaskCard fallback | Explicit selection/integrity fixtures replace it. |
| profiles/snapshots/registries | AgentInstallation passes exact three-OS identity and recovery. |
| RunManifest/RunContract/authority manifest | One compiled RunSpec proves intent/authority/hash equivalence. |
| checkpoint/outbox/inbox | Selected journal/store passes all fault and ACK-order fixtures. |
| shell/direct/source fallbacks | Installed and developer/oracle entry contracts are separated and tested. |
| facade | Replacement scenario journey is accepted; no third facade remains. |
| node/listener/service/process/lease records | Replacement preserves install/incarnation/live exact-stop semantics. |
| Feedback | Owner chooses separate tool, retained Python utility, or deletion independently of business loop. |

Phase 6 exit criteria:

- Every old run/delivery/state surface is drained, terminal, owner-abandoned, migrated, or explicitly
  retained with an owner and reason.
- No normal command or production service silently enters an old Runtime.
- No required semantic fixture is deleted with its old implementation.
- Repository docs expose one current product truth.
- Program rollback compatibility for the bounded window is documented; state is never rolled back.

## 7. Critical Path and Dependency Check

```text
RTS-001 Draft semantic/fault contract
  -> RTS-010 fresh real PASS
  -> RTS-011 deterministic Python rework acceptance
  -> Contract Candidate
  -> RTS-020 Python simplification slice
  -> RTS-021 storage comparison
  -> if native value remains: RTS-022 Rust slice
       -> if Rust-specific stop and native value remains: RTS-023 Go slice
  -> RTS-024 owner product/language/storage/topology decision
  -> Contract Frozen
  -> Phase 3 selected local Runtime boundary
  -> Phase 4A transport
  -> Phase 4B lifecycle
  -> Phase 5 distribution + real dogfood + default decision
  -> Phase 6 compatibility/old-Runtime closeout
```

There is no dependency cycle. Documentation and isolated fixture preparation may precede live
business acceptance, but Candidate/Frozen/production entry gates may not.

## 8. Evidence and Test Requirements

### Minimum language-neutral conformance set

- legal and illegal stage transitions;
- duplicate before start, after start, and after completion;
- ambiguous provider start;
- Artifact parse/hash/provenance rejection;
- exact implement-to-rework lineage and exhausted budget;
- outgoing intent/send retry and handler-success/ACK ordering;
- terminal idempotence and conflicting terminal replay;
- workspace/Git/PR/CI drift;
- stale/corrupt/unknown state and cache;
- exact process/incarnation ownership;
- read-only status and one legal next action;
- external truth unavailable/stale observations.

### Per-change evidence

- one TaskCard and one focused branch/PR;
- behavior locked before cleanup or representation deletion;
- local `git diff --check`, changed-path audit, and safe static checks;
- Python/Rust/Go lint, test, type/static, build, and platform work in GitHub CI or an authorized node
  under the machine policy;
- independent review for state transitions, process boundaries, migration, compatibility deletion, and
  default switch;
- versioned evidence read and summarized after CI; no success claim from job status alone.

### Live evidence safety

- fresh isolated identities, state, branches, deliveries, and scoped queues;
- no historical event reuse or replacement;
- stop at the first fail-closed boundary;
- no manual ACK/requeue/redispatch to manufacture completion;
- no credential, token, private URL, payload, or secret in reports.

## 9. Fallback and Rollback Matrix

| Failure point | Required fallback | Rollback boundary |
|---|---|---|
| Contract Draft incomplete | Continue documentation/fixtures. | No code/state exists to roll back. |
| Fresh PASS or rework reference fails | Fix only the exposed Python correctness/contract gap, then rerun with fresh authority. | Preserve failed evidence; no manual queue repair. |
| Python slice meets goals | Choose Python refactor; do not rewrite for its own sake. | Revert isolated slice or land small reversible PRs. |
| Python architecture works, packaging fails | One native-launcher/real-CPython feasibility candidate. | Keep wheel/environment production path. |
| Rust crosses a stop threshold | Stop Rust; run one Go slice only if native value remains. | Delete/revert disposable Rust slice; no migrated state. |
| Go slice fails | Return to Python refactor/launcher or reduce scope. | Delete/revert disposable Go slice. |
| SQLite does not reduce named faults | Keep atomic-file/journal store. | Candidate databases contain disposable copied state only. |
| Coordinator topology adds availability/recovery ambiguity | Keep logical single writer without a new always-on network service. | No production coordinator cutover. |
| Cross-machine/lifecycle gate fails | Keep current Python production path; repair only via new scoped TaskCard. | Roll back candidate artifact, never state. |
| Release/default acceptance fails | Keep Python default and candidate private. | No publication or implicit fallback. |
| Cutover compatibility is unknown | Refuse rollback/start and preserve evidence for owner decision. | Never reinterpret or downgrade state. |

## 10. Decision Checkpoints

| Checkpoint | Required decision | Default without approval/evidence |
|---|---|---|
| D0 after Phase 0 | Draft accurately describes current semantics/faults. | Continue extraction only. |
| D1 after Phase 1 | Python is a valid reference and contract may become Candidate. | No candidate Runtime slice. |
| D2 after Phase 2 | Product boundary, language, store, and Coordinator topology. | Keep Python production and stop. |
| D3 after Phase 3 | Local selected Runtime boundary is acceptable. | Do not add Bus/lifecycle. |
| D4 after Phase 4 | Cross-machine and lifecycle semantics are equivalent. | Keep current Python operations path. |
| D5 after Phase 5 | Publish candidate and/or change default. | Keep artifacts private and Python default. |
| D6 during Phase 6 | Migrate/abandon retained state and delete old Runtime items. | Preserve old representation/evidence. |

## 11. Double Review Reconciliation

Double-review verdict: **`CONDITIONAL GO` for simplification/evidence; `NO-GO` for a precommitted Rust
rewrite, SQLite store, or physical single Coordinator.**

### Retained and strengthened

- preserve ACK, ambiguity, idempotency, provenance, exact identity, structured argv, and Bus boundary;
- require one fresh post-remediation real PASS and deterministic rework acceptance;
- use a small vertical slice and independent review before a default switch;
- avoid permanent dual Runtime and delete compatibility only after closeout;
- pursue a three-command steady-state golden path and native distribution only with evidence.

### Modified

- semantic contract changes from immediate freeze to `Draft -> Candidate -> Frozen`;
- Rust changes from preferred target to gated candidate;
- four state classes change from acceptance requirement to measured budget with multiplicity;
- SQLite changes from target design to a fault-tested option;
- one Coordinator changes from physical architecture assumption to logical-single-writer semantics;
- `run/status/stop` changes from complete surface to golden path plus onboarding/support/admin;
- Python freeze permits bounded simplification/reference work until the implementation-choice gate.

### Rejected

- rewrite as a necessary condition for product simplicity;
- fresh business PASS as the only material timing blocker;
- binary candidate failure as proof that Rust is next;
- deleting all compatibility based only on the absence of external users;
- beginning full target architecture or Cargo scaffolding before comparative evidence.

### Open evidence gaps

- post-remediation real business PASS;
- complete deterministic rework artifact;
- current authority/fault inventory;
- Python versus Rust/Go shared-slice measurements;
- SQLite Windows/fault evidence;
- physical Coordinator recovery model;
- support-scenario UX decisions;
- owner product-boundary ADR and retained-state audit.

### Next decision point

RTS-001 passed and the Draft is complete enough to enter Phase 1 under the later owner execution
authorization. The next planned card is RTS-010, but its fresh live/business TaskCard must still
satisfy its own entry criteria and scoped authority before any model, queue, remote, or downstream
mutation. Do not choose a language, store, Coordinator deployment, or production migration at this
point.

## 12. Plan Completion Definition

This plan is complete only when every phase either passes its measurable exit criteria or is stopped by
an explicit owner decision; all current and selected-Runtime semantics have linked evidence; retained
state is closed safely; and HANDOFF, ROADMAP, architecture, release docs, CLI, and installed behavior
state one current product truth. Report progress by last passed gate, never by percentage.
