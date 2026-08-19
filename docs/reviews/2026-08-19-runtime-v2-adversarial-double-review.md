# Agent Workflow Runtime v2 Adversarial Double Review

Date: 2026-08-19

Status: Independent draft review. This document is not an ADR and does not authorize implementation,
dispatch, migration, or release work.

## 1. Review Metadata and Baseline

| Item | Observed fact |
|---|---|
| Current branch | `main` |
| Current HEAD | `0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2` |
| Original Review basis | `main@0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2` |
| HEAD delta from basis | None; the current HEAD is the exact Review basis. |
| Worktree before this review | Not clean: the original Review was the sole untracked path. It was preserved and not edited. |
| Original Review | `docs/reviews/2026-08-18-global-architecture-product-simplicity-runtime-rewrite-review.md` |
| Selected plan source | `.omx/plans/runtime-v2-development-plan.md` |
| Reconciled repository plan | `docs/plans/runtime-v2-development-plan.md` |

The original Review is not contained in `HEAD`; it is an untracked draft whose own status says that
owner acceptance is required. Its code and evidence references nevertheless resolve against the exact
commit it names, so its factual claims can be checked without a basis drift qualification.

### Plan candidates and selection

| Candidate | Authority evidence | Decision |
|---|---|---|
| Original Review section 14 | High-level proposal embedded in the Review; not an independent execution plan. | Input only. |
| `.omx/plans/runtime-v2-development-plan.md` | Dated 2026-08-18, written after the Review, directly cites Review/HANDOFF/ROADMAP, and contains complete phases, gates, fallbacks, and acceptance criteria. | Selected as the latest and most complete plan source. |
| `ROADMAP.md` | Tracked project roadmap and current operations truth, but it does not adopt or schedule Runtime v2/Rust. | Constraint/source of current product truth, not the rewrite plan. |
| `HANDOFF.md` | Tracked operational truth and evidence index, not a rewrite implementation plan. | Evidence source only. |

The selected plan was ignored by Git and explicitly proposed making a tracked copy. This review
therefore reconciles it into `docs/plans/runtime-v2-development-plan.md`; the `.omx` path is no longer
allowed to be the sole planning authority.

### Checks performed

- Git branch, HEAD, status, history, basis delta, ignore rules, document timestamps, and references.
- Static inspection of the original Review, selected plan, `HANDOFF.md`, `ROADMAP.md`, constitution,
  Runtime architecture documents, TaskCards, acceptance reports, and implementation reports.
- Static sampling of the CLI parser, Python-to-packaged-script bridges, RunLedger/context packet,
  checkpoint/outbox/inbox, status aggregation, node lifecycle records, provider subprocess boundary,
  and v1-v3 route handling.
- Repository measurements: 12 Python files under `src/agent_workflow`, 20 Python scripts, 19 test
  modules, 478 test functions, and 31,867 Python lines across `src`, `scripts`, and `tests`.
- Presence and internal consistency checks for the three-card business acceptance, fresh-machine
  no-model acceptance, binary readiness, implement-to-rework lineage, and causal-status evidence.
- `git diff --check`, plan/review cross-reference inspection, dependency-order inspection, and final
  allowed-path inspection after documentation edits.

### Checks not performed

- No paid or real provider/model invocation.
- No Agent Bus queue, ACK, requeue, payload, listener, or retained-delivery operation.
- No remote host, service manager, scheduler, GitHub mutation, push, PR, release, or publication.
- No Pytest, Ruff, Cargo, Rust, Go, signing, packaging, or live three-OS execution.
- No proof that the repository's historical remote PR/CI/queue statements remain live today; the
  versioned reports were checked as repository evidence, not re-enacted.

### Original evidence survival and validity

| Evidence sampled from the original Review | Exists at current HEAD? | Current validity |
|---|---|---|
| Operations CLI and Python/package bridges | Yes: `src/agent_workflow/cli.py`, `node.py`, `status.py`, and packaged `scripts/` | Valid current implementation evidence; the cited menu, dynamic imports, lifecycle, and status joins remain. |
| RunLedger/context packet and checkpoint/outbox/inbox code | Yes: `scripts/awf_control_plane.py`, `awf_role.py`, and related tests | Valid current safety/recovery evidence; it does not prove a replacement store or topology. |
| Remediation TaskCards and reports | Yes: canonical state root, truthful lifecycle, durable profile, compiler/gate, rework, causal status, structured handler, facade, and binary documents are present. | Valid evidence of why current invariants exist; completion reports are not language-neutral conformance fixtures by themselves. |
| Three-card business dogfood acceptance | Yes: `docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md` | Valid historical PASS evidence for the earlier runtime; explicitly insufficient for the post-remediation business gate and contains no rework. |
| Fresh-machine no-model acceptance | Yes: `docs/tasks/fresh-machine-usability-acceptance-closeout-report.md` | Valid isolated three-OS/Fast and Mac-to-Windows Deep evidence; it invoked no model and does not authorize a business TaskCard. |
| Implement-to-rework transition report | Yes: `docs/tasks/implement-rework-workspace-transition-implementation-report.md` | Valid focused synthetic lineage evidence; not an end-to-end accepted business or full deterministic loop artifact. |
| Binary release readiness report | Yes: `docs/tasks/binary-release-readiness-report.md` | Valid `NO_GO_PRODUCTION_BINARY` evidence for the measured candidates; not evidence that Rust or Go is superior. |
| Current test corpus | Yes: 19 tracked test modules and 478 statically counted test functions. | Strong regression asset; tests were not executed in this review and many remain implementation-coupled until classified. |

## 2. Executive Verdict

**`CONDITIONAL GO` for a bounded Runtime simplification and evidence program.**

**`NO-GO` for treating a Rust rewrite, SQLite, a physically singular Coordinator, or four state
classes as already-selected implementation decisions.**

The original Review correctly identifies a real product mismatch and accidental complexity. The
installed `awf` surface is a Runtime even though the constitution and architecture still describe a
thin stateless validator. The normal CLI exposes setup, preflight, dispatch, recovery, feedback, and
eleven node commands. `src` dynamically imports packaged `scripts`, and status joins multiple durable
records plus external systems. Those are current repository facts.

The same evidence does not establish that a language rewrite is necessary. Most hard failures arose
from state ownership, lifecycle identity, external-effect ordering, compatibility, and UX boundaries.
Python can represent a stricter state API, use a transactional store, remove compatibility, and offer
a smaller CLI. Conversely, Rust cannot make Agent Bus, provider processes, Git, GitHub, or OS manager
effects transactional. The language and storage choices are hypotheses that need the same bounded
fixture, metrics, and failure cases.

The recommended direction is therefore:

1. keep Python as the only production Runtime;
2. write a language-neutral semantic contract as a **Draft**;
3. calibrate it with one fresh post-remediation PASS run and one deterministic rework acceptance;
4. measure one narrow Python simplification slice before concluding a rewrite is needed;
5. if a native rewrite remains justified, compare a bounded Rust slice against the same baseline,
   then use Go only when Rust-specific delivery/maintenance thresholds fail;
6. freeze a contract and select storage/topology/language only after those results.

## 3. Original Review Verdict Table

| Original conclusion | Verdict | Repository evidence | Plan impact |
|---|---|---|---|
| The shipped product is already a Runtime while documented boundaries still say stateless validator. | `CONFIRMED` | Full operations CLI, packaged scripts, dynamic `sys.path` bridges, subprocess/lifecycle code, and HANDOFF evidence. | Add a product-boundary ADR gate before production v2 work. |
| Safety goals such as success-before-ACK, no replay after ambiguity, fail-closed authority, and exact provenance are necessary. | `CONFIRMED` | RunLedger gates, checkpoint recovery, outbox/inbox reports, rework-lineage report, and real business acceptance. | Preserve as language-neutral conformance fixtures before deleting any representation. |
| The implementation shape and normal operator surface are overgrown. | `CONFIRMED` | Seven-command benchmark, eleven node subcommands, manifest/profile/contract exposure, and status joins. | Keep a three-command golden-path objective, but add onboarding/support/admin scenario acceptance. |
| A rewrite is required to achieve simplification. | `UNSUPPORTED` | No Python internal-refactor baseline and no native-language vertical slice exist. The cited defects are mostly boundary/ownership defects, not Python impossibilities. | Replace “rewrite plan” with a simplification and implementation-choice plan. |
| Rust is preferred over Go and Python restructuring. | `UNSUPPORTED` | No Rust or Go slice, dependency graph, incident exercise, or delivery-velocity measurement exists. Typed states help only inside one process/store boundary. | Rust becomes one gated candidate, not the default target. |
| Python should be feature-frozen immediately after one business gate. | `PARTIALLY CONFIRMED` | Dual production drift is real, but reference-preserving Python simplification may be the winning option and may be required to expose a clean contract. | Freeze only incompatible expansion; permit bounded simplification, safety fixes, and fixture extraction until the implementation-choice gate. |
| Four AWF-owned authoritative classes materially reduce authority. | `PARTIALLY CONFIRMED` | The proposed count excludes per-host `AgentInstallation` and external truth, and `InvocationStore` exists once per worker. It is a useful budget, not a proven count. | Inventory authority domains and persistent record families; measure joins and recovery cases rather than count names alone. |
| `RunStore + InvocationStore` and transactional outboxes eliminate the important file-order failures. | `PARTIALLY CONFIRMED` | A local transaction can remove some checkpoint/outbox ordering windows, but cannot atomically include model launch, Bus send/ACK, Git, GitHub, or another machine's store. | Compare atomic-file journal and SQLite on named faults; retain ambiguity and idempotency semantics. |
| One Coordinator should own all Workflow transitions. | `PARTIALLY CONFIRMED` | A single logical writer clarifies authority, but the current plan does not specify coordinator availability, restart, location, or worker/result recovery. | Require logical-single-writer semantics; defer physical always-on Coordinator topology. |
| `prepared/started/completed/failed/ambiguous` is a sufficient invocation state model. | `UNSUPPORTED` | Existing checkpoints distinguish result persistence, validation, trusted import, handoff prepared/sent, inbox completion, and terminal consumption. The five labels do not yet map all those faults. | Contract draft must map every current fault/effect boundary before state names freeze. |
| Compatibility can eventually be deleted because there are no external users. | `PARTIALLY CONFIRMED` | Alias/shim and v1/v2 branches are candidates, but v3, profiles, RunManifest/Contract, checkpoint/outbox/inbox, exact-stop records, and source-mode tooling carry current use or safety meaning. | Delete only after per-item semantic fixture, retained-state closeout, replacement proof, and rollback point. |
| `awf run/status/stop` is the complete product surface. | `PARTIALLY CONFIRMED` | It is a plausible steady-state menu, not sufficient for install, provider auth, fork ambiguity, Bus outage, dirty workspace, upgrades, rollback, multi-project selection, or ambiguous invocation. | Define three-command golden path plus explicit `init`, `doctor`, read-only `debug`, and exact-target `admin` support surfaces. |
| A fresh post-remediation business run is required before full production v2 work. | `CONFIRMED` | Existing accepted three-card dogfood predates the final remediation and had no rework. | Keep as a production-implementation gate, not a documentation/prototype gate. |
| The fresh business run is the only material timing blocker. | `REJECTED` | Product-boundary authority, current authority/fault inventory, deterministic rework evidence, contract maturity, and implementation-choice evidence are also missing. | Add explicit evidence and decision gates; permit Draft/fixture/spike work before them. |
| Binary readiness proves a native rewrite is the next step. | `UNSUPPORTED` | The report proves current candidates fail the frozen Python re-entry contract and recommends a native-launcher/real-CPython experiment; it does not compare rewritten Rust/Go/Python architectures. | Treat distribution as a later decision driver and keep the launcher experiment available. |
| Permanent dual Runtime is undesirable. | `CONFIRMED` | Two implementations would duplicate recovery, lifecycle, and conformance burdens in a small-team project. | Any coexistence window is explicit, versioned, non-dual-write, and bounded by a cutover decision. |

## 4. Strongest Supporting Evidence

1. **The declared and shipped boundaries conflict.** `src/agent_workflow/cli.py` exposes validation,
   setup, plan, dispatch, preflight, feedback, run, status, facade, and node lifecycle. Both CLI and
   node modules add packaged operations scripts to `sys.path` and import them. This is not a thin,
   stateless validator in implementation terms.
2. **The safety semantics are backed by incidents and tests.** The rework report binds a new rework to
   the exact prior implement workspace, checkpoint, PR tuple, commit, and Git manifest. The accepted
   dogfood proves trusted Git/PR/CI and handler-success ACK ordering. These are not removable ceremony.
3. **The current state representation is expensive to join.** Status explicitly reads lifecycle,
   RunLedger, delivery checkpoints, live files, queue observations, Git/GitHub facts, and an independent
   Feedback outbox. Simplifying representation and projection is justified.
4. **The normal UX is not yet simple.** The fresh-machine benchmark needed seven commands and five
   decision groups. A smaller normal path is a real product need even if the support surface remains.
5. **Compatibility and packaging impose measurable cost.** Production still handles v1-v3, source and
   installed resource paths, Python re-entry, aliases, and older TaskCard selection. The binary matrix
   found 15/15 failures at the Python re-entry gate for the evaluated candidates.

## 5. Strongest Contrary Evidence

1. **The current Runtime is proven in the hardest external boundaries.** Three real business cards,
   three-OS no-model readiness, cross-machine subprocess proof, trusted Git/PR/CI, ACK ordering, exact
   stop, and rework-lineage fixtures already exist. A rewrite reopens all of them.
2. **The repository has a large migration surface.** Static counting found 31,867 Python lines across
   production and tests, 478 test functions, and extensive implementation-coupled evidence. Size does
   not forbid a rewrite, but it contradicts the assumption that a small semantic port is already known.
3. **External truth dominates the hardest recovery cases.** Model start, Agent Bus send/ACK, Git refs,
   GitHub PR/CI, native managers, and provider login cannot join one SQLite transaction. A new store
   reduces local serialization windows, not the distributed recovery problem.
4. **The Review has no comparative experiment.** Rust's alleged advantage, Go fallback cost, Python
   refactor ceiling, SQLite benefit, and Coordinator topology are all inferred.
5. **The recommended launcher path points the other way.** The binary readiness report names a small
   native launcher plus relocatable real CPython as the shortest legal next candidate. That option must
   be invalidated by measured architecture or distribution evidence, not preference.

## 6. State and Recovery Challenge

### Current versus proposed state

Counting only labels is misleading. The useful comparison is authority domain, persistent
representation, owner, and joins needed for recovery.

| Dimension | Current Python Runtime | Original target | Double-review finding |
|---|---|---|---|
| AWF logical authority domains | owner intent; Workflow transition; invocation/recovery; workspace/provenance; host lifecycle; optional Feedback | ProjectConfig; RunSpec; RunStore; InvocationStore, with AgentInstallation excluded | The target consolidates representations but does not reduce all ownership domains. |
| Internal record families | TaskCard, RunManifest, RunContract, authority manifest, ledger/context packet, checkpoint, outbox, inbox, workspace/evidence, profile/snapshot/registries/install/desired/process/lease, Feedback records | Four named Workflow classes plus per-host AgentInstallation and evidence | Current has at least fifteen control/evidence record families; target still has per-worker stores and host state. The proposed “four” is a budget, not an apples-to-apples result. |
| Internal ownership boundaries | owner/compiler, transition handlers, worker local effects, lifecycle manager, optional Feedback | Coordinator, each worker, each host installation | A physical Coordinator may clarify one boundary while adding a new availability/recovery dependency. |
| External truth boundaries | Agent Bus, Git, GitHub, OS manager, provider CLI | Same five systems | Unchanged. Most non-transactional joins remain. |

### Crash/recovery cases that remain after SQLite

| Boundary | Current requirement | Effect of local transactional storage |
|---|---|---|
| authorization before provider start | duplicate/stage/rework/provenance gate | Can atomically record authorization/prepared state. |
| provider started, result absent | never auto-repeat an ambiguous invocation | Unchanged; provider process is external. |
| provider returned, Artifact invalid or import incomplete | retain exact result/evidence and fail closed | Storage can improve local ordering; validation and filesystem/Git effects remain external. |
| outgoing intent committed, Bus send outcome unknown | idempotent resend keyed to stable intent | Outbox helps, but send/ACK is still outside the transaction. |
| Bus handler success versus ACK | ACK only after required durable local effect | Unchanged; Bus owns transport state. |
| trusted Git commit/push/PR/CI | re-read exact external truth and bind evidence | Unchanged. |
| service launched before process/lease observation | refuse stale/name/PID-only ownership | A host store may consolidate records; live OS truth still requires a join. |
| coordinator unavailable after worker result | recover result without authorizing duplicate work | New explicit target-architecture case; not addressed by naming one Coordinator. |

SQLite is acceptable only if a fault experiment shows which current ordering failures it removes and
defines corruption, locking, backup, schema migration, and Windows behavior. A transactional outbox is
not semantically equivalent to the current checkpoint/inbox/outbox chain unless conformance fixtures
prove the same authorization, ambiguity, downstream-send, handler-success, and ACK outcomes.

## 7. Compatibility and Safety Disposition

| Surface proposed for deletion | Classification now | Required treatment |
|---|---|---|
| v1/v2 routes | Historical compatibility | Freeze rejection/selection/ACK fixtures, verify no retained run needs them, then delete. |
| v3 route | Current production protocol | Keep until a new protocol passes real cross-machine cutover and retained-state closeout. |
| legacy TaskCard fallback | Historical form carrying selection/integrity lessons | Delete form only after explicit-selection fixtures cover mismatch and audit identity. |
| profiles | Current production configuration and lifecycle binding | Hide from beginner UX; replace only after AgentInstallation proves equivalent exact identity. |
| RunManifest/RunContract/authority manifest | Current owner/compiler/dispatch safety gates | Merge representation only after one compiled RunSpec proves authority and hash equivalence. |
| checkpoint/outbox/inbox | Current crash, dedupe, handoff, and ACK semantics | Preserve semantics and fault fixtures; a table is not proof of equivalence. |
| shell shim | Historical/source compatibility | Delete from production when installed and developer entry contracts are explicitly separated. |
| Python re-entry/source fallback | Current packaged lifecycle and editable-development behavior | May leave the production product; retain an explicit developer/oracle path where still required. |
| facade | Current beginner experience | Keep until the replacement golden path wins scenario tests; do not create a third facade. |
| node/listener/service/process/lease | Current lifecycle representation with real exact-stop lessons | Merge names/records only after exact install/incarnation/live-observation conformance passes on three OSes. |
| Feedback | Optional dogfood pipeline | Remove from normal UX; decide separately whether it remains a Python tool or separate product. |

## 8. UX Verdict

`awf run`, `awf status`, and `awf stop` are a good **steady-state golden path**, not a complete product
surface. The product must still handle:

| Scenario | Normal/hidden behavior | Required explicit surface when unresolved |
|---|---|---|
| first install/project enrollment | automatic only when every fact is unambiguous | `awf init` or guided onboarding |
| provider auth expired | probe before invocation | causal error with provider-owned login action |
| fork/upstream ambiguity or dirty workspace | never guess or mutate | status/doctor diagnosis and exact remediation |
| Bus unavailable or stale readiness | safe deny and bounded retry of checks | `doctor`/read-only `debug` evidence |
| ambiguous invocation | never auto-replay | status names ambiguity and an owner-authorized admin action |
| rework | automatic only from a valid reviewer transition and remaining budget | status exposes lineage/budget, not manual stage flags |
| upgrade/rollback | compatibility precheck and immutable program versions | exact-target `admin upgrade/rollback` |
| multiple projects/agents | derive from cwd only when unique | explicit project/agent selector |
| OS-specific lifecycle failure | hidden on success | support output names native manager fact and safe next action |

Acceptance must measure commands and decisions per scenario. Hiding a command without removing the
decision or failure mode is complexity transfer, not simplification.

## 9. Language and Architecture Recommendation

| Option | Project-specific assessment | Decision role |
|---|---|---|
| Python internal refactor | Reuses all current external-boundary proof; can modularize state/CLI and test a transactional store without a port. Does not by itself solve native distribution. | **First comparative baseline and viable final choice.** |
| Python + native launcher | Existing readiness report identifies it as the shortest legal distribution experiment. It keeps Python process/lifecycle semantics and bundle complexity. | **Use if architecture simplifies in Python and distribution is the remaining blocker.** |
| Go Runtime v2 | Simple native build/process model and likely lower small-team incident burden, but has no current project evidence and still requires a full semantic port. | **Native fallback/candidate after a shared slice exists.** |
| Rust Runtime v2 | Strong exhaustive enums and native integration can help local invariants, but compile/dependency/FFI/platform debugging and team capacity are unmeasured. It cannot solve external transactions. | **Gated candidate, not preferred by default.** |
| Temporary hybrid | Needed for oracle/cutover only. | **Bounded transition, never dual-write or permanent.** |
| Reduce Runtime scope | Externalize optional Feedback and possibly advanced lifecycle/distribution; retain method, invocation safety, provenance, and transport boundaries. | **Required product-boundary alternative in the ADR.** |

Recommended architecture principles, independent of language:

- one **logical** writer for each run transition; physical Coordinator deployment remains undecided;
- one durable per-invocation journal owned by the executing host;
- stable idempotency identities across transport redelivery;
- external effects represented as intent, attempt, observation, and ambiguity, never exactly-once claims;
- derived status cannot authorize mutation;
- one compiled immutable RunSpec concept, but its storage representation is not frozen;
- provider adapters remain pure structured argv/stdin/file renderers;
- Agent Bus remains transport-only and independently released;
- native lifecycle identity stays separate from Workflow transition authority.

## 10. Timing Gates and Near-Term Sequence

### Work allowed before fresh business validation

- document the current authority/record/fault inventory;
- draft, but do not freeze, the semantic contract;
- extract deterministic language-neutral fixtures;
- run local no-model/file-store/SQLite comparison experiments;
- measure a strictly isolated Python simplification slice;
- prepare TaskCards and acceptance documents without dispatching them.

### Required before production Runtime v2 implementation

1. Owner accepts a product-boundary ADR: Runtime first-class versus reduced/external scope.
2. One fresh post-remediation real PASS TaskCard proves model, trusted Git/PR/CI, review, terminal,
   handler-success ACK, and scoped queue evidence.
3. One deterministic `REQUEST_CHANGES -> rework -> review` acceptance proves exact lineage and no
   duplicate invocation on the current Python reference.
4. The semantic contract reaches Candidate status after being corrected by those two results.
5. The current-versus-target authority, ownership, and fault matrix has an independent review.

### Required before freezing contract or choosing language/storage/topology

- the same bounded no-model slice runs against the Python baseline and proposed candidate;
- named fault cases produce equivalent safe outcomes;
- SQLite versus atomic-file/journal results identify eliminated and remaining recovery windows;
- the Rust/Go/Python decision records measured maintenance, dependency, CI, diagnosis, and packaging
  evidence;
- no decision depends only on the count of classes, commands, or files.

The semantic contract lifecycle is `Draft -> Candidate -> Frozen`. Drafting begins now. Candidate
requires the reference evidence. Frozen requires the implementation-choice slice and independent
review. This prevents both premature freeze and undocumented semantic drift.

## 11. Missing Evidence and Uncertainty

- No post-remediation real business TaskCard has completed on current main.
- No accepted business run has exercised rework; only focused synthetic implementation evidence exists.
- No end-to-end deterministic rework acceptance records all model/invocation, Git, review, ACK, queue,
  and terminal facts in one artifact.
- No current authority-versus-evidence inventory generated directly from code exists.
- No Python simplification, Rust, or Go slice provides comparative LOC, dependency, failure, or
  maintainer-diagnosis data.
- No SQLite fault/locking/corruption/backup/migration experiment exists on Windows.
- No physical Coordinator lifecycle or coordinator-unavailable recovery contract exists.
- No scenario matrix proves that `run/status/stop` reduces decisions rather than hiding them.
- No owner ADR promotes Runtime into the product boundary or chooses reduced Runtime scope.
- No current live audit establishes which retained Python runs/deliveries/state may be deleted.

## 12. Recommended Immediate Task

Create one documentation-only `awf.semantic-contract.v1` **Draft** plus a machine-readable fault table
for the current Python reference. It must map, without redesigning production code:

- every authorization and ownership boundary;
- each existing checkpoint/outbox/inbox phase;
- provider start/result/validation/import ambiguity;
- Bus send/handler-success/ACK ordering;
- Git/PR/CI and OS-manager external truth;
- exact rework lineage;
- legal status projection and owner-only recovery decisions.

Exit when every state and transition cites an existing code/test/report source, unsupported target
states are labeled hypotheses, and an independent reviewer can identify any unmapped current fault.
Do not initialize Rust, choose SQLite, dispatch a business event, or freeze the contract in this task.

## 13. Fact, Inference, and Experiment Labels

- **Facts:** current Git state; file/code structure; CLI commands; existing record families; versioned
  acceptance/report content; current tests and static counts; original Review/plan status.
- **Inferences:** current shape is difficult for a small team; a logical single writer and consolidated
  local journal are likely simpler; permanent dual Runtime is likely too costly.
- **Hypotheses requiring experiments:** Rust is preferable; Go is cheaper to maintain; Python cannot be
  simplified enough; SQLite reduces total recovery complexity; a physical Coordinator is necessary;
  four state classes are sufficient; three normal commands materially reduce user decisions.

## 14. Final Decision

Proceed with the reconciled plan only through its Draft/evidence/comparative gates. Do not treat the
original Review as an accepted ADR, do not treat its Rust/SQLite/Coordinator choices as settled, and
do not begin production Runtime v2 implementation until the revised production-entry criteria pass.
