# Repository Handoff

> Current through the 2026-08-01 v1-v3 selection-integrity merge and Dousansi-bound Deep
> Preflight. The minimum dispatch floor is `e118463`; repository files and live Git refs are
> authoritative for any later documentation-only advance. This document contains no private
> endpoint, credential, host, personal-path, or event-payload data.

## Current Handoff State: 2026-08-01

The operations P0 prerequisites exposed by the stopped downstream run are merged: durable
run-ledger and context-packet gates, same-delivery checkpoint/outbox recovery, strict Python
configuration loading, native Python dispatch, one subprocess boundary, deterministic architect
terminal consumption, and Fast/Deep Preflight. PR #37 proved a fresh disposable no-model Deep
route and PR #38 extracted the existing Codex/OpenCode argv renderers without changing provider
selection, payloads, recovery, stage transitions, or ACK-sensitive lifecycle.

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
Codex/OpenCode reviewer execution paths. A generic invocation/result contract, registry, resolver,
Claude adapter, or Pi adapter is not a prerequisite and remains deferred until dogfood proves a
real need.

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

The downstream terminal decision, current v3 PhasePlan, first frozen TaskCard, and metrics template
are merged on Dousansi `main@6fd5293`. The remaining product gate is the first completed
non-infrastructure three-TaskCard dogfood with capacity-isolation metrics.

## Dousansi Dogfood Restart Boundary

The first real downstream run was intentionally stopped before product completion. Its artifacts and
safe event metadata are preserved in the downstream project's `docs/HANDOFF.md`; do not inspect,
ACK, requeue, or redispatch preserved historical events to recreate the run.

The Workflow-owned infrastructure gaps and downstream repository-truth gates are now implemented
and verified. Dousansi `main@6fd5293` records the preserved run as terminal, replaces stale v2
authority with a fresh v3 PhasePlan/TaskCard contract, assigns lower-cost normal-path coder and
reviewer roles, and carries the required metrics fields. The contribution fork exists and the
upstream-read-only/fork-write dry run passes. Current Mac and Windows Fast checks pass, and the
persistent Mac dogfood checkout has a current bound Deep proof.

Restart is therefore authorized only as a wholly fresh v3 run from refreshed downstream `main`:
new v4 task branch, frozen TaskCard commit, run ledger, context packet, delivery, and event. The
selected listener `tool` and `model` must match the hashed delivery identity exactly. Switching
agent tools requires a new version-only Fast check; rerun Deep if the report requests it or if the
runtime/transport facts materially changed.

These are downstream readiness and operations gates. They do not justify an Agent Host, generic
engine, Agent Bus protocol change, or provider-contract migration before dogfood.

## Next Gates (in order)

1. **Refresh the two exact baselines.** Require Agent Workflow to contain dispatch floor `e118463`
   and Dousansi to contain readiness floor `6fd5293`; when live refs advance, review the diff and
   record the actual exact dispatch SHAs.
2. **Recheck the selected agent tool.** Run Fast on every participating host with the actual CLI
   selected for that host; a tool change is version-only during Fast and must not invoke a model.
3. **Dispatch only a fresh v3 run.** Create a new branch, run ledger, delivery, and event from the
   refreshed downstream `origin/main`. Never resume or mutate preserved historical events.
4. **Complete three bounded downstream TaskCards.** Keep at least two normal paths free of
   high-value-model calls and record every escalation with a stable reason code.
5. **Reassess provider abstraction from evidence.** Start the next adapter phase only if the run
   exposes repeated provider-bound lifecycle friction or requires a currently unsupported provider.

## Next-Agent Start Sequence

Begin with `git status --short --branch`, a fresh fetch, and a live check of both repositories'
default branches and CI. Read this handoff, `ROADMAP.md`, `docs/runtime-preflight-architecture.md`,
the downstream terminal decision, and the current downstream PhasePlan/TaskCard. Run no historical
event command. Keep changes on feature branches with Lore-formatted commits. The next authorized
live action is a version-only Fast recheck for the agent tool actually selected tonight, followed
by the fresh v3 `DOUSANSI-DOGFOOD-001` run if the bound Deep proof remains current.

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
