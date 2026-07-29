# Repository Handoff

> Current through the 2026-07-29 post-merge fork/PR live proof. The current `main`
> baseline is `88c7001`; repository files and live Git refs are authoritative. This document contains no private
> endpoint, credential, host, personal-path, or event-payload data.

## Current Handoff State: 2026-07-29

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

Agent Bus event handling was separately authorized. Historical coder events #97 and #100 were
classified as superseded/terminal and ACKed without executing their old product TaskCards. Proof
event #101 exposed a fixture-path failure plus an existing duplicate-without-outbox recovery gap;
it was terminally closed via the Bus-required requeue-then-ACK transition. Fresh event #102 passed
the Windows coder model isolation, postflight, fork push, fresh SHA, and PR #31 creation. Its
reviewer handoff remains unACKed and recoverable because Windows-to-Bus sends currently fail through
both the proxy and direct private route. The Mac reviewer queue remained empty.

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

- The authoritative product branch is `main`. Commit `88c7001` is the fresh baseline and includes
  merged PR #29's fork/PR-aware v3 trusted runner.
- All prior failure/evidence branches were converted to `archive/*` tags (events 49, 50, 73–80 plus
  prep/proof lanes). Do not delete, reset, re-point, or dispatch from archive tags; they are
  evidence, not product direction.
- A detached dirty postflight self-test worktree (`/private/tmp/agent-workflow-postflight-selftest`)
  is preserved for separate audit; do not clean it as part of unrelated work.
- Historical Agent Bus events 49–52 and 73–80 are evidence only: never read payloads, consume, ACK,
  or requeue them.
- The 2026-07-26 v1–v4 semantic-loop branches are failed or intermediate evidence. The v5 branch is
  the successful evidence branch at executor commit `451cc60`; preserve all five refs and their
  event-scoped evidence without reset, re-pointing, or redispatch.

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
5. **Dispatch push fail-closed gate.** `awf-dispatch.sh` now exits before Agent Bus delivery when
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

PR #27's control plane is merged and its deterministic CI passed. The fork/PR-aware v3 route is
implemented and locally testable on its current feature branch, but is not a merged or live
operational capability until current-head CI and independent security/code review pass.

Still missing: completion of the Agent Bus reviewer handoff for retained event #102, recorded
capacity-isolation metrics for the live run
(`docs/product-metrics.md` counters have not yet been filled), a completed non-infrastructure
downstream TaskCard, and a terminal recovery decision for the preserved interrupted run.

## Dousansi Dogfood Stop: Proven Gaps

The first real downstream run was intentionally stopped before product completion. Its artifacts and
safe event metadata are preserved in the downstream project's `docs/HANDOFF.md`; do not inspect,
ACK, requeue, or redispatch preserved historical events to recreate the run.

The run exposed these Workflow-owned gaps:

1. **No durable run control plane.** The method defines self-contained TaskCards and artifacts, but
   does not yet require one versioned run ledger or compact context packet that records the current
   TaskCard, frozen base, branch/PR, evidence, state transition, prohibited actions, and next action.
   Conversation context is therefore an unsafe source of truth after compaction or a new session.
2. **No pre-invocation workflow budget gate.** A transport redelivery can reach a model before the
   Workflow's one-rework policy is checked. Rework allowance, route, and terminal state must be
   atomically checked and recorded by the trusted runtime before it starts a model process.
3. **Route coverage is configuration-dependent.** The default coder listener did not automatically
   cover the rework event type. A dispatch preflight must prove that the selected event type has
   exactly one compatible active handler and that its TaskCard state permits the transition.
4. **Operational authority is not encoded.** The user had authorized reversible recovery actions,
   yet endpoint discovery and listener restart were treated as conversational escalation. A
   machine-readable authority manifest must distinguish pre-authorized diagnostics/restarts from
   destructive, credential, historical-event, and policy-bypass actions.
5. **Verification lacks proportional tiers.** The same cross-machine gates were repeatedly applied
   to infrastructure and product work. The runtime needs a small normal-path gate for ordinary
   TaskCards and a full cross-machine/security gate only for transport, trust-boundary, or first-rollout
   changes.

These are operations-surface requirements proven by dogfood. They do not justify adding a generic
Agent Host, workflow engine, or Agent Bus coupling to the stable core.

## Next Gates (in order)

1. **Finish the fork/PR proof follow-up PR.** Complete independent review, push the reviewed head,
   create the PR, and require green GitHub CI. Do not merge it in this task.
2. **Keep PR #28 separate.** It remains a narrow disposable-proof record; do not rewrite or expand
   it to carry the fork/PR change.
3. **Recover retained event #102 after Bus connectivity returns.** Deliver only its already-fixed
   PR #31 provenance to reviewer, then ACK coder only after send success. Do not restart the coder
   model or create another proof event.
4. **Write the proof evidence and metrics update.** Record role/reason counters, ledger ID,
   context-packet checksum, gate decisions, and denial reasons without raw prompts, credentials,
   retained payloads, ACK/requeue actions, or token counts.
5. **Create the terminal-recovery decision artifact.** Decide the disposition of the preserved
   interrupted run only after the disposable proof. No new product TaskCard may begin before that
   explicit decision.

## Next-Agent Start Sequence

Begin with `git status --short --branch`, a fresh fetch, and a live check of the fork/PR feature PR
and CI; do not assume this snapshot's remote state. Read this handoff,
`docs/tasks/fork-pr-trusted-runner.md`, and its implementation report. Confirm the exact
provenance tests, full verification, current-head CI, and independent review. Keep all changes on
the feature branch and use Lore-formatted commits. A live proof is a later separately authorized
gate, not part of this repair.

## Standing Rules

- Feature branch + PR + CI for every change; never push to `main` directly.
- Implementation and repository-truth documentation ship together; no code-first/docs-later
  closeout is complete.
- TaskCards are frozen after commit; executors touch only Allowed paths; postflight contract stays
  authoritative.
- Token values never appear in argv, logs, chat, or git.
- `Use first, abstract second`: no Agent Host, plugin SDK, generic engine, or new dependency enters
  the core from operations work.
