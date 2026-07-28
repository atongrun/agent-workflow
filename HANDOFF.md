# Repository Handoff

> Current through the 2026-07-29 disposable-proof preflight stop. The current `main` baseline is
> `f24b5fb`; repository files and live Git refs are authoritative. This document contains no private
> endpoint, credential, host, personal-path, or event-payload data.

## Current Handoff State: 2026-07-29

PR #27 merged at `f24b5fb1a4097a24b37210643dc15277f7b5dbe6`; merge-main CI passed.
Post-merge independent review then found that terminal-state denial ran before duplicate delivery
recovery. Draft [PR #28](https://github.com/atongrun/agent-workflow/pull/28) contains the narrow
repair plus an idempotent terminal transition command. Its local suite recorded 223 passed and one
expected platform skip; Ruff, format, contract validation, independent native review, and current
PR CI passed.

The disposable live proof did not start. A fresh Windows exact-commit checkout passed clone/SHA/
clean-tree gates, but the preflight incorrectly tested a direct push to the read-only upstream
repository. That rejection is expected for the Windows contributor workflow; Windows should publish
to its fork and open a pull request. The current trusted runner hard-codes `origin` as both the
dispatch source and evidence-push target, so the proof still needs a reviewed fork/PR-aware
publication path rather than upstream write access. The isolated transport identity also could not
be used on Windows without a credential change, which is a hard stop under the authority manifest.
No Bus event was created. Read-only fixed-column evidence established an
empty reviewer/architect baseline and retained coder events 97 and 100; every non-payload mutable
column for those retained rows was unchanged at the stop. Their payloads were not read or hashed.

The proof TaskCard is preserved on `proof/pr27-disposable-20260729-001` at `f211448`, but it has
never been dispatched. It is infrastructure-only disposable evidence, not a product TaskCard.
Do not dispatch it until the trusted runner can verify the Windows fork/PR head without granting
Windows write access to the upstream repository, and an isolation-safe transport identity is
available without inspecting or modifying retained events.

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

- The authoritative product branch is `main`. Commit `f24b5fb` merged PR #27's run control plane.
  Refresh refs before relying on this snapshot.
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

Still missing: merge or rejection of draft PR #28, a fork/PR-aware trusted publication path, the
fresh disposable end-to-end proof after isolation-safe identity readiness is explicitly restored,
recorded capacity-isolation metrics for a live run
(`docs/product-metrics.md` counters have not yet been filled), a completed non-infrastructure
downstream TaskCard, and a terminal recovery decision for the preserved interrupted run.

The versioned run ledger, bounded context packet, fresh-session recovery CLI, pre-invocation gate,
durable denial/replay decisions, and narrow authority manifest are merged from PR #27 and covered
by deterministic tests. Terminal duplicate recovery and an explicit terminal transition are on
draft PR #28. Neither branch has a successful disposable live proof.

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

1. **Review draft PR #28 without merging it automatically.** Its deterministic verification, CI,
   and independent review are green; live acceptance remains intentionally absent.
2. **Restore live readiness without upstream Windows write.** Add and review a fork/PR-aware trusted
   publication path so Windows pushes only to its fork and the reviewer verifies the exact PR head.
   Separately provide an isolation-safe transport identity without reading/copying credentials or
   connecting the shared coder listener. Do not reinterpret the current credential hard stop.
3. **Then run exactly one fresh disposable proof event.** Prove ledger persistence,
   fresh-session recovery, route/stage/attempt/rework/terminal checks, replay handling, and the
   refusal paths before model invocation. Use only a new isolated event and only reversible actions
   listed in the authority manifest. Never inspect, ACK, requeue, redispatch, or restart preserved
   historical events, and never resume Dousansi v3.
4. **Write the proof evidence and metrics update.** Record role/reason counters, ledger ID,
   context-packet checksum, gate decisions, and denial reasons without raw prompts, credentials,
   retained payloads, ACK/requeue actions, or token counts.
5. **Create the terminal-recovery decision artifact.** Decide the disposition of the preserved
   interrupted run only after the disposable proof. No new product TaskCard may begin before that
   explicit decision.

## Next-Agent Start Sequence

Begin with `git status --short --branch`, `git fetch origin`, and fresh checks of merged PR #27,
draft PR #28, and CI. Read this handoff and
`docs/tasks/run-control-plane-implementation-report.md`. Do not send the preserved proof TaskCard
until a new task explicitly authorizes resolution of both live-readiness blockers. Keep all changes
on a feature branch and use Lore-formatted commits.

## Standing Rules

- Feature branch + PR + CI for every change; never push to `main` directly.
- Implementation and repository-truth documentation ship together; no code-first/docs-later
  closeout is complete.
- TaskCards are frozen after commit; executors touch only Allowed paths; postflight contract stays
  authoritative.
- Token values never appear in argv, logs, chat, or git.
- `Use first, abstract second`: no Agent Host, plugin SDK, generic engine, or new dependency enters
  the core from operations work.
