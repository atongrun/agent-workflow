# Repository Handoff

> Current through the 2026-08-12 Dogfood Finding Phase A implementation follow-up, the accepted
> 2026-08-09 three-TaskCard downstream dogfood, and the 2026-08-10 `v0.3.0` release documentation.
> The minimum
> dispatch floor is the merge containing this handoff; repository files and live Git refs are
> authoritative for the exact SHA. This
> document contains no private endpoint, credential, host, personal-path, or event-payload data.

## Current Handoff State: 2026-08-20 Runtime v2 Decision Plan

The owner-authored Runtime simplification Review, independent adversarial double review and gated
development plan are integrated by PR #96 at merge commit
`712365b8a462f2c9ca27b461f91125fff344caca`. RTS-043 is the last passed
TaskCard gate: the language-neutral semantic contract and machine-readable fault matrix are
`Frozen`; the matrix contains 39 unique cases and
11 normalized outcomes, and the current inventory names six authority domains plus 28 persistent
record families without hiding external Agent Bus/Git/GitHub/OS/provider truth. Independent Review
2 returned `PASS` with zero findings. See the
[TaskCard](docs/tasks/runtime-v2-semantic-contract-draft.md),
[contract](docs/runtime-v2-semantic-contract.md),
[fault matrix](docs/testing/runtime-v2-fault-matrix.md),
[inventory](docs/testing/runtime-v2-authority-record-inventory.md), and
[implementation report](docs/tasks/runtime-v2-semantic-contract-draft-implementation-report.md).

PR #96's exact reviewed semantic TaskCard commit is `021e054`; later evidence-only commits preserve
the transient integration stop and its clearance. Ordinary Ubuntu/Windows/macOS and installed-wheel
CI passed. `native-macos-arm64` initially failed three bounded attempts
at the same external GitHub API `403 rate limit exceeded` while resolving the latest
`python-build-standalone` release; current main's last comparable run was green. The integration
state was `EXTERNAL_BLOCKED`. Evidence-only commit `c9130a9` then triggered fresh ordinary and
Binary Feasibility runs that completed green across all jobs, including all five native cells and
the aggregate. Exact-head Review and CI then passed on `e6d3081`; the PR merged, so that block and
integration gate are closed.

RTS-001 changed no Runtime code or external state. Its compiled RunContract handler-binding gap was
confirmed during RTS-010 entry preparation and fixed by PR #97, merged as
`38dffae1aeb68c8176dd25719a8bc19b16408199`: the first role gate copies the digest only from a
successfully recovered current ledger packet. Exact-head ordinary CI, Binary Feasibility and
independent Review passed before merge.

Two separately frozen RTS-010 authorities then failed closed before any provider invocation. The
first isolated Windows listener hid the normal Git network configuration by overriding host
application-data roots; upstream fetch exhausted the transport retry budget without a RunLedger
authorization. A fresh r2 authority corrected that harness boundary and proved the upstream fetch,
then exposed a cross-platform immutable-identity defect: Windows `awf run` wrote the TaskCard with
backslashes while the canonical delivery used `/`. Its ledger sequence, authorized events and
attempts also remained zero. Neither failed delivery was ACKed, requeued, redispatched, recovered,
hot-patched or counted as acceptance evidence; their branches, isolated Bus stores, ledgers and
handler evidence remain retained.

PR #98 fixed only the owner identity source with `Path.as_posix()` and added a Windows-effective
regression. Exact-publication-head ordinary CI and independent Review passed; Binary Feasibility
passed all five native targets plus aggregate after rerunning one macOS x86_64 Artifact Service
upload timeout. The PR merged as `d92594dcb2ba48efe2ed62c2f236b629a07f85fe`.

A third wholly fresh authority pinned that merge and completed RTS-010. Dousansi TaskCard
`dousansi-runtime-v2-rts-010-home-reconsideration-r3-20260820` used a fresh isolated Bus,
state-root, profiles, run, branch and delivery. Deep Preflight passed, then exactly one Windows
OpenCode implementation and one Mac Pi review produced downstream commit `f7ef229`, Pi `PASS`,
terminal `review_passed`, five handler-success ACKs, and final architect/coder/reviewer queues
`0/0/0`. Downstream PR #40 passed exact-head CI and merged as `dfa7237`. The local terminal ledger
retains CI/merge as unrecorded while external GitHub/Git facts prove them; no terminal mutation was
performed. See the
[RTS-010 acceptance report](docs/tasks/runtime-v2-rts-010-fresh-pass-acceptance-report.md).

PR #100 corrected the former second-review transition/attempt-capacity gap. PR #101 then completed
RTS-011 on one disposable repository and state root: exactly one implement, one rework and two
review child processes; exact lineage, duplicate/drift denial, same-event durable result recovery,
outbox/inbox and terminal ordering all passed. Both reviews retained input `attempt=1`. The ACK
observer, transport send, provider intelligence and GitHub provenance were synthetic and make no
real-business claim. Independent Review passed after one bounded route/schema correction; ordinary
CI run `32301184219` and Binary Feasibility run `32301184171` passed every job on executable head
`2868486`. See the
[RTS-011 acceptance report](docs/tasks/runtime-v2-rts-011-deterministic-rework-acceptance-implementation-report.md).

RTS-020 then completed the removable Python shared slice on repair head `457a336`: one
implement child, one review child, terminal completion, idempotent replay, read-only status, exact
local stop and all eight fault families across 14 machine rows. One RunStore writer and one
InvocationJournal API retained separate authorization, launch, result, Artifact, Git effect,
handoff and terminal facts. Independent implementation Review passed after two bounded repair
rounds. Pre-final-review head `77c7023` passed ordinary CI run `32308287706` and Binary Feasibility
run `32308287696`. The first exact-head Review found one corrupt authorized-journal outcome mismatch;
`457a336` fixed both implement and review authorization states without provider start or state repair.
See the [RTS-020 closeout](docs/tasks/runtime-v2-rts-020-python-shared-slice-implementation-report.md).

RTS-021 then passed the same removable slice for checksummed atomic-file and stdlib SQLite Stores.
Both retained all 14 shared rows and removed the same four local ordering windows; SQLite passed
contention/restart/corruption/restore/migration/read-only-status/exact-stop gates but bought no
unique Workflow ownership reduction. PR #103 pre-closeout head `00baa356` passed ordinary CI run
`32314492329` and Binary Feasibility run `32314492349`; final closeout-head CI/Review remains.
See the [RTS-021 closeout](docs/tasks/runtime-v2-rts-021-storage-comparison-implementation-report.md).

RTS-022A then returned `RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE`. The removable
zero-dependency Rust executable preserved all 14 Candidate rows on five native targets; every cell
recorded `python_invoked=false`, exact run/status/replay/stop facts, and implement=1/review=1.
Pre-closeout head `3be3263` passed ordinary CI run `32322178827` and Binary Feasibility run
`32322178851`. Its 3,471-line numerator exceeds the frozen threshold, so RTS-022B is mandatory: one
separately frozen independent-maintainer injected-fault diagnosis/repair card. This does not choose
Rust, SQLite, a physical Coordinator or product boundary. RTS-023 remains conditional on a
Rust-specific stop with native value still present. Do not inspect or operate retained events. No
production migration, default, release or destructive decision has been made. See the
[RTS-022A closeout](docs/tasks/runtime-v2-rts-022-rust-shared-slice-implementation-report.md).

RTS-022B then returned `RUST_MAINTAINER_GATE_PASS`. A fresh maintainer independently diagnosed one
blinded launch-intent ambiguity/no-replay fault from current code, the frozen contract, existing
tests and exact seeded CI logs, and restored it in one semantic repair. Seeded Binary Feasibility
`32324044913` compiled all five Rust targets then failed the same existing row; candidate ordinary
CI `32324509595`, Binary Feasibility `32324509603` and independent Gate Review passed. Final Rust
source matches the RTS-022A main source exactly. RTS-023 does not enter. RTS-024 is now
the owner decision gate; its result is recorded below. See the
[RTS-022B closeout](docs/tasks/runtime-v2-rts-022-maintainer-fault-gate-implementation-report.md).

RTS-024 then returned `PASS — PYTHON + NATIVE LAUNCHER`. The owner selected Python refactoring,
checksummed atomic-file RunStore plus a per-invocation journal API, and one logical Workflow writer
without a physical always-on Coordinator. Rust remains a comparison oracle, RTS-023 does not enter,
SQLite is not selected, and the native launcher is a separate bounded distribution candidate only
after Phase 3 stabilizes the Python package/application boundary. Independent Architecture Review
passed. A separate Adversarial Review found one Python LOC-head ambiguity; repair `5da55fd` recorded
1,380 runner lines at `77c7023` and 1,396 at repair head `457a336`, then focused re-review passed.
ADR-0006 is accepted and the semantic contract/fault matrix are Frozen without changing any of the
39 cases or 11 outcomes. Phase 3 starts with separately frozen RTS-030. No production default,
state migration, launcher acceptance, release, retained-event operation or destructive cleanup is
authorized. See the [RTS-024 closeout](docs/tasks/runtime-v2-rts-024-decision-implementation-report.md).

RTS-030 then returned `PASS` for the first reversible Phase 3 Python Core package/interface
boundary. The installed `agent_workflow.runtime` package defines strict immutable RunSpec,
InvocationSpec and canonical RenderedInvocation identities plus narrow logical RunStore,
per-invocation journal, read-only status and pure renderer ports. It imports no packaged operations
scripts and changes no production/default Runtime path. Candidate ordinary CI `32335336859` and
Binary Feasibility `32335336776` passed. Independent Gate Review found one missing canonical launch
identity; repair `c9e2c5f` bound executable/argv/cwd/environment and stdin digest/length, repair CI
passed the affected tests and installed-wheel gates, and the same Reviewer focused re-review passed.

RTS-031 then returned `PASS` for the disposable local atomic Store/journal implementation. One
checksummed authority envelope owns immutable RunSpec, Workflow transitions, embedded invocation
facts, outgoing intent and terminal behind one exact writer lock. Candidate ordinary CI
`32341036671`, Binary Feasibility `32341036800` and independent Review passed after repair `2d4576b`
closed parent-path symlink/reparse traversal. No production handler, legacy representation,
external truth, dependency, default or migration boundary changed.

RTS-032 then returned `PASS` for the production provider-renderer seam. Closed installed OpenCode
coder/reviewer, Codex reviewer and Pi reviewer renderers receive one fully bound immutable
`InvocationSpec` and return one canonical `RenderedInvocation` at the existing spawn boundary.
Independent Gate Review returned PASS with zero findings. After an L1 test-stub compatibility
repair, exact-head ordinary CI `32345260471` and Binary Feasibility `32345260487` passed at
`1028eae`. Current RunLedger/checkpoint/outbox/inbox/RunEvidence state remains the sole production
authority and recovery path; no Store adoption, dual write, migration, default or provider replay
change occurred. See the
[RTS-032 closeout](docs/tasks/runtime-v2-rts-032-provider-renderers-implementation-report.md).

RTS-033 then returned `PASS` for the isolated-workspace and trusted local import seam. The installed
Runtime now owns exact event-contained no-remote preparation, compatible Git-control identity,
bounded binary-delta serialization and equal-tree trusted import. Independent Review returned PASS
with zero findings; exact-head ordinary CI `32349631233` and Binary Feasibility `32349631258`
passed at `75a4630`, including Windows staged-tree provenance. Current
RunLedger/checkpoint/outbox/inbox/RunEvidence state remains sole production authority. See the
[RTS-033 closeout](docs/tasks/runtime-v2-rts-033-workspace-import-implementation-report.md).

RTS-034 then returned `PASS` for the Artifact validation seam. The installed Runtime owns
TaskCard/report identity, strict report policy, exact raw Artifact facts and postflight decisions;
the operations scripts retain trusted observations/execution and compatibility mapping only.
Independent Gate Review returned PASS at `f10ab60`; ordinary CI `32355614215` and Binary
Feasibility `32355614216` passed after one external GitHub API 403 single-job rerun. Current
RunLedger/checkpoint/outbox/inbox/RunEvidence remains sole production authority. See the
[RTS-034 closeout](docs/tasks/runtime-v2-rts-034-artifact-validation-implementation-report.md).

RTS-035 then returned `PASS` for the selected disposable local application boundary. One installed
`LocalRuntimeApplication` composes the accepted RunSpec, atomic Store/journal, closed renderers,
isolated workspace/trusted import and Artifact policy behind `run`, read-only `status` and exact
local `stop`. All legal PASS, bounded rework/second-review/PASS and BLOCKED paths plus the 14 shared
fault rows passed. Independent Gate Review found zero issues at `9d34532`; ordinary CI
`32363592197` and Binary Feasibility `32363592149` passed. The Windows candidate failure was closed
by binding the fixture to existing platform `core.autocrlf` semantics without weakening
`git diff --check`. Current production authority/defaults remain unchanged. See the
[RTS-035 closeout](docs/tasks/runtime-v2-rts-035-local-application-implementation-report.md).

Phase 3 is complete. The next safe action is a separately frozen RTS-040 Phase 4A Stage-blind
command/result envelope boundary. It may begin only with disposable no-model state and must keep
Agent Bus send, handler success and ACK as external observations. It must not operate production or
retained events, dual-write/migrate authority, change defaults, begin native-launcher work, release
or delete compatibility. Fresh isolated cross-machine acceptance remains a later Phase 4A gate.

RTS-040 then returned `PASS` for that local transport-envelope boundary. One strict versioned
command/result family now binds exact owner, route, invocation, authorization, payload and causation
identity and rejects malformed or mismatched input before application/provider entry. Result
preparation joins exact Store-owned outgoing facts without transport, send, handler-success or ACK
authority. Independent Gate Review returned PASS with zero findings at `8adacc9`; exact-head
ordinary CI `32368582902` and Binary Feasibility `32368582891` passed. See the
[RTS-040 closeout](docs/tasks/runtime-v2-rts-040-transport-envelope-implementation-report.md).

The next safe action is a separately frozen RTS-041 Store-owned outgoing-intent and bounded Agent
Bus adapter boundary. It may atomically retain exact canonical result-envelope bytes in the selected
disposable Store and exercise one narrow injected adapter with explicit send observations. It must
not adopt or dual-write production authority, modify Agent Bus, operate production/retained events,
retry ambiguous sends, infer handler success/ACK, perform live cross-machine acceptance, change
defaults, migrate state, begin lifecycle/launcher work, release or delete compatibility. Fresh
isolated Mac-to-Windows no-model acceptance remains the following Phase 4A gate.

RTS-041 then returned `PASS` for that local outgoing-intent adapter boundary. Each accepted
handoff/terminal effect now commits exact reconstructable result-envelope bytes in the same atomic
authority. One Stage-blind injected dispatcher persists `attempting` before I/O and records only
`sent` or `ambiguous`; duplicate in-flight and stopped state cannot authorize replay. Initial Gate
Review findings on stale-prepared concurrency and stopped status were repaired at `beec962`, and
focused re-review returned PASS with zero findings. Exact repaired-head ordinary CI `32376015654`
and Binary Feasibility `32376016069` passed. See the
[RTS-041 closeout](docs/tasks/runtime-v2-rts-041-outgoing-intent-adapter-implementation-report.md).

The next safe action is a separately frozen RTS-042 fresh isolated Mac-to-Windows no-model
request/result acceptance using the selected adapter boundary. It must use fresh isolated
Bus/config/state/queue identities, run a real child handler, prove external success-gated ACK and
scoped queues `0/0 -> 0/0`, and preserve exact identity. It must not invoke a model/business
handler, touch production or retained events, adopt/dual-write production authority, change
defaults, migrate state, begin lifecycle/launcher work, release or delete compatibility.

RTS-042 is currently **EXTERNAL_BLOCKED / evidence preserved**, not accepted. The first isolated
identity delivered its command to Windows, where the handler failed closed before its bounded
child and before Store initialization. Agent Bus then owned the `/fail` transition and atomically
wrote `retry_count=1`; no result event existed. Read-only diagnosis proved that both hosts had the
same Git HEAD but the fixture hashed platform-normalized working-tree Markdown bytes, so Windows
CRLF conversion split the immutable RunSpec. The failed event/database/log/state remains retained
and was not retried, requeued, ACKed, replaced, deleted or counted as PASS.

Bounded repair `037d514` derives the two frozen document hashes from exact candidate Git blobs.
Ordinary CI `32386481057` and Binary Feasibility `32386481051` passed exact head. One separately
owner-authorized identity then completed the real Mac-to-Windows command and Windows-to-Mac result:
two bounded children returned zero, the Store recorded `attempting -> sent`, two isolated events
were ACKed with zero retry/error facts, and scoped queues converged `0/0 -> 0/0`. Its exact resources
were safely removed; all failed-identity roots were confirmed retained afterward. This validates
the local fixture RCA but does not retroactively promote the failed identity or the TaskCard.

The next safe TaskCard is an event-free **RTS-043 Phase 4A evidence adjudication and closeout**.
It should perform the one independent Gate Review over the preserved failure, bounded repair and
fresh-success evidence, then either close Phase 4A without another live event or record a concrete
invariant conflict. It must not create a third acceptance identity, operate retained events, change
production/default/migration, or begin Phase 4B before that review gate.

RTS-043's independent Gate Review found no semantic or architecture conflict and adjudicated
RTS-040, RTS-041 and RTS-042 as jointly satisfying all five Phase 4A exit criteria. Its sole
semantic-review `REQUEST_CHANGES` finding was that the RTS-043 closeout artifacts and gate-status
updates had not yet been written; a focused packaging finding then required the ignored artifact to
be explicitly tracked. Both documentation-only findings are closed, and final focused re-review
returned `PASS`. The closeout records that `rts042-live-20260820-01` remains
terminal failed, `EXTERNAL_BLOCKED / evidence preserved`, and can never be future PASS evidence;
`rts042-live-20260820-02` is the only successful acceptance. No retry, requeue, manual ACK,
replacement delivery, manufactured completion or third identity occurred. Phase 4A is closed. The
next safe action is a separately frozen Phase 4B TaskCard; no lifecycle implementation is authorized
inside this closeout.

RTS-044 next reused the current lifecycle implementation instead of adding a speculative
`AgentInstallation` abstraction. Its initial independent Review returned `REQUEST_CHANGES` for two
real exact-identity gaps: managed native stop did not strictly require process-record state-root
evidence, and installed state did not bind manager ID/definition path to the deterministic adapter
target. RTS-045 repaired only those joins. Missing/partial/drifted process roots now produce zero
native calls and remain ineligible for exact-dead cleanup; foreign manager IDs or self-consistent
alternate definition paths no longer project current installation or authorize upgrade stop.

RTS-045 independent L3 Review returned `PASS` at `37ea274`; focused validation passed 75 tests with
one platform skip, the full suite passed 876 with five skips, ordinary CI `32544625110` passed and
Binary Feasibility `32544625218` passed all cells/aggregates. RTS-044 local lifecycle conformance is
therefore closed without a new record, migration, native-manager operation, Agent Bus action or
production change. Phase 4B itself remains open. The next safe milestone is separately frozen
**RTS-046 fresh isolated three-OS native-manager acceptance**. It may assume Agent Bus already
exists but may not install it or operate business events. Windows logout/login or reboot remains a
disruptive external action requiring an explicitly scheduled owner window.

## Current Handoff State: 2026-08-17

The final fresh-machine no-model usability gate is green. The original benchmark's disposable
installed-wheel local journey completed the seven facade commands in 0.0379 seconds, then its
cross-machine attempt correctly stopped at `BLOCKED_BEFORE_DEEP`. A separately authorized rerun
used fresh exact-main Python 3.12 environments and a fully isolated Bus/config/state surface on
Mac, VPS, and Windows. All three Fast Preflights passed 9/9 layers with architect/coder queues at
zero. One Mac architect to Windows coder Deep Preflight passed 9/9 layers in 9.303 seconds, both
handler children succeeded, two distinct disposable control records were acknowledged, and queues
returned `0/0 -> 0/0`. All temporary processes, credentials, repositories, environments, state,
database, logs, and reports were removed; the distinct production Bus remained active. No model
or business event was used, and no production or retained delivery was inspected or operated.
The current milestone result is `PASS`. See the
[benchmark TaskCard](docs/tasks/fresh-machine-usability-benchmark.md) and
[historical report](docs/tasks/fresh-machine-usability-benchmark-report.md), plus the
[acceptance closeout](docs/tasks/fresh-machine-usability-acceptance-closeout-report.md).

Passing the no-model gate removes the acceptance blocker but does not invent business scope. The
next business action still requires its own explicit TaskCard; do not infer it from a production
pending delivery or reuse a retained event.

P2 completed the 15-cell native binary distribution matrix without changing production runtime.
PyInstaller one-folder, PEX scie eager, and a checksum-verifying Go launcher paired with an
independently versioned PEX app all failed the frozen all-five-target acceptance gate. The
deterministic result is `NO_GO_PRODUCTION_BINARY`: no candidate preserved Python interpreter
re-entry on every target, and the PEX-based candidates also failed their Windows runtime/no-model
probe. Packaged resources, native lifecycle rendering, exact argv/UTF-8 where reported, Go checksum
failure, artifact size/startup/SHA, CycloneDX SBOMs, and the disposable SQLite Bus smoke remain
useful measured research. No production ABI, installer, updater, signing/notarization claim, live
event, model invocation, or service mutation was created. See
[`docs/tasks/binary-distribution-feasibility.md`](docs/tasks/binary-distribution-feasibility.md) and
its [report](docs/tasks/binary-distribution-feasibility-report.md).

P2b turns that matrix into an actionable release-readiness contract without changing production
code or adopting a binary ABI. The raw post-merge evidence confirms 15/15 Python interpreter
re-entry failures, two Windows PEX-family runtime failures, zero passing candidates, and four Go
manifest-swap successes. Repairing one freezer is therefore not the shortest legal path. The next
recommended candidate is a small native launcher plus relocatable real CPython and an installed
AWF application; Agent Bus stays independently distributed. Four technical blockers remain:
functional five-target runtime bundle, production distribution contract, supply-chain trust, and
release lifecycle/RC acceptance. Live artifact publication is a separate explicit authorization
boundary. See [`docs/tasks/binary-release-readiness-report.md`](docs/tasks/binary-release-readiness-report.md).

P1-3 removes the remaining production handler command-template boundary. Role, coder rework,
architect terminal and optional no-model Preflight registrations are exact `awf.handler-argv.v1`
lists serialized as UTF-8 JSON for the pinned Agent Bus `agent-bus.listen.on-argv.v1` consumer.
Executable/script/config/state-root paths and payload placeholders remain separate tokens; existing
`awf_role.py` delivery/provenance/state-root/stage/checkpoint/outbox/postflight and return-code gates
are unchanged. Install/activate the compatible Bus before Workflow; roll back Workflow before Bus.
An older Bus rejects `--on-argv` before SSE connection or event delivery, with no event-time
fallback. See [`docs/tasks/structured-handler-contract.md`](docs/tasks/structured-handler-contract.md)
and its [implementation report](docs/tasks/structured-handler-contract-implementation-report.md).

P1-2 adds a thin beginner facade without adding a second configuration or control plane. `awf
init`/`enroll` generates credential-free coder/reviewer profiles in the platform config home,
validates them with the existing node contract, and reuses setup to write the default owner
RunManifest and compiled run contract. Top-level doctor/start/run-check/run/status/drain/stop
discover those exact bindings; old setup/plan/node/run/status forms remain available. Managed
start installs only from explicit `not_installed` evidence, while unknown/stale installation facts
fail closed. Drain collects read-only queue counts for all selected profiles before any exact stop.
No facade operation ACKs, requeues, recovers, dispatches, flushes Feedback, reads a business
payload, or invokes a model. See [`docs/tasks/thin-usability-facade.md`](docs/tasks/thin-usability-facade.md)
and its [implementation report](docs/tasks/thin-usability-facade-implementation-report.md).

P1-1 makes run-aware node status causal without making it active. `awf node status --run ...
--explain` projects existing lifecycle, RunLedger and exact authorized-delivery checkpoint facts
into stage/attempt, first blocker, owner/cause, model-invocation evidence, payload-blind event
observation, and one legal next action. Feedback capture/outbox/flush is reported as an independent
top-level component, so neither business terminal/ACK nor pending Feedback rewrites the other.
Status does not ACK, requeue, recover, redispatch, flush, mutate lifecycle, or invoke a model. The
UTF-safe executor/native-manager/log boundary was completed separately in P1-1a. See
[`docs/tasks/causal-status-and-feedback-diagnostics.md`](docs/tasks/causal-status-and-feedback-diagnostics.md).

P0-5 closes the implement-to-rework workspace ownership gap for trusted v3 runs. The initial coder
checkpoint now separates immutable delivery/source identity from the expected trusted transition
to the verified implementation commit and records the imported tree, stable Git-control binding,
and post-transition manifest. A rework resolves the unique prior authorized implement delivery
from the same RunLedger and reuses that exact no-remote workspace only when the completed handoff,
current PR tuple/commit, checkpoint digest, and Git manifest all match before provider invocation.
Agent Bus payloads, control-plane stage/budget authority, same-delivery no-replay behavior, and
business/Finding ACK separation are unchanged. See
[`docs/tasks/implement-rework-workspace-transition.md`](docs/tasks/implement-rework-workspace-transition.md).

P0-4b makes the proven compiler a mandatory setup/run gate. Setup now stores the canonical
state-root and coder/reviewer profile references in the credential-free owner RunManifest, compiles
the complete current graph, and writes owner-only `.awf/run-contract.json`. Run reloads and
recompiles the exact owner/authority/TaskCard/profile/state-root graph, requires report equality,
and binds `run_contract_sha256` into the context packet before Git HEAD lookup or RunLedger
initialization. Generic setup/run `--manifest` and old uncompiled manifests fail with an explicit
migration; lower-level native dispatch is unchanged. See
[`docs/tasks/compiled-run-consumption-gate.md`](docs/tasks/compiled-run-consumption-gate.md).

P0-4a adds a read-only contract compiler before any normal execution-surface switch. The
`awf plan check` command keeps `awf.run-manifest.v1` owner intent distinct from the internal
`awf.authority-manifest.v1`, validates TaskCard/ImplementationReport/ReviewReport allowlist,
run/branch, v1-v3 routes, role tool/model, repository/provenance, canonical state-root, and exact
durable profile identities, then prints a deterministic `awf.run-contract-report.v1` with
compiler provenance and SHA-256 bindings. It never initializes a ledger, mutates Git, connects to
Agent Bus, starts a process, or emits an event. Normal `setup`, `run`, and `dispatch` consumption is
unchanged until P0-4b. See
[`docs/tasks/read-only-run-contract-compiler.md`](docs/tasks/read-only-run-contract-compiler.md).

P0-3 makes managed profile identity durable beyond its authoring file. Install writes one
credential-free content-addressed snapshot and exact source/name registry beneath the platform AWF
configuration directory; launchd, systemd, and Task Scheduler definitions reference that snapshot.
Managed start/status/logs/stop/restart/upgrade/uninstall and reconcile therefore use the installed
identity even when the authoring file moved or disappeared. Exact stop still requires the native
install/definition, installed profile digest, role/repository/state-root, launch identity, process
creation identity where supported, and live lease to agree; no broad process-name or PID-only stop
was added. See [`docs/tasks/durable-profile-exact-stop.md`](docs/tasks/durable-profile-exact-stop.md)
and its [implementation report](docs/tasks/durable-profile-exact-stop-implementation-report.md).

P0-1 of the usability remediation now defines one canonical host-local state-root contract for
node-managed execution. A node profile explicitly owns the root; listener argv, generated business
and preflight handlers, process/lease evidence, RunEvidence, RunLedger context, delivery
checkpoint/outbox/inbox, Feedback Outbox, readiness, and factual status share its credential-free
binding. Disagreement is rejected before Agent Bus connection or provider/model invocation, while
direct script entry retains an explicit platform-default compatibility path. No lifecycle
vocabulary, Agent Bus behavior, business/Finding ACK separation, retained event, Phase B, Agent
Host, compiler, rework, status redesign, or binary work changed. The frozen scope and evidence are
in [`docs/tasks/canonical-state-root-contract.md`](docs/tasks/canonical-state-root-contract.md) and
its [implementation report](docs/tasks/canonical-state-root-contract-implementation-report.md).

P0-2 replaces the node doctor's ambiguous top-level `status: ready` with independent
`configured`, `installed`, `running`, `connected`, and `dispatch_capable` facts in
`awf.node-readiness.v2`; factual node status carries the same lifecycle block while leaving facts
it did not observe unknown. Managed installation comes only from the current native install record
and definition, running still requires exact process/profile/lease/launch identity, and only a
bounded Bus doctor probe establishes connected. Node commands never promote missing, stale, or
unexamined Fast/Deep evidence to dispatch authority. Managed `start` consistently fails before
desired-state mutation when uninstalled and gives the exact explicit `install` action instead of
silently installing. See
[`docs/tasks/truthful-lifecycle-state-model.md`](docs/tasks/truthful-lifecycle-state-model.md) and
its [implementation report](docs/tasks/truthful-lifecycle-state-model-implementation-report.md).

The current Phase A follow-up adds an independent Dogfood Finding operations path: one strict,
source-gated Finding may be stripped from existing OpenCode coder/reviewer, Codex reviewer, or Pi
reviewer Reports before formal validation/import, queued under a separate Feedback Outbox, sent
only by `awf feedback flush`, and durably deduplicated by `awf feedback ingest` before Agent Bus
handler success permits ACK. Agent Bus Core, Workflow roles/stages, business checkpoint/outbox/ACK
semantics, triage, grouping, publication, and automatic flush remain unchanged. The explicitly
authorized reporter deployment is live as a dedicated identity and hardened system service. One
fresh disposable event proved durable ingest before handler-success ACK, empty reporter pending/
failed queues, and restart recovery; credentials remain outside Git in protected files. The bounded
contract and current verification are in
[`docs/tasks/dogfood-finding-phase-a.md`](docs/tasks/dogfood-finding-phase-a.md) and its
[implementation report](docs/tasks/dogfood-finding-phase-a-implementation-report.md).

The first non-infrastructure product gate is complete. Three serial Dousansi TaskCards ran through
the managed Windows OpenCode coder, Mac Pi reviewer, deterministic architect terminal consumer,
trusted commit, pull request, green CI, terminal ACK, merge, and empty queues. Each business card
used one coder and one reviewer model invocation; there was no rework, escalation, manual
ACK/requeue/redispatch, or high-value model call inside a delivery handler. Exact surrounding
planning and milestone-acceptance call counts were not instrumented, so no precise token/cost claim
is made. The durable evidence and limitation are recorded in
[`docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md`](docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md).

The operations P0 prerequisites exposed by the stopped downstream run are merged: durable
run-ledger and context-packet gates, same-delivery checkpoint/outbox recovery, strict Python
configuration loading, native Python dispatch, one subprocess boundary, deterministic architect
terminal consumption, and Fast/Deep Preflight. PR #37 proved a fresh disposable no-model Deep
route and PR #38 extracted the existing Codex/OpenCode argv renderers without changing provider
selection, payloads, recovery, stage transitions, or ACK-sensitive lifecycle.

The installed operations wheel has an explicit node lifecycle contract. Existing profiles default
to `session`: local process-group control remains compatible, but `start` fails closed inside SSH
unless the operator explicitly accepts temporary session binding. A profile may instead select
`managed`, in which case one adapter supervises the same in-process foreground listener through a
launchd user agent, lingering systemd user unit, or Windows Task Scheduler user task. Secrets remain
in strict owner-only `dispatch.env`; the service profile, definition, argv, and install record are
credential-free. Agent Bus stays transport-only and no lifecycle command can read, ACK, requeue,
resend, or dispatch an event. See [`docs/runtime-node-lifecycle-architecture.md`](docs/runtime-node-lifecycle-architecture.md).

The Windows implementation deliberately does not use `DETACHED_PROCESS` or
`CREATE_BREAKAWAY_FROM_JOB`. Current-host OpenSSH Job probes proved that a new process group remains
session-bound, while breakaway survival loses the existing cross-session Ctrl-Break stop primitive.
The Windows task reuses the active local console user's `InteractiveToken`, reconciles every minute
while that console session is logged in, and needs no
service account, WinSW binary, password, or PowerShell setup. Agent Bus shutdown is the graceful
remote stop; exact-bound `taskkill /T` plus Task Scheduler End provides an independent local tree
stop. CI is implementation evidence only; the architecture document's fresh session A/B post-SSH
matrix remains the acceptance gate.

The node doctor also has a bounded machine-readable operator snapshot:
`awf node doctor --profile <profile> --json --ttl-seconds <seconds>`. It lets an architect replace
sequential host, path, tool, Bus, workspace, and listener discovery commands with one remote call.
The credential-free fingerprint and validity window are discovery evidence only; the report never
claims dispatch authority, writes a cache, emits an event, or replaces Fast/Deep Preflight. See
[`docs/tasks/node-readiness-snapshot-implementation-report.md`](docs/tasks/node-readiness-snapshot-implementation-report.md).

Node startup allows 15 seconds for the child listener to repeat startup validation and publish its
lease. A follow-up downstream run proved that elapsed time was not the remaining Windows boundary:
the virtual-environment `python.exe` redirector PID returned by `Popen` differs from the real
interpreter PID written into the lease. Node-managed starts now bind the process record and listener
lease with one random per-start identity, independent of launcher depth, while retaining the
launcher PID for process-group signaling and the interpreter PID for listener conflict detection.
Process-exit detection remains immediate and an absent or unrelated lease still fails closed at the
bounded deadline. Installed-wheel CI launches a real venv child and locks both the Windows
redirector observation and launch-identity contract. See
[`docs/tasks/windows-venv-pid-binding-implementation-report.md`](docs/tasks/windows-venv-pid-binding-implementation-report.md).

`awf node status --profile <profile> [--run <run-id>] [--json] [--explain]` is the factual read-only
view. It
keeps recorded and live PR/CI facts separate, reports unavailable observations honestly, and names
ReviewReport raw-file and normalized-object hashes as `file_sha256` and
`canonical_report_sha256`. Its causal projection and independent Feedback facts add no recovery or
event lifecycle mutation.
See [`docs/tasks/factual-node-status-implementation-report.md`](docs/tasks/factual-node-status-implementation-report.md).

The current addition implements the evidence-backed Pi reviewer need without introducing a generic
provider interface. Pi uses a pure argv renderer, read-only tools, explicit text-mode
non-interactive execution, trusted stdout persistence, and the existing isolated reviewer,
selection-integrity, checkpoint/recovery, ReviewReport, outbox, and ACK gates. Pi coder execution
remains unsupported.

The current operations UX repair keeps architect terminal verification out of shared checkouts.
Each terminal delivery creates an event-scoped no-remote workspace, copies only validated remote
bindings into it, and performs fetch, exact PR/commit verification, and artifact reads there. The
source checkout's HEAD, index, remote-tracking refs, tracked edits, and untracked files are left
unchanged. Listener startup now fails before Bus connection when the role workspace is not ready,
the same role already has a live PID, or another live role owns the same repository. Coder and
reviewer listeners require clean dedicated roots; architect may be dirty. Local `Ctrl-C` returns
130 without a traceback and releases only its exact lease. Terminal ledger-before-inbox ordering,
same-delivery replay, ACK-on-handler-success, v1-v3 payloads, and Agent Bus remain unchanged.

The installed-tree follow-up packages the complete production operations resource set into the
wheel and makes `awf` resolve it without cwd or repository-root assumptions. Packaged resources
include Python entry points, agent adapters, authority/config support, model Git guards/hooks,
service wrappers/templates, and artifact templates. Source/editable checkouts retain their existing
fallback. A dedicated three-OS CI matrix builds a real wheel, installs it into a fresh virtual
environment, changes to an unrelated directory, imports the operations modules, checks required
assets, and runs the installed CLI. Node lifecycle and status aggregation remain separate follow-up
PRs; this packaging change does not add a service manager, provider registry, or Agent Bus behavior.

The follow-up closes the mixed-role selection gap without changing the v3 payload schema. The
owner RunManifest can freeze `reviewer_tool`/`reviewer_model`, and the exact committed TaskCard
must carry the same coder/reviewer pairs in one `awf-reviewer-selection` JSON comment. Dispatch
compares both sources before mutation. Trusted handlers re-read the bound TaskCard after checkout:
coder handoff selects the frozen reviewer, Pi `REQUEST_CHANGES` selects the frozen coder, and any
role mismatch fails before model invocation. Legacy TaskCards without the block retain same-tool
behavior.

The current follow-up makes the Fast model-tool gate role-scoped without weakening model-executing
runtimes: only `source-role=architect` may explicitly declare the tool `not-applicable`; coder and
reviewer still require a real version-only probe. The declared policy, resolved executable, and
version-output hash are fingerprint inputs, so changing the role policy or selected CLI invalidates
the bound Deep proof.

PR #40 merged the v1-v3 executor-selection integrity gate as `e1184637f7bf8fa2010bd7f7e429b65d77bd62c8`.
On 2026-08-01, current Mac and Windows Fast checks passed against Dousansi
`main@6fd529307292eb25cd019a808287e4c0c2a83888`. A fresh Mac architect to Windows coder Deep
Preflight then completed through one disposable no-model request/result pair: both handlers
returned success, both events were success-gated ACKed, pending moved from exact zero back to
exact zero, and the bound report returned `allow_remote_dispatch=true`. The proof is cached for
the persistent clean Dousansi dogfood checkout and expires at `2026-08-01T21:27:25Z`; any path,
configuration, role, runtime, or transport change requires a fresh Fast check and, when indicated,
a new Deep proof.

The next product gate is a fresh bounded downstream dogfood on the existing OpenCode coder and
Codex/OpenCode/Pi reviewer execution paths. The Pi adapter is reviewer-only: `dispatch.env` may
set `AWF_PI_BIN`, Pi runs with read-only tools, and the trusted runner persists Pi stdout as the
ReviewReport only after rc=0. A generic invocation/result contract, registry, resolver, or Claude
adapter is not a prerequisite and remains deferred until dogfood proves a real need.

### v1-v3 executor-selection integrity

Existing v1-v3 deliveries had split executor-selection authority. `role_coder()` and
`role_reviewer()` prefer listener-local `AWF_TOOL`/`AWF_MODEL` over the integrity-hashed payload
arguments, while reviewer verdict payloads still report the original payload `tool`/`model`. A
misconfigured listener can therefore execute one provider/model and persist another identity in
downstream audit evidence.

The compatibility path now validates the effective listener selection immediately after delivery
hash/identity validation. A tool or model mismatch fails before control-plane authorization,
outbox replay, model launch, outbox preparation, or inbox completion. Matching v1-v3 deliveries
retain their prior behavior; legacy direct/no-delivery entry points retain listener-local
environment overrides. Reviewer verdict evidence now uses the validated effective identity. The
payload schema, delivery hash, defaults, checkpoints, outboxes, stages, and Agent Bus protocol are
unchanged. This does not introduce Phase 2's generic invocation/result contract or a new selection
authority.

PR #27 merged successfully as `f24b5fb1a4097a24b37210643dc15277f7b5dbe6`; its CI was green.
Draft PR #28 remains a separate terminal-replay/disposable-proof record and is not part of the
current change.

Fork/PR-aware trusted-runner [PR #29](https://github.com/atongrun/agent-workflow/pull/29) merged as
`88c70012697510c9959a7823d6af5529b5fe0395` after green CI and independent native security/code
review. A fresh contributor-machine proof then pushed only to the configured fork, freshly matched
the remote SHA, created [proof PR #30](https://github.com/atongrun/agent-workflow/pull/30), and
completed Mac review from that PR's exact persisted head SHA with a `PASS` verdict. Upstream write
permission was neither required nor tested.

The proof exposed a GitHub eventual-consistency race: PR creation succeeded while
`gh pr list --head` remained empty even though direct lookup by PR number worked. The runner
correctly withheld reviewer delivery and ACK. The current follow-up strictly parses the canonical
PR URL returned by trusted `gh pr create`, binds its exact number, and verifies the full tuple
without branch-list rediscovery. It also normalizes v3's initial `pull_request: 0` before
control-plane persistence.

That follow-up merged as PR #32 at `62b3d628a93aefcee371ce8ef6170a8042b32232`
after a fresh head/check audit and green CI. PR #28 was later closed unmerged and remains a
terminal disposable-proof record.

Agent Bus event handling was separately authorized. Historical coder events #97 and #100 were
classified as superseded/terminal and ACKed without executing their old product TaskCards. Proof
event #101 exposed a fixture-path failure plus an existing duplicate-without-outbox recovery gap;
it was terminally closed via the Bus-required requeue-then-ACK transition. Fresh event #102 passed
the Windows coder model isolation, postflight, fork push, fresh SHA, and PR #31 creation. Durable
checkpoint recovery later resumed that same event, freshly verified fork/PR provenance, sent
reviewer event #103, and ACKed #102 with the coder invocation count unchanged at one. Reviewer #103
recovered its same completed subprocess, emitted structured `PASS` decision #104 without a second
invocation, and was ACKed. Architect validated its canonical delivery hash and exact PR tuple before
ACKing #104.

### Fork/PR boundary

Default listeners subscribe only to v3 operations routes. Trusted local configuration owns remote
names and allowed repository identities; payloads contain no remote URL or credentials. Legacy
v1/v2 routes are explicit compatibility paths and do not consume v3 payloads. The complete
contract is in
[`docs/tasks/fork-pr-trusted-runner-implementation-report.md`](docs/tasks/fork-pr-trusted-runner-implementation-report.md).

## Product Position

### Thin operations menu contract

The owner-only `.awf/run-manifest.json` is the sole source for TaskCard-derived
branch, route, report, model, provenance, and rework metadata. `awf run` and
default `awf dispatch` validate and consume it; `dispatch.env` supplies only
secrets and runtime binaries. The serial operator uses the listener-compatible
`task-<branch-task-suffix>` run ID, and `awf status` renders missing
health/checkpoint/queue observations as `not_recorded`. Initial manifests with
an empty tool require an explicit `awf setup --replace --tool <tool>` migration.
`awf resume` reports one legal next action and does not execute replay, ACK,
requeue, or redispatch.

Agent Workflow is a model-agnostic development method, structured handoff protocol, and verifiable
process contract. It isolates scarce high-value-model capacity in downstream projects by assigning
frequent bounded work to lower-cost models and reserving high-value participation for architecture,
genuine escalation, and milestone acceptance. Infrastructure development may use high-value models
freely when quality or safety benefits.

Read in this order:

1. [`constitution.md`](constitution.md)
2. [`README.md`](README.md)
3. [`ROADMAP.md`](ROADMAP.md)
4. [`docs/adr/0005-high-value-model-capacity-isolation.md`](docs/adr/0005-high-value-model-capacity-isolation.md)
5. [`docs/tasks/reviewer-verdict-routing-implementation-report.md`](docs/tasks/reviewer-verdict-routing-implementation-report.md)
6. [`docs/tasks/windows-verification-env-gate-v2-implementation-report.md`](docs/tasks/windows-verification-env-gate-v2-implementation-report.md)
7. [`docs/tasks/windows-python312-utf8-closeout-v7-implementation-report.md`](docs/tasks/windows-python312-utf8-closeout-v7-implementation-report.md)
8. [`docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md`](docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md)

AI Memory can provide long-term/private background to an Architect or Planner. It does not override
these versioned files, and a fresh Executor must not need it when a TaskCard is complete.

## Repository and Branch Truth

- The only long-lived product branch is `main`. Short-lived feature and proof branches are deleted
  after terminal merge, closeout, or evidence capture. The closeout policy is in
  [`docs/reviews/2026-08-03-single-main-branch-closeout.md`](docs/reviews/2026-08-03-single-main-branch-closeout.md).
- Historical outcomes are retained only when they remain useful in versioned reports, tests, or
  `main` history. Tags are reserved for named product releases and milestones, not execution or
  proof evidence.
- The obsolete postflight self-test worktree registration was retired after its Git link became
  invalid. Its recorded commit is reachable from `main`; the old directory is not repository truth.
- Historical Agent Bus events 49–52 and 73–80 are evidence only: never read payloads, consume, ACK,
  or requeue them.
- The 2026-07-26 semantic-loop branch refs were retired after their exact tips were recorded. V1–v4
  are failed or intermediate evidence; v5 is the accepted executor result documented in the live
  semantic-loop implementation report. Do not recreate branches for the retired attempts.

Refresh refs before relying on this snapshot.

## What Landed Since the 2026-07-18 Positioning Audit

1. **Fail-closed reviewer verdict routing (PR #12, merge `7b1bb29`).** The reviewer placeholder is
   gone. The trusted runner validates a structured `awf-review-report` block with a closed verdict set
   (`PASS` / `REQUEST_CHANGES` / `BLOCKED`), embeds the complete normalized report (≤16 KiB) in
   every verdict event, routes `decision:awf-ready` / `task:awf-rework` / `decision:awf-blocked`
   respectively, and fails the handler (no ACK) on any invalid report or failed send. Verification
   at the PR #12 head recorded 123 focused and 160 full-suite tests. See the implementation report
   for the exact event/payload contract and routing matrix.
2. **Default-locale verification boundary (PR #13, merge `f5f6a37`).** `verification_env()` strips
   `PYTHONUTF8` for trusted postflight commands only; model/tool child environments are unchanged.
   A fresh Windows Python 3.12 checkout proved the real child boundary with 4 focused tests; the
   local integration suite recorded 162 passed. Complete Windows portability remained downstream.
3. **Windows Python 3.12 UTF-8 portability closeout (PR #14, squash `db5a45c`).** Explicit
   `encoding="utf-8"` on resource reads, UTF-8-hygienic CLI test environments, and a Windows-valid
   staged secret-scan regression closed the downstream portability gate. Fresh Windows evidence:
   162 passed, 1 expected platform skip, Ruff/format/resource validation clean, trusted postflight
   passed, and push plus remote SHA verified. The accepted executor commit remains preserved at
   `archive/event-80-windows-python312-utf8-closeout-v7-success`.
4. **Reviewer compatibility and live semantic-loop closeout.** The operations runner now keeps
   model-side Git publishing credentialless, drives Codex review through a read-only prompt with
   the canonical ReviewReport contract, and passes only validated deterministic failures into
   rework. A fresh
   isolated Mac architect → Windows coder → Mac reviewer → architect run completed on events
   94–96: coder postflight, commit/push, and remote SHA `451cc60` matched; reviewer emitted a
   structured `PASS`; architect consumed the verdict; every event was ACKed with retry count zero
   and no last error. Agent Bus remained an unchanged opaque transport.
5. **Dispatch push fail-closed gate.** `awf_dispatch.py` exits before Agent Bus delivery when
   its TaskCard branch push fails. A regression test proves the bus command is not invoked on that
   path; explicit `--no-push` remains a local-only mode.
6. **Windows ACL readiness accuracy.** The handoff check strips the exact echoed credential-file
   path before parsing ACE principals, so `C:\Users\...` does not masquerade as a broad `Users`
   grant. ACL read/parse uncertainty, inherited ACEs, and any principal other than the current user
   remain blocking failures.
7. **Private Bus proxy bypass.** Handoff, listener, and dispatch subprocesses add the configured
   Agent Bus host to both `NO_PROXY` variants without discarding existing exclusions. This prevents
   Windows proxy settings from turning a healthy Tailscale Bus route into HTTP 502/SSE retries.
8. **Isolated model Git boundary.** A real downstream run proved prompt-only Git ownership was
   insufficient when OpenCode committed and pushed before trusted postflight. OpenCode coder and
   fallback reviewer processes now run in fresh event-scoped clones with no remotes. Their normal
   Git path is read-only, credential channels and source-checkout path variables are removed, and
   protocol denial plus hooks remain defense in depth. The runner verifies the isolated refs and
   refreshed remote task ref, runs frozen postflight in the isolated clone, imports an exact tree
   delta, and alone commits/pushes with git-native Lore trailers. This closes the observed ordinary
   Git-write class. Model inference keeps credential-free proxy settings, but embedded proxy
   username/password values fail before model launch. Configured report artifacts are imported even
   from ignored directories, while reviewer evidence must be tracked by the dispatched commit.
   Hostile same-user arbitrary code still requires OS/network isolation.

## Repository Truth Consistency

Repository truth consistency is the first completion metric. Every implementation PR must update
the affected current-state sections in this file and reconcile `README.md` and `ROADMAP.md` in the
same PR. Historical reviews, frozen TaskCards, and implementation reports remain point-in-time
evidence and are not rewritten when current status advances.

## Proven and Missing

Proven with deterministic tests and live operations evidence: exact checkout, trusted
model-process and postflight gates, allowed-path/secret/diff checks, commit/push plus remote-SHA
proof, durable handler evidence, Windows handler-return/ACK, semantic verdict validation and
fail-closed routing, fail-closed dispatch when a TaskCard branch cannot be pushed, Windows Python
3.12 default-locale portability, path-safe Windows ACL validation, private-Bus proxy bypass,
event-scoped no-remote OpenCode workspaces with trusted delta import, and one fresh uninterrupted
cross-machine `PASS` route
through architect consumption and ACK.

PR #32's exact PR-number and control-plane compatibility fixes and the subsequent recovery,
configuration, native-dispatch, executor, Preflight, and renderer changes are merged with green
cross-platform CI. Same-delivery coder/reviewer recovery is proven without repeating either
completed model subprocess. Fast Preflight is read-only; Deep Preflight is a disposable no-model
transport proof and cannot authorize a historical delivery.

The original downstream stop is closed by a wholly fresh run. The accepted three-card evidence is
versioned in the acceptance report; downstream TaskCards, reports, ledgers, and product assertions
remain owned by the Dousansi repository. A comparable high-value-model-led baseline is still
missing and must not be reconstructed from estimates.

## Dousansi Dogfood Closeout Boundary

The earlier stopped run remains historical evidence. Do not inspect, ACK, requeue, or redispatch its
preserved events. Its replacement was a fresh v3 run; that run is now terminal and must not be used
as a source of new work.

The accepted run also closes the former Windows session-loss blocker. The managed coder listener
survived a complete SSH session A exit and was verified from a fresh session B with exact manager,
PID, launch identity, lease, queue connection, consumption, crash recovery, and clean local stop.
No PowerShell, WinSW, service password, or Agent Bus supervisor behavior was introduced.

These are downstream readiness and operations gates. They do not justify an Agent Host, generic
engine, Agent Bus protocol change, or provider-contract migration before dogfood.

## Next Gates (in order)

1. **Keep `v0.3.0` boring.** Fix only evidence-backed reliability or compatibility failures; do not
   reopen the core/runtime boundary because the first product gate passed.
2. **Run a second downstream phase.** Use another bounded multi-card phase before generalizing
   scheduler, provider, or continuation behavior.
3. **Instrument the comparison.** Record phase-level planning/milestone high-value calls and a
   comparable prior baseline prospectively; do not estimate the missing first-run counts.
4. **Exercise one deterministic rework path.** The first phase needed no `REQUEST_CHANGES`; a future
   live phase should prove that path without forcing a product change merely to create evidence.
5. **Reassess abstraction only from repetition.** Broaden adapters only when another supported host,
   provider, or repeated operator burden supplies concrete evidence.

## Next-Agent Start Sequence

Begin with `git status --short --branch`, a fresh fetch, and a live check of both repositories'
default branches and CI. Read this handoff, `ROADMAP.md`, the three-card acceptance report, and the
runtime lifecycle/Preflight architecture documents. Run no historical event command. Keep changes
on feature branches with Lore-formatted commits. There is no retained business delivery to resume;
the next product action requires a newly approved downstream phase and fresh repository truth.

## Standing Rules

- `main` is the only long-lived branch. Use a short-lived feature branch + PR + CI for each change,
  then delete the feature branch immediately after terminal closeout; never push to `main` directly.
- Implementation and repository-truth documentation ship together; no code-first/docs-later
  closeout is complete.
- TaskCards are frozen after commit; executors touch only Allowed paths; postflight contract stays
  authoritative.
- Token values never appear in argv, logs, chat, or git.
- `Use first, abstract second`: no Agent Host, plugin SDK, generic engine, or new dependency enters
  the core from operations work.
