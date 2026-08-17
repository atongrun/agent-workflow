# Repository Handoff

> Current through the 2026-08-12 Dogfood Finding Phase A implementation follow-up, the accepted
> 2026-08-09 three-TaskCard downstream dogfood, and the 2026-08-10 `v0.3.0` release documentation.
> The minimum
> dispatch floor is the merge containing this handoff; repository files and live Git refs are
> authoritative for the exact SHA. This
> document contains no private endpoint, credential, host, personal-path, or event-payload data.

## Current Handoff State: 2026-08-15

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
