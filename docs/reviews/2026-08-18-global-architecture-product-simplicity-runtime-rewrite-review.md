# Agent Workflow Global Architecture, Product Simplicity, and Runtime Rewrite Review

Date: 2026-08-18

Review basis: `main@0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2`

Status: Draft review. These recommendations require owner acceptance before they become an ADR,
TaskCard, migration, or implementation authority.

Scope: architecture review, target architecture, UX redesign, language decision, rewrite timing, and
rewrite proposal only. No production implementation is authorized by this document.

## 1. Executive Conclusion

### Decision

**Final timing verdict: `REWRITE AFTER CURRENT REMEDIATION + VALIDATION`.**

The preferred target production Runtime is **Rust**, through a temporary hybrid period in
which Python remains the production fallback and behavioral oracle. This is not a recommendation to
translate the existing Python modules. It is a recommendation to extract the small set of proven
Workflow semantics and safety invariants, redesign the product and state boundaries, and build a
smaller Runtime v2. Rust is the working target, not an irreversible language commitment: a bounded
vertical slice must prove simpler state ownership, a smaller operator surface, and maintainable
cross-platform lifecycle work before the project commits to completing the rewrite. Go and the
Python/native-launcher bridge remain explicit fallback decisions if it fails that gate.

The repository is **not quite at the implementation-start gate today**:

- The architecture/usability remediation is merged.
- The isolated Mac/VPS/Windows Fast and Mac-to-Windows Deep no-model acceptance is green
  ([closeout](../tasks/fresh-machine-usability-acceptance-closeout-report.md#outcome)).
- The three-card real business dogfood proved the serial coder/reviewer/terminal path, trusted Git/PR
  provenance, green CI, handler-success ACK, and empty queues
  ([acceptance](../tasks/dousansi-three-card-dogfood-acceptance-20260809.md#outcome)).
- However, that business dogfood predates the final 2026-08-14 through 2026-08-17 remediation. The
  final shape has not yet completed a fresh real business TaskCard, and no accepted business run has
  exercised `REQUEST_CHANGES -> rework -> review`.

Therefore:

- **Start semantic-contract extraction and Rust v2 design now.**
- **Do not start full Rust production implementation until one fresh post-remediation real business
  vertical slice passes.** Prefer a bounded card that naturally exercises rework; if no legitimate
  change request occurs, run a separate deterministic rework acceptance fixture rather than
  manufacturing a false business failure.
- After that gate, freeze Python Runtime features: bug fixes, conformance fixtures, and reference
  evidence only.

### Overall assessment

The current implementation is **semantically strong but architecturally overgrown**.

The necessary complexity is real:

- handler success before business ACK;
- one durable authorization before an expensive model invocation;
- no automatic replay after an ambiguous `model_started` boundary;
- fail-closed route, stage, attempt, rework, Artifact, and provenance gates;
- exact process/workspace ownership;
- structured argv with no business shell interpretation;
- durable handoff/outbox recovery;
- Agent Bus as transport, never Workflow authority;
- Git, PR, CI, and report hashes as external evidence.

The accidental complexity is also real:

- the product still describes itself as a stateless method and validation CLI while shipping a
  production operations Runtime;
- one `awf` command exposes both contract-development tools and a large operator toolbox;
- `init` wraps profile generation and `setup`, then the facade wraps node/manifest/status again;
- run identity, node identity, progress, and completion are repeated across too many JSON files;
- compatibility for v1/v2/v3 routes, old TaskCards, shell shims, direct script entry, source checkout,
  `sys.executable`, aliases, and old flag paths is protected despite no external compatibility need;
- status must reconstruct causality from ledger, packet, checkpoints, files, queues, GitHub, lifecycle,
  and Feedback because the Runtime has no single coherent state model.

This project is over-engineered **in implementation shape**, not in its safety goals. The right move
is not to weaken safety or add another facade. It is to make one Runtime own the loop and one durable
store own each class of state.

## 2. Current Architecture Map

### Documented architecture

The constitution says Agent Workflow owns method semantics and Artifact contracts, does not execute
or transport, and leaves a future Runtime external
([constitution](../../constitution.md#11-external-boundaries)). `docs/architecture.md` likewise
describes a thin validation CLI that never executes, schedules, or orchestrates
([architecture](../architecture.md)).

### Actual architecture

The installed product is already a Runtime:

```text
User
  |
  v
awf CLI
  |-- validation/inspection core
  |-- setup/init/enroll/plan/run/dispatch/preflight/feedback
  |-- beginner facade: doctor/start/status/drain/stop
  `-- node lifecycle: install/reconcile/start/logs/restart/upgrade/uninstall
          |
          +--> RunManifest + compiled RunContract
          +--> generated NodeProfiles + installed snapshots/registries
          +--> native manager definition + desired state + process record
          +--> listener lease
          |
          v
     awf_listen
          |
          +--> Agent Bus listen --on-argv
          |
          v
     awf_role trusted handler
          |
          +--> RunLedger/context packet authorization
          +--> RunEvidence + delivery checkpoint/outbox/inbox
          +--> isolated model workspace
          +--> provider argv Adapter -> Codex/OpenCode/Pi
          +--> trusted Git/commit/push/PR/postflight
          `--> next delivery or terminal decision

External truth:
  Agent Bus delivery/ACK state | Git object database | GitHub PR/CI | native service manager
```

The mismatch is observable in the package itself: the CLI exposes the full operations menu
([parser](../../src/agent_workflow/cli.py#L903)), while the wheel force-includes the operations
scripts. `src` dynamically locates those scripts and mutates `sys.path` before bare imports
([CLI bridge](../../src/agent_workflow/cli.py#L203),
[node bridge](../../src/agent_workflow/node.py#L432)). The separation between “core” and “external
Runtime” is therefore prose, not an enforceable module or product boundary.

### Ownership and dependency findings

| Area | Current owners/truths | Finding |
|---|---|---|
| Project/run intent | TaskCard, RunManifest, compiled RunContract, branch-derived run ID | Intent is validated well, but represented three times. |
| Workflow stage | RunLedger, context packet, delivery type, checkpoint phase | Ledger should be sole semantic authority; the rest should be evidence or projection. |
| Model invocation | ledger authorization, handler result, recovery checkpoint, process evidence | The invariant is essential; its representation is scattered. |
| Node identity | authoring profile, installed snapshot, source/name registry, install record, desired state, process record, lease | Exact ownership is correct; six persistent representations are not. |
| Completion | ReviewReport, checkpoint, terminal ledger, Git/PR/CI, Agent Bus ACK | These facts have distinct meanings, but current status must infer their relationship. |
| Product boundary | stateless core, packaged operations, facade, scripts | The declared boundary contradicts the shipped product. |

There is no harmful circular semantic dependency between Workflow and Agent Bus: Bus still owns
transport and success-gated ACK, Workflow owns stage and completion. The circularity is instead an
implementation one: `src` loads packaged `scripts`, scripts import `agent_workflow`, and the facade
re-enters CLI setup paths. That makes the architecture hard to explain, package, and rewrite.

## 3. Historical Baggage Inventory

These verdicts assume the stated 0.x condition: no external users, public API, plugin ecosystem, old
CLI, schema, or deprecation window must be preserved. **DELETE means delete from Runtime v2 after a
migration/closeout gate, not mutate live Python state immediately.** Before removing any current
production path, retained deliveries must be drained or explicitly abandoned by their owner,
state migration versus discard must be recorded, and the Python oracle fixtures must be frozen.

| Existing item | Verdict | Current problem and target treatment |
|---|---|---|
| `init` and `enroll` as aliases | **DELETE `enroll`** | Both register the same handler ([CLI](../../src/agent_workflow/cli.py#L948)). One word is enough. |
| `setup` as a public beginner action | **MOVE TO DEBUG/DELETE** | It exposes state root, profiles, manifests, repositories, routes, and models. `run` should compile its own internal spec. |
| `plan check` | **MERGE/AUTO** | Contract compilation is valuable; requiring a separate command is not. Retain a debug inspection surface. |
| `run check` before `run` | **AUTO** | A safety prerequisite belongs inside `run`. |
| Current bare `run` semantics | **REDESIGN** | It initializes a ledger and prints `next=clean_checkout`; it does not run the loop ([implementation](../../src/agent_workflow/cli.py#L678)). The primary command must do what its name promises. |
| `dispatch` flags as normal API | **INTERNAL/ADMIN** | Dispatch should consume the current run, not reconstruct authority from user flags. |
| `preflight fast/deep/resume-deep` | **AUTO + DEBUG** | The distinctions are operational implementation details. Today the packaged wrapper exposes only recovery while README still uses the script for fast/deep, a concrete abstraction leak. |
| `node` eleven-command menu | **MOVE TO DEBUG/ADMIN** | Useful for incident response; not a beginner product surface ([CLI](../../src/agent_workflow/cli.py#L1107)). |
| `drain` as user concept | **MERGE INTO `stop`** | Safe zero-pending observation is correct; users should not learn a lifecycle protocol word. `stop` may ask or refuse when active work exists. |
| `resume` | **AUTO/DEBUG** | Recovery should normally occur during `run`; ambiguous cases should become a causal status action. |
| `feedback` pipeline in main menu | **MOVE TO DEBUG or separate product** | Dogfood Finding is independent of business completion and should not expand the normal product vocabulary. |
| `validate` / `inspect` | **KEEP AS DEV TOOLS** | Valuable for contract authors, not normal Runtime commands. |
| v1/v2/v3 delivery routes | **DELETE** | Compiler and handlers explicitly preserve them ([compiler](../../src/agent_workflow/manifest.py#L345)); Rust v2 needs one protocol. |
| legacy TaskCard role fallback | **DELETE** | The same-tool fallback protects historical cards, not product semantics. |
| command-string handler builder | **DELETE** | Production uses `--on-argv`; the old string builder remains in the production module and tests. |
| `scripts/awf-dispatch.sh` | **DELETE** | It is a POSIX compatibility shim around the Python entry. |
| direct script entry | **DELETE** | There is no reason for installed Runtime contracts to depend on script paths. |
| source/editable checkout fallback | **DELETE FROM PRODUCTION** | Keep developer tooling separate; the released Runtime must have one resource model. |
| `python -m` and `sys.executable` re-entry | **DELETE FROM RUST/NATIVE PRODUCT INVARIANTS** | All 15 binary candidate/target cells failed the interpreter re-entry gate; preserve it only for the Python oracle/fallback until the switch gate ([readiness](../tasks/binary-release-readiness-report.md#existing-candidate-decision)). |
| `dispatch.env` parser legacy `export` syntax | **DELETE** | Safe parsing is good; migration syntax has no user to migrate. |
| authoring profile -> installed snapshot -> alias registries | **REDESIGN** | It repaired real service identity drift, but should become one internal AgentInstallation record. |
| RunManifest + compiled RunContract | **MERGE** | Keep immutable compiled intent, remove duplicate user-visible files. |
| ledger + sidecar context packet + summary | **MERGE** | Keep one authoritative RunStore; generate recovery/status views. |
| separate checkpoint/outbox/inbox JSON files | **REDESIGN** | Keep phases and transactional ordering in one per-delivery journal/table. |
| facade over existing layers | **DELETE AFTER REWRITE** | It is a useful transitional repair, not a final architecture boundary. |

For each deletion, validation is not “old tests stay green.” Validation is that the replacement keeps
the relevant semantic fixture or invariant while the compatibility-only assertion is removed.

## 4. Loop Reliability Review

### The semantic loop to preserve

```text
Task accepted
  -> implement invocation authorized exactly once
  -> implementation artifact and trusted Git commit
  -> review invocation authorized exactly once
  -> PASS | REQUEST_CHANGES | BLOCKED
      PASS -> terminal provenance verification -> completion
      REQUEST_CHANGES -> bounded rework on exact lineage -> review
      BLOCKED -> terminal/escalation
  -> next Task only after current terminal state
```

The existing `RunLedger.pre_invocation_gate` already checks terminal state, route ownership, duplicate
delivery, stage, attempts, and rework budget before invocation
([control plane](../../scripts/awf_control_plane.py#L469)). A completed or ambiguous invocation is not
blindly repeated. Checkpoint phases are monotonic, and a handler that has crossed `model_started`
must recover or fail closed rather than launch a second model. These are the central Runtime
semantics, not Python details.

### ACK boundary

The invariant is:

```text
receive delivery
  -> validate identity and authority
  -> make the local effect durable
  -> make any required downstream handoff durable/sent
  -> mark local inbox complete
  -> handler returns success
  -> Agent Bus ACKs
```

`delivered` is not completion, Agent Bus ACK is not a Reviewer verdict, and Workflow terminal state
is not transport state. This separation must survive unchanged.

### Current fragility

1. **Coordinator ownership is implicit.** Run semantics live in a ledger reachable from role
   handlers, but the product does not name one coordinator that owns the transition graph. Cross-
   machine delivery and per-host files make ownership appear distributed even though Workflow
   authority should be singular.
2. **Crash interpretation spans records.** The Runtime correlates RunLedger, handler result/log,
   recovery checkpoint, outbox, inbox, workspace manifest, and Bus state. Much of this is necessary
   evidence, but too much is independently serialized truth.
3. **Rework lineage is correct but expensive to reconstruct.** It resolves a prior implement
   delivery and cross-checks checkpoint digest, workspace, PR tuple, commit, and Git manifest. The
   target store should record this lineage directly as an immutable relation.
4. **Node running truth is a join.** Exact install record, definition, desired state, process record,
   launch identity, live PID, and lease must agree. Exact stop is right; representing one Agent
   incarnation across several user-visible records is not.
5. **Status is at risk of becoming a second control plane.** It currently reads lifecycle, ledger,
   delivery files, queue counts, Feedback, Git, PR, and CI
   ([aggregation](../../src/agent_workflow/status.py#L603)). It must remain a pure projection.
6. **TaskCard serial continuation is not a first-class state transition.** The current accepted
   three-card run was operationally serial, but the product still depends on an external Architect
   to create and authorize the next card. Runtime v2 should explicitly distinguish “current task
   terminal” from “project has another authorized task.” It must never invent the next task.

### Target reliability model

Use a single coordinator-owned Run state machine and a worker-owned Invocation journal:

```text
Coordinator RunStore                    Worker InvocationStore
--------------------                    ----------------------
current task/stage                      invocation_id
rework budget                           spec hash
authorized invocation  ---- command --> prepared
expected result                         started
outgoing delivery intent <--- result -- completed | failed | ambiguous
terminal decision                       artifact/evidence hashes
```

- The coordinator is the only owner of Workflow transitions.
- A worker is the only owner of local model process and workspace effects.
- Agent Bus transports idempotent commands/results and success-gated ACKs; it owns no stage.
- An `invocation_id` is stable across redelivery. `prepared` may launch once; `started` without a
  recoverable result becomes `ambiguous` and blocks automatic replay.
- Transactional outbox rows live in the same database transaction as the state change that created
  them. Separate JSON outbox truth disappears.
- Git/GitHub are re-read at trust boundaries; their facts are recorded as evidence, not copied into
  a second mutable authority.

This removes recovery cases created by file ordering while preserving recovery cases inherent to an
at-least-once transport and an external, non-transactional model process.

## 5. User Cognitive Load Audit

### Current measured path

The synthetic beginner benchmark required seven operator commands:

1. `awf init`
2. `awf doctor --explain`
3. `awf start`
4. `awf run check`
5. `awf run`
6. `awf status --explain`
7. `awf stop`

It required five explicit decision groups and created two profiles, one owner RunManifest, and one
compiled contract ([benchmark](../tasks/fresh-machine-usability-benchmark-report.md#local-beginner-journey)).
The measured 0.0379 seconds covers command execution through test seams, not human choices, runtime
authentication, native service-manager behavior, or a useful business run.

### Current configuration explosion

At minimum, a real remote-capable project/host currently involves:

| Class | Current objects/files | Human-facing burden |
|---|---|---|
| Project intent | TaskCard, `.awf/run-manifest.json`, `.awf/run-contract.json` | User supplies the card and must understand compilation/drift errors. |
| Agent binding | two JSON NodeProfiles | Coder/reviewer runtime/model, machine/project, lifecycle, repo/remotes, state root. |
| Secrets/runtime paths | owner-only `dispatch.env` | Bus URL, three role tokens, optional executable paths; init explicitly leaves it separate ([setup](../../src/agent_workflow/cli.py#L468)). |
| Managed install | content-addressed snapshots, source/name registries, install record, native definition | Created automatically, but visible during failure recovery. |
| Runtime | desired state, process record, listener lease, RunLedger, context packet, summary | Multiple identifiers and paths appear in diagnostics. |
| Delivery | RunEvidence log/result, checkpoint, outbox, inbox, workspace | Internal but often required to diagnose a stop. |
| Readiness | Fast report plus Deep proof/cache | User must currently understand why one is not the other. |
| External prerequisites | Python/wheel, Agent Bus, provider CLI/auth, Git remotes/auth, GitHub auth | Not provisioned by `init`. |

`awf init` exposes 17 options and requires the TaskCard plus upstream/head repository identities
([parser](../../src/agent_workflow/cli.py#L948)). The top-level CLI exposes roughly eighteen named
commands/groups, and `node` exposes eleven more. This is an operator toolkit, not a simple product.

### Concept classification

| Concept | Classification | Target disposition |
|---|---|---|
| Project | **USER CONCEPT** | Repository detected from Git; one project context. |
| Agent | **USER CONCEPT** | A named coding agent and where it runs. |
| Task | **USER CONCEPT** | Prompt/issue/TaskCard accepted as one task. |
| Status | **USER CONCEPT** | “What is happening, why stopped, what next?” |
| Role | **ADVANCED CONCEPT** | Internally Coder/Reviewer/Architect; beginner sees recommended agents. |
| TaskCard | **ADVANCED CONCEPT** | First-class structured task for power users; generated from simple input when possible. |
| Artifact / ImplementationReport / ReviewReport | **ADVANCED CONCEPT** | Visible as evidence links, not setup prerequisites. |
| Agent Bus | **ADVANCED CONCEPT** | Exposed only when configuring remote agents or diagnosing transport. |
| Rework budget | **ADVANCED CONCEPT** | Safe default of one; configurable in project policy. |
| Profile | **INTERNAL IMPLEMENTATION DETAIL** | Replace with generated AgentBinding. |
| state root | **INTERNAL IMPLEMENTATION DETAIL** | Platform default; only `debug paths` shows it. |
| RunManifest / RunContract | **DELETE/MERGE** | One internal immutable `RunSpec`. |
| authority manifest | **DELETE/MERGE** | Capabilities compiled into RunSpec/policy. |
| listener / lease / process record | **INTERNAL IMPLEMENTATION DETAIL** | Agent process supervisor state. |
| checkpoint / ledger / outbox / inbox | **INTERNAL IMPLEMENTATION DETAIL** | RunStore and InvocationStore records. |
| managed/session | **INTERNAL; ADVANCED OVERRIDE** | Default managed where supported, foreground only when explicitly requested. |
| Fast/Deep Preflight | **INTERNAL IMPLEMENTATION DETAIL** | Automatic readiness pipeline with one causal result. |
| handler argv | **INTERNAL IMPLEMENTATION DETAIL** | Hard safety invariant, never a user concept. |
| upstream/head repository | **DERIVED; ASK ONLY IF AMBIGUOUS** | Infer from remotes and authenticated identity. |
| machine identity | **DERIVED** | Stable installation identity; friendly name optional. |
| run ID | **INTERNAL** | Displayable reference, never typed on the normal path. |
| Feedback / Feedback Outbox | **DELETE FROM NORMAL PRODUCT** | Optional dogfood diagnostics surface. |

## 6. CLI / UX Redesign

### Target normal surface

```text
awf run [task]
awf status
awf stop
```

Optional explicit onboarding remains:

```text
awf init
```

Everything else is either automatic or namespaced:

```text
awf agent ...      # add/list/remove/pair agents
awf debug ...      # read-only diagnostics, paths, state, contract, logs
awf admin ...      # explicit repair/install/restart/recovery operations
```

### Current command disposition

| Current command | Verdict | Target |
|---|---|---|
| `awf init` | **KEEP, REDESIGN** | Interactive/generated project setup; automatically entered by `run`. |
| `awf enroll` | **DELETE** | No alias. |
| `awf setup` | **DELETE FROM NORMAL PATH** | Internal RunSpec compiler or `debug contract`. |
| `awf doctor` | **AUTO** | `run` performs it; `debug doctor` remains read-only. |
| `awf start` | **AUTO** | `run` ensures required agents; `admin agent start` escape hatch. |
| `awf run check` | **AUTO** | Always before state mutation. |
| `awf run` | **KEEP, RADICALLY REDESIGN** | Ensure/configure, validate, start, preflight, dispatch, supervise, and continue the bounded loop. |
| `awf status` | **KEEP** | One causal view and one legal next action. |
| `awf resume` | **AUTO/MOVE TO ADMIN** | Resume safe durable work automatically; ambiguous work blocks with an explicit action. |
| `awf dispatch` | **INTERNAL/MOVE TO ADMIN** | Never rebuild normal authority from flags. |
| `awf drain` | **MERGE INTO `stop`** | `stop` safely waits/refuses/prompts; `admin stop --force` remains exact and explicit. |
| `awf stop` | **KEEP** | Stop this project's agents without touching deliveries. |
| `awf preflight ...` | **AUTO/MOVE TO DEBUG** | One internal readiness pipeline. |
| `awf feedback ...` | **MOVE TO DEBUG/SEPARATE** | Not a normal Workflow action. |
| `awf node ...` | **MOVE TO ADMIN/DEBUG** | Preserve exact operator controls without advertising them to beginners. |
| `awf validate/inspect` | **MOVE TO DEV** | Contract author tooling. |

`awf run` must execute prerequisites in dependency order and stop at the first fail-closed boundary:

```text
discover project/config
  -> validate/compile RunSpec
  -> discover agents and credentials
  -> ensure exact agent processes
  -> run automatic readiness checks
  -> open/recover RunStore
  -> dispatch only the authorized transition
  -> supervise until terminal, user stop, or an ambiguous boundary
```

Automatic does not mean permissive. Unknown install identity, a non-empty unexpected queue, a dirty
owned workspace, stale proof, conflicting remote, or an ambiguous invocation must still stop. The
difference is that the user sees the cause and next action, not the internal command graph.

## 7. Interactive UX Decision

### Recommendation: hybrid, interactive-first only when information is missing

| Option | Verdict | Why |
|---|---|---|
| Flag-heavy | Reject as default | Reproducible but exposes implementation structure and produces the current setup burden. |
| Interactive-first | Incomplete alone | Best onboarding, but unsuitable for CI, repeatability, and declarative review. |
| Config-first | Reject as default | Makes a beginner learn schema before receiving value. |
| Hybrid | **Choose** | Auto-detect and convention first; ask only unresolved choices; persist a tiny config; support flags/JSON for automation. |

Precedence should be explicit flags (automation) -> project config -> detected facts -> recommended
defaults. Interactive questions are allowed only for facts that cannot be derived or whose ambiguity
changes authority.

Example:

```text
$ awf run "Implement the next approved task"

No Agent Workflow project found.

Detected project: github.com/user/project
Detected agents: Codex, OpenCode, Pi
Detected Git relationship:
  upstream  user/project
  write     user/project-fork

Recommended:
  Coder     OpenCode
  Reviewer  Pi
  Rework    1
  Runtime   managed

Use this setup? [Y/n]

✓ Project configured
✓ Agents ready
✓ Safety checks passed
→ Task started: TASK-017

Run `awf status` from any terminal.
```

If no TaskCard exists, `awf run "..."` may create an internal structured TaskSpec only when the
input is sufficiently bounded. Ambiguous product intent must stop for planning; interactive
onboarding is not permission to invent task scope.

## 8. Target Architecture

### Product boundary

Agent Workflow v1 should honestly be one product with two layers:

1. **Method Contract**: vendor-neutral Workflow semantics, task/report schemas, role authority, and
   safety invariants.
2. **AWF Runtime**: a native implementation that executes that contract using external provider
   CLIs, Git/GitHub, native process supervisors, and Agent Bus.

The Runtime is not an “external optional integration” once reliable cross-machine execution is the
product goal. Agent Bus remains external and transport-only. Provider CLIs remain external model
runners. AI Memory remains outside execution authority.

### Runtime components

```text
CLI / TUI boundary
  |
  v
Project Resolver --------> small ProjectConfig
  |
  v
Run Compiler ------------> immutable RunSpec
  |
  v
Coordinator
  |-- Workflow State Machine
  |-- RunStore + transactional outbox
  |-- Causal Status projector
  |-- Git/PR provenance verifier
  `-- Transport client ---------------------- Agent Bus
                                                |
                                                v
Agent Runtime (per machine)
  |-- AgentBinding resolver
  |-- native Supervisor adapter
  |-- InvocationStore + inbox/outbox
  |-- isolated Workspace manager
  |-- trusted Artifact/Git postflight
  `-- pure ProviderAdapter -> external model CLI
```

The coordinator and an agent Runtime may live in the same `awf` process on one machine. Multi-machine
operation starts the same agent Runtime under the native user supervisor. Do not introduce a general
scheduler, plugin framework, arbitrary DAG, or Agent Host.

### Major abstraction disposition

This matrix compresses the ten review questions for every named abstraction: the real problem,
whether it is independent, overlap/duplicate truth, user visibility, delete/merge/derive/internal
treatment, and whether it survives in Rust v2.

| Abstraction | Real problem | Independent vs overlap / duplicate truth | User visibility | Target and Rust v2 |
|---|---|---|---|---|
| Workflow | Defines legal stages and authority | Independent product semantics | Advanced, not setup vocabulary | **KEEP** as typed state machine. |
| Runtime | Durably executes Workflow | Independent and currently unnamed; behavior is scattered across CLI/scripts | Product behavior, not a concept lesson | **PROMOTE** to first-class Rust product layer. |
| Node | Represents an execution host/agent process | Overlaps listener/service/profile/process/lease | User sees Agent/machine only | **MERGE** into AgentRuntime/AgentInstallation. |
| Agent Bus | Durable at-least-once transport | Independent external truth; must not duplicate Workflow stage | Advanced remote-transport setting | **KEEP EXTERNAL**, transport-only. |
| Adapter | Converts invocation to provider argv/stdin/files | Independent narrow boundary; no state authority | Internal | **KEEP** as pure Rust renderer/trait with a small closed set. |
| Role | Separates Coder/Reviewer/Decider authority | Independent semantic capability, but current product/Bus names differ | Advanced; beginner sees assigned Agent | **KEEP INTERNALLY** as typed authority. |
| Profile | Binds role, repo, tool, machine, state, lifecycle | Duplicates ProjectConfig, installed snapshot, and RunSpec bindings | Delete from beginner UX | **REDESIGN** as generated AgentBinding inside AgentInstallation. |
| Run | One bounded execution of a Task | Independent domain identity | Status may display it; user need not type ID | **KEEP**. |
| RunManifest | Owner intent | Overlaps TaskCard, profiles, and compiled contract | Internal | **MERGE** into RunSpec compilation input; delete current schema. |
| RunContract | Validated/compiled intent | Independent semantic idea, duplicate file beside manifest | Internal/debug view | **KEEP IDEA**, one immutable Rust `RunSpec`. |
| TaskCard | Self-contained task contract | Independent repository Artifact; some fields currently repeat manifest selections | User Task; structured form advanced | **KEEP**, remove duplicated runtime/config fields. |
| Artifact | Auditable handoff evidence | Independent evidence class, not transition authority | Evidence links only | **KEEP**, with language-neutral contracts. |
| Ledger | Workflow transition authority | Independent and should be sole semantic authority; packet/summary duplicate it | Internal; projected by status | **KEEP SEMANTICS** as coordinator RunStore. |
| Checkpoint | Prevents repeated/ambiguous effects | Independent per-invocation semantics; overlaps handler result and inbox | Internal | **MERGE** into InvocationStore state. |
| Workspace | Isolates model writes and trusted Git | Independent resource with lineage bound to invocation | Internal/debug | **KEEP**, Runtime-owned. |
| Listener | Receives transport deliveries | Not an independent product concept; part of AgentRuntime | Internal | **MERGE** into AgentRuntime. |
| Service | Keeps AgentRuntime alive | Platform adapter, overlaps node lifecycle | Internal/admin | **MERGE** into Supervisor adapter. |
| Preflight | Proves readiness before dispatch | Independent safety gate; report/cache are derived | Internal; user sees readiness result | **KEEP INTERNALLY**, automatic. |
| Feedback | Captures dogfood findings | Independent optional pipeline, not loop state | Debug/dogfood only | **SEPARATE/OPTIONAL**; may live outside Rust core. |
| Outbox | Makes downstream send recoverable | Independent transactional pattern; current file duplicates checkpoint facts | Internal | **KEEP PATTERN**, row in same transaction/store. |
| Process record | Records a launched incarnation | Overlaps lease/install/desired state | Internal | **MERGE** into AgentInstallation or Invocation record. |
| Lease | Proves live exact ownership | Ephemeral observation paired with process incarnation | Internal | **KEEP EPHEMERALLY** as incarnation token, not a product object/file. |

### Major change evaluation

| Change | Current/accidental problem | New design | Loop reliability | Cognitive load | Verification and migration risk |
|---|---|---|---|---|---|
| **DELETE compatibility surface** | Old routes, fallbacks, aliases, shims, and Python entry contracts protect no external user and multiply branches. | One v2 protocol, one installed entry, one resource model. | Fewer alternate recovery/dispatch paths; risk is losing an invariant hidden in a legacy test. | Removes flags, formats, and migration errors. | Classify tests first; port semantic cases; close or explicitly abandon retained live deliveries; decide migrate vs discard; then delete compatibility cases. |
| **MERGE manifests/profiles** | The same run, role, repository, model, and state bindings appear in TaskCard, RunManifest, RunContract, and profiles. | ProjectConfig + immutable compiled RunSpec + generated AgentBinding. | One hash-bound invocation specification reduces drift. | Users choose agents/task, not files/paths. | Differential fixture comparison; risk is accidentally treating derived discovery as authority. |
| **REDESIGN durable state** | Ledger/packet/summary/checkpoint/outbox/inbox/result files encode overlapping progress and ordering. | Coordinator RunStore and worker InvocationStore with transactional outboxes. | Removes file-order crash windows while retaining ambiguous external-effect stops. | Status no longer asks users to reconcile files. | Fault injection at every transaction/external-effect boundary; highest rewrite risk. |
| **REDESIGN lifecycle** | Profile snapshot, registries, definition, desired state, process record, and lease jointly represent one agent incarnation. | AgentInstallation record plus live incarnation and narrow supervisor adapter. | Exact stop remains; fewer inconsistent combinations exist. | Listener/lease/managed/session disappear from normal UX. | Native three-OS lifecycle matrix; risk is weakening exact identity during simplification. |
| **REWRITE Runtime in Rust** | Python packaging and module/script re-entry are coupled to lifecycle, while architecture remains wrapper-heavy. | Native Runtime v2 implementing only the frozen semantic contract. | Typed states help make illegal transitions unrepresentable; language alone does not provide safety. | Enables `run/status/stop` and one install artifact. | Python oracle + conformance + real dogfood; risk is a mechanical port or dual-runtime drift. |

## 9. Minimal State and Config Architecture

### Minimal authoritative state

There should be only four AWF-owned authoritative classes:

| Authority | Owner | Contents |
|---|---|---|
| `ProjectConfig` | project owner | Only choices that cannot be derived: agent assignments/locations, optional policy overrides. |
| `RunSpec` | coordinator | Immutable task identity, stage graph, role assignments, Artifact paths/contracts, rework bound, repository/provenance policy. |
| `RunStore` | coordinator | Current stage, authorized invocation, transitions, terminal decision, transactional outgoing intents. |
| `InvocationStore` | executing agent | Invocation identity/spec hash, prepared/started/completed/failed/ambiguous phase, workspace/evidence hashes, transactional result intent. |

`AgentInstallation` is host configuration/state, not Workflow state. It owns the selected executable,
project binding, native manager identity, current incarnation, and desired running/stopped state in
one record/API.

### Durable evidence

- Task, ImplementationReport, ReviewReport, decision, and their canonical hashes;
- model invocation start/exit/result evidence;
- Git base/head/tree/commit facts;
- push remote SHA, PR tuple, CI conclusion, merge commit;
- Agent Bus delivery IDs and observed ACK-related outcome;
- native manager/install/incarnation facts required for exact stop.

Evidence is append-only or content-addressed. Evidence may prove a transition, but it does not gain
authority to select the next transition.

### Derived views

- causal status and “one legal next action”;
- context packet for a fresh agent session;
- run summary;
- readiness report;
- human logs and timelines;
- profile-like diagnostic output.

Deleting a derived view must never lose the ability to recover authoritative state.

### Caches

- runtime/tool discovery;
- provider version hashes;
- Deep transport proof with fingerprint and TTL;
- read-only GitHub observations.

A stale or missing cache can deny an action but can never authorize one.

### External truth

| System | Owned truth | AWF treatment |
|---|---|---|
| Git | object/tree/commit/ref state | Re-read exact object IDs at trust boundaries. |
| GitHub | PR tuple, CI, merge | Record observations with timestamps; do not pretend cached facts are live. |
| Agent Bus | delivery, pending/failed/ACK transport state | Map by idempotency key; never infer Workflow completion from ACK alone. |
| Native manager/OS | installed definition, process identity, liveness | Query live; bind to one AgentInstallation/incarnation. |
| Provider CLI | authentication, model catalog, process result | Probe version/readiness; treat model call as non-transactional external effect. |

### Minimal config

Prefer one optional `.awf/config.toml`:

```toml
[agents]
coder = "opencode"
reviewer = "pi"

[policy]
rework = 1
```

The file should be absent when defaults and discovery are unambiguous. Repository identity, base
branch, fork/upstream relationship, installed executables, machine identity, state location, routes,
report paths, run ID, lifecycle manager, and credentials are derived or stored in platform-specific
secure configuration. Secrets must not enter project config.

## 10. Language and Runtime Recommendation

### Comparison

| Dimension | Python | Python + native launcher | Go | Rust | Permanent hybrid |
|---|---|---|---|---|---|
| Loop/state correctness | Proven today; dynamic structure makes illegal states easier to represent | Same Python semantics | Good with explicit types | **Best fit for exhaustive typed states** | Two implementations increase drift |
| Crash-safe state | Proven via careful files/fsync/locks | Same | Good | **Good; strong typed storage boundary** | Duplicate recovery logic |
| Process/subprocess control | Works, but platform exceptions and interpreter identity leak | Packaging improves, process model unchanged | Strong and simple | **Strong; precise OS integration** | Boundary duplication |
| Concurrency | Adequate; GIL irrelevant for current process-heavy model | Same | Excellent/simple goroutines | Excellent; use restrained synchronous design first | Highest complexity |
| Cross-platform lifecycle | Proven but tightly coupled to Python re-entry | Preserves current shape | Good native binary | **Good native binary; platform adapters explicit** | Two lifecycle stacks |
| Structured argv/UTF-8 | Proven | Proven | Natural | Natural | Must prove twice |
| Filesystem/Git integration | Mature; current code proven | Same | Mature | Mature; continue structured Git CLI for trust equivalence | Drift risk |
| Agent Bus integration | Proven CLI boundary | Same | Straightforward | Straightforward | Protocol duplicated |
| Packaging/fresh machine | Weak; Python environment required | Better bridge, but large runtime bundle | Excellent | **Excellent target** | Worst distribution story |
| Startup/binary size/memory | Acceptable but environment-heavy | Bundle-heavy | Usually smallest operational burden | Small/fast enough; often larger builds than Go | Worst total footprint |
| Signing/notarization | Python tree complicates identity | Launcher plus tree complicates signing | Simple artifact | **Simple artifact** | Multiple artifacts |
| Supply chain | Python + freezer/runtime tree | More components | Small dependency graph possible | Cargo graph must be tightly controlled | Largest attack/update surface |
| Development velocity | **Best now** | Best bridge | High | Lower initially; compile/ownership learning cost | Lowest overall |
| Maintainability | Current 17k production lines and dispersed state are warning signs | Does not simplify Runtime | Good | **Best if design deletes state/compatibility layers** | Long-term double maintenance |
| Testability | Existing suite is strong | Same | Strong | **Strong with typed state + crash injection** | Conformance burden never ends |
| Future extensibility | Easy but invites more wrappers | Same | Good | Good; explicit traits/enums resist accidental extension | Drift and feature asymmetry |

### Recommendation

- **Option A — Continue Python:** reject as the long-term Runtime. Keep it through the transition.
- **Option B — Python + native launcher:** retain only as a contingency/bridge. It is the shortest way
  to package current behavior, but it preserves the architecture that needs redesign.
- **Option C — Go:** viable and arguably the simplest distribution choice. Choose Go instead only if
  measured Rust delivery velocity or maintenance capacity fails the Phase 1 gate.
- **Option D — Rust:** preferred working target, conditional on the vertical-slice gate. The reason
  is not generic performance. It is the
  fit between exhaustive state enums, strict ownership boundaries, crash-safe persistence, exact
  process identity, structured subprocesses, single-binary distribution, and a long-lived
  correctness-sensitive Runtime.
- **Option E — Hybrid:** use temporarily, not as the final architecture. Python is the oracle and
  fallback; Rust is the new Runtime; Agent Bus remains independently distributed.

Do not introduce async Rust, an ORM, a plugin framework, or embedded Git in Phase 1 unless a proven
need requires them. A synchronous coordinator, SQLite transactions, structured external Git/Agent
Bus/provider commands, and narrow platform adapters are enough.

## 11. Rust Rewrite Timing Decision

### Result: CONDITIONAL YES

The named decision is **`REWRITE AFTER CURRENT REMEDIATION + VALIDATION`**.

The language recommendation itself also has a go/no-go gate: after the semantic contract and target
ADR, a time-boxed Rust vertical slice must demonstrate fewer authoritative state objects, a smaller
normal CLI, and maintainable native lifecycle code. If it cannot, choose Go or the Python/native
launcher bridge rather than continuing Rust for sunk-cost reasons.

### 1. Why not rewrite before the current remediation?

The remediation discovered semantic contracts, not cosmetic bugs: canonical state identity,
truthful lifecycle facts, durable installed identity, exact stop, compile-before-run, rework
workspace lineage, causal status, structured handler argv, and fresh-host behavior. Rewriting before
those discoveries would encode unknown behavior or reproduce the same ambiguity in Rust.

### 2. Why is the post-remediation node appropriate?

- The Python implementation now serves as an executable specification of the hard cases.
- The no-model gate proves current installation/configuration/transport behavior on three OSes.
- Real dogfood proves the main business value and ACK/provenance chain.
- Binary feasibility proves that preserving Python interpreter re-entry makes distribution worse,
  not safer.
- There are no external compatibility obligations, so this is the cheapest future point to delete
  interfaces before they acquire users.

### 3. What must freeze before Rust implementation?

Freeze a language-neutral `awf.semantic-contract.v1` containing:

1. Workflow states and legal transitions for implement, review, bounded rework, blocked, rejected,
   completed, and next-task eligibility.
2. Exactly one authorization identity for every model invocation.
3. `prepared` may start; `started` without recoverable completion must never auto-replay.
4. Durable local handler effect and required handoff before handler success/ACK.
5. Agent Bus transport-only ownership.
6. Task/Artifact/report canonicalization and hash rules that are genuinely product-level.
7. Trusted Git/commit/push/PR/CI provenance gates.
8. Exact workspace and process ownership; no PID-only or name-only mutation.
9. Fail-closed unknown/stale/drift behavior.
10. Causal status as a read-only projection with one legal next action.

### 4. What must not freeze?

Do not freeze CLI hierarchy/flags, file/directory layout, v1-v3 route names, existing JSON schemas,
RunManifest shape, profile shape, authority-manifest representation, state-root exposure, Python
module/script entry, `sys.executable`, source checkout fallback, aliases, compatibility shims,
`argparse` messages, or exact Python class/function boundaries.

### 5. Python's role

Before the gate, Python remains the production implementation. After the gate:

```text
Python: production fallback + behavioral oracle + bugfix/reference only
Rust:   new Runtime development and all new Runtime architecture
```

After Rust acceptance, delete the Python production Runtime and retain only language-neutral
fixtures, selected oracle tools, and historical evidence. Do not maintain two production Runtimes.

### 6. Should Python receive new large features?

No. After the post-remediation real business gate, only correctness fixes needed to preserve the
frozen oracle or unblock conformance should land. New product surface belongs in Rust v2.

### 7. May Rust redesign CLI/state/config?

Yes; it must. The rewrite has little value if it preserves the current external or storage shape.
Behavioral parity is required for semantics and safety, not interface parity.

### 8. Current missing gate

Run one fresh TaskCard from `main@0ed7812` or later through actual model execution, trusted commit,
review, terminal verification, handler-success ACK, and empty scoped queues. Add a real or fixture-
driven rework path. This is the only material timing blocker identified by this review.

### 9. Formal Rust switch gate

Rust becomes default only when all are true:

1. Language-neutral semantic and safety fixtures pass.
2. Crash injection passes at every invocation and outbox boundary.
3. Duplicate/redelivery tests prove no duplicate completed or ambiguous model call.
4. Local fresh-machine `awf run` succeeds without manual internal commands.
5. Mac, Windows, and Linux/VPS lifecycle/readiness pass.
6. Cross-machine no-model transport passes with handler-success ACK and empty queues.
7. Real PASS business loop passes.
8. Real or controlled `REQUEST_CHANGES -> rework -> review` passes.
9. Git fork/push/PR/CI provenance matches or exceeds Python evidence.
10. Signed/checksummed release candidate, SBOM, upgrade, program rollback without state rollback, and
    clean uninstall are demonstrated on the supported target matrix.
11. `awf status` explains every injected failure without mutating state.
12. No production fallback silently invokes Python.

### 10. When to abandon the Rust rewrite

Stop or switch to Go/Python if a bounded vertical-slice review finds any of these:

- Rust v2 reproduces the same number of authoritative state objects or compatibility layers.
- The design cannot express ACK, invocation ambiguity, and provenance with fewer ownership
  boundaries than Python.
- Maintainable cross-platform process/service code requires large unsafe or platform-specific
  frameworks that exceed the product value.
- A signed, updatable native distribution is not materially simpler than the Python bundle.
- The available team cannot sustain Rust delivery and incident response after a time-boxed vertical
  slice.
- Product semantics are still changing weekly after the missing dogfood gate, so the oracle is not
  actually stable.

## 12. Rewrite Boundary

### Delete from Runtime v2 after the migration/closeout gate

- `enroll` alias;
- public `setup`, separate `run check`, public fast/deep vocabulary;
- v1/v2/v3 compatibility and legacy TaskCard fallbacks;
- shell dispatch shim and command-string handler builder;
- direct script/source checkout production entry;
- Python interpreter re-entry contract;
- facade as a permanent layer;
- user-authored profiles, authority manifest, and state-root flags;
- independent context-packet/summary files as authorities;
- Feedback commands from the normal Workflow surface.

### Redesign

- CLI and onboarding;
- ProjectConfig/AgentBinding/RunSpec;
- node/listener/service lifecycle as AgentInstallation + incarnation;
- file-spread ledger/checkpoint/outbox/inbox as transactional stores;
- coordinator/worker ownership;
- status as a store projection;
- installation, upgrade, rollback, signing, and distribution.

### Preserve semantics, rewrite implementation

- Workflow stage machine and bounded rework;
- TaskCard and Artifact contracts where product-level;
- provider selection and pure invocation rendering;
- isolated workspace and trusted postflight;
- Git/PR/CI verification;
- process supervision and cross-machine delivery;
- readiness and crash recovery.

### Preserve as hard invariants

- handler success before business ACK;
- no ambiguous duplicate model invocation;
- fail closed on unknown, stale, conflicting, or unverifiable authority;
- exact run/workspace/process ownership;
- Workflow owns semantic transition; Bus owns transport only;
- structured argv/no business shell interpretation;
- durable transition/effect ordering;
- terminal and rework lineage idempotence;
- technical delivery is never product completion.

## 13. Test Strategy for the Rewrite

### Four test classes

| Class | Examples | Action |
|---|---|---|
| Contract tests | Task/Report parsing, RunSpec compilation, canonical hashes, verdicts | Rewrite as language-neutral fixtures; run against Python oracle and Rust. |
| Safety invariant tests | duplicate delivery, stage mismatch, rework bound, terminal idempotence, ACK ordering, ambiguous invocation, exact stop | Preserve behavior; add crash/fault injection. |
| Integration/dogfood | installed artifact, native lifecycle, Fast/Deep transport, Git/PR/CI, real PASS/rework loops | Re-run as Rust acceptance, not unit-test parity. |
| Implementation-coupled tests | argparse shape, Python paths/classes, `sys.executable`, source fallback, v1/v2 routes, wrapper calls | Delete or replace; failure does not imply Rust regression. |

The current suite contains 478 Python test functions and about 14.6k test lines; 232 functions are in
`test_awf_role.py` alone. This is valuable incident knowledge, but also a sign that one large module
and its historical shapes dominate the executable specification.

### Shared conformance harness

```text
semantic cases (JSON/JSONL + filesystem fixtures)
        |                         |
        v                         v
Python oracle adapter       Rust Runtime adapter
        |                         |
        +------ normalized observable result ------+
```

Compare observable decisions and durable facts, not internal filenames. Every case declares which
fields are semantic and which are intentionally implementation-specific.

### Required fault points

Inject termination or I/O failure:

1. before invocation authorization;
2. after authorization, before durable `prepared`;
3. after `prepared`, before spawn;
4. immediately after spawn/`started`;
5. after model exit, before Artifact import;
6. after Artifact import, before trusted Git commit;
7. after commit/push/PR, before result outbox;
8. after result outbox commit, before send;
9. after send, before local completion;
10. after handler completion, before observed ACK;
11. after terminal ledger transition, before status projection.

For each point, assert the only legal outcomes: safe resume, safe replay without repeated external
effect, explicit ambiguity requiring intervention, or terminal failure. Never “probably retry.”

### Existing tests to migrate first

- control-plane authorization, duplicate, transition, and terminal tests;
- recovery model policy and outbox/inbox ordering tests;
- structured argv/no-shell boundary tests;
- manifest drift tests rewritten around RunSpec semantics;
- exact process/profile/lease tests rewritten around AgentInstallation/incarnation;
- trusted Git/fork/PR provenance cases;
- cross-platform installed artifact verification.

### Existing tests to delete early

- v1/v2 routing matrices and legacy selection fallbacks;
- shell shim length/entry assertions;
- Python module and `sys.executable` re-entry;
- exact facade-to-old-function call assertions;
- source/editable resource fallback;
- compatibility-only CLI flags and error strings.

One current gap must be fixed in the conformance contract: the runtime command-boundary document says
all production Python modules are scanned, but the AST test scans only `scripts`, while `cli.py`,
`node.py`, and `node_service.py` invoke subprocesses directly
([test](../../tests/test_runtime_command_boundary.py#L12),
[CLI subprocess](../../src/agent_workflow/cli.py#L743)). Rust v2 should have one explicit process
port plus a narrow, enumerated native-supervisor exception.

## 14. Proposed Refactor and Rewrite Plan

This plan intentionally avoids dozens of compatibility PRs.

### Phase 0 — Close the semantic reference gate

- Run one fresh post-remediation real business TaskCard.
- Exercise rework through a legitimate run or deterministic acceptance fixture.
- Record exact model invocation, handler, ACK, queue, Git, PR, CI, and terminal evidence.
- Do not expand the Python architecture to make the test convenient.

Exit: current Python shape is accepted as a semantic reference, not as the target architecture.

### Phase 1 — Freeze the language-neutral contract

- Write `awf.semantic-contract.v1` and state-transition tables.
- Classify every current test as contract, invariant, integration, or implementation-coupled.
- Create shared fixtures and normalized observable outputs.
- Mark Python Runtime feature-frozen.

Exit: Rust work can reject old interfaces without debate while preserving named behavior.

### Phase 2 — Design Rust Runtime v2

- Define ProjectConfig, RunSpec, RunStore, InvocationStore, AgentInstallation, and evidence schemas.
- Choose a small SQLite schema and transaction boundaries.
- Specify coordinator/agent protocol and stable invocation IDs.
- Specify `run/status/stop`, debug/admin namespaces, installation and upgrade contract.
- Review the design for state count: if it recreates the current file graph, stop.

Exit: accepted target ADR and fault model; no production migration yet.

### Phase 3 — Minimal local vertical slice

- Build `awf run/status/stop` for one local coder and deterministic fake reviewer/terminal path.
- Auto-detect project/runtime, compile RunSpec, create RunStore, supervise one invocation.
- Implement crash injection from authorization through result persistence.
- Produce a native artifact and SBOM.

Exit: simpler state ownership and UX are demonstrated, not merely promised.

### Phase 4 — Complete semantic loop

- Add Reviewer PASS/BLOCKED/REQUEST_CHANGES.
- Add one bounded rework and terminal decision.
- Add isolated workspaces, Artifact validation, trusted Git commit/push/PR/CI provenance.
- Pass shared fixtures against Python and Rust.

Exit: local loop parity for product semantics.

### Phase 5 — Agent Bus and cross-machine execution

- Integrate structured transport commands/results and idempotency keys.
- Preserve handler-success ACK and transactional outbox ordering.
- Prove redelivery and crash boundaries without duplicate invocation.
- Keep Bus independently released and Workflow-unaware.

Exit: no-model Mac/Windows/Linux/VPS transport acceptance.

### Phase 6 — Cross-platform lifecycle and distribution

- Implement narrow launchd/systemd/Task Scheduler adapters.
- Bind native definition, AgentInstallation, incarnation, and exact stop.
- Add signed/checksummed artifacts, SBOM/provenance, immutable installs, upgrade and program rollback.
- Do not roll back Runtime state with program binaries.

Exit: supported target matrix meets release gates.

### Phase 7 — Real dogfood and switch

- Run fresh PASS and rework business cards across machines.
- Compare model-call counts, intervention, recovery, time-to-useful-run, and causal status quality.
- Make Rust default only after independent review and all switch gates pass.

Exit: Rust is production Runtime; Python is fallback for one bounded release window.

### Phase 8 — Delete Python Runtime

- Remove old CLI, facade, scripts, schemas, shims, and packaging experiments.
- Retain language-neutral fixtures, the method constitution, selected reference tools, and historical
  evidence.
- End the dual-production period.

## 15. Final Recommended Product Surface

### Installation

```text
brew install awf             # macOS example
winget install AgentWorkflow # Windows example
curl ... | verified installer # Linux only after a signed/checksummed distribution contract
```

The exact channels are future release decisions. The product requirement is one verified native
artifact/install, no Python prerequisite, and no independent scripts checkout. Agent Bus may be an
independent package but can be detected and guided by AWF.

### First run

```text
cd my-project
awf run "Implement TASK-017"
```

If configuration is absent, `run` performs interactive onboarding. `awf init` exists for users who
want to configure first or generate automation config without starting work.

### Configuration

- Default: none when Git and local agents are unambiguous.
- Optional: one small `.awf/config.toml` with agent assignments and policy overrides.
- Secrets: platform credential/config store, never the project file.
- CI: `awf run --non-interactive --config ... --task ... --json`.

### Run

```text
awf run docs/tasks/TASK-017.md
awf run "Fix issue #42 within the approved scope"
```

`run` performs internal checks and starts or recovers the single legal transition. It never silently
requeues historical work or repeats an ambiguous model invocation.

### Status

```text
$ awf status
Task: TASK-017
State: waiting for review
Coder: completed once (commit abc123)
Reviewer: running on mac-reviewer
Transport: healthy
Next: no action required
```

On failure:

```text
State: blocked before reviewer invocation
Cause: reviewer agent is installed but not connected
Safety: no reviewer model call was authorized; coder delivery remains durable
Next: sign in on mac-reviewer, then run `awf run`
```

### Failure recovery

- `awf run` automatically resumes only proven safe states.
- `awf status` reports ambiguous external effects and never offers automatic retry for them.
- `awf admin recover ...` exists only for explicit, evidence-backed operator actions.
- There is no normal user `ACK`, `requeue`, checkpoint, outbox, lease, or state-root command.

### Multi-machine

```text
awf agent add               # prints a bounded pairing/enrollment flow
awf agent list
awf run                     # selects configured local/remote agents automatically
```

Users see agent name, capability, machine, and health. Listener, service manager, Bus token, route,
and lease remain internal unless `awf debug` is requested.

### Advanced/debug

```text
awf debug doctor --json
awf debug state
awf debug logs --agent reviewer
awf debug contract
awf admin agent restart reviewer
awf admin recover --run <id>
```

Debug is read-only by default. Admin mutations name exact targets and retain fail-closed ownership.

## 16. Final Go / No-Go Table

| Decision | Result |
|---|---|
| Current architecture needs major redesign | **YES** |
| Current safety/reliability semantics are valuable | **YES** |
| Current implementation is over-engineered | **YES, in state/interface shape** |
| Existing compatibility should be preserved | **NO** |
| CLI should be radically simplified | **YES** |
| Normal path should converge on `run/status/stop` | **YES** |
| Interactive onboarding recommended | **YES, as part of hybrid UX** |
| State root/profile/listener/preflight should be beginner concepts | **NO** |
| Agent Bus should become Workflow Runtime | **NO** |
| Code/document remediation merged | **YES** |
| Post-remediation business validation required before implementation | **YES; NOT YET COMPLETE** |
| Fresh-machine and cross-platform no-model validation complete | **YES** |
| Post-remediation real business validation complete | **NO** |
| Python should remain long-term Runtime | **NO** |
| Python + native launcher is useful | **ONLY AS BRIDGE/CONTINGENCY** |
| Go is a viable fallback target | **YES** |
| Rust is preferred target Runtime | **YES, SUBJECT TO VERTICAL-SLICE GO/NO-GO** |
| Post-remediation is the right Rust rewrite node | **CONDITIONAL YES** |
| Immediate full Rust implementation should start today | **NO** |
| Rust contract/design work should start today | **YES** |
| Python should become reference/oracle and bugfix-only | **YES, after the missing dogfood gate** |
| Rust may redesign CLI/state/config | **YES; REQUIRED** |
| Old Python Runtime should eventually be deleted | **YES** |
| Permanent dual Runtime is recommended | **NO** |

## 17. Evidence and Review Limits

This review inspected the current repository documentation and production/test code, including the
constitution, README, HANDOFF, roadmap, architecture/runtime documents, remediation TaskCards and
reports, CLI/facade/node/node-service/manifest/status/control-plane/role/dispatch/preflight/Agent Bus
integration, lifecycle adapters, trust-boundary tests, binary feasibility/readiness, fresh-machine
acceptance, and real dogfood evidence.

Static measurements at the reviewed commit:

- production Python under `src/agent_workflow`, `scripts`, and provider adapters: approximately
  17,152 lines;
- Python tests: approximately 14,631 lines;
- 478 test functions, including 232 in `test_awf_role.py`;
- beginner benchmark: seven commands, five decision groups, and four generated config/contract files
  before managed-install/runtime state;
- binary matrix: 15 candidate/target records, zero candidates passing all target gates.

No local Pytest, Ruff, Rust, Go build, service mutation, Agent Bus event operation, model invocation,
or remote-machine mutation was performed for this review. This follows the local Mac verification
policy and the user-scoped request to review rather than implement. Repository code and existing CI,
TaskCard, implementation-report, and dogfood artifacts are the evidence base.

The most important uncertainty is explicit, not hidden: the final remediation shape needs one fresh
real business loop. That evidence should decide the exact feature-freeze date; it should not reopen
the target architecture unless it reveals a new semantic invariant.
