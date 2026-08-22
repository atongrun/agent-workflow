# TaskCard: Phase 5-02 Fresh Runtime v2 Single-Card Adoption

Status: Draft for independent architecture/authority review. No implementation is authorized until
this card is reviewed, repaired if needed, marked Frozen, committed and pushed.

## Task ID

phase5-02-fresh-single-card

## Goal

Make `awf run <committed-TaskCard>` execute exactly one fresh TaskCard through the selected Runtime
v2 authority path:

```text
fresh RunSpec
  -> Coder
  -> Reviewer
       -> bounded REQUEST_CHANGES -> Coder -> fresh Reviewer
       -> PASS/BLOCKED
  -> Pi Architect terminal decision
  -> exact CI/provenance gate
  -> trusted merge attempt/observation
  -> completed only after exact merge fact
```

The implementation must support the first-class topology of local Mac Pi Architect and remote
Windows OpenCode Coder+Reviewer while also allowing all three exact role bindings on one machine.
It is one-card only and must stop before next-card or milestone-loop behavior.

## Integrated prerequisites

- Agent Workflow `main@8f13b80b2fadba63a4a3e0d464220629c8e9b858`, merging accepted Phase
  5-01 PR #121.
- Agent Bus annotated tag `v0.3.1`, which peels to reviewed merge
  `c9626894be8d8036a7ef5d578fb236fd57106d21` and formally carries
  `agent-bus.listen.on-argv.v1`.
- Frozen Runtime contract/fault matrix and accepted ADR-0006.
- RTS-011 deterministic rework evidence, RTS-035 local application, RTS-040/041 envelopes/outgoing
  intent, RTS-042-02 transport acceptance and Phase 4B exact lifecycle.

## Current gaps that this card closes

- Top-level `awf run` still initializes the legacy RunLedger rather than a fresh Runtime v2 Store.
- Runtime v2 RunSpec/Store/application currently represent only Coder/Reviewer; Reviewer PASS/BLOCKED
  is immediately terminal and Pi Architect cannot authorize completion.
- Phase 4 transport is an acceptance fixture, not a production command/result worker path.
- Runtime v2 has no trusted GitHub CI/merge attempt/ambiguity/completion facts.
- Phase 5-01 machine config is local per machine; the Architect must learn remote role readiness and
  exact tool/model/profile facts without SSH ownership or dynamic discovery.

## Frozen architecture

### 1. One logical Workflow writer

- The machine running `awf run` must provide the exact Pi Architect binding and owns the sole fresh
  Runtime v2 RunStore/writer for this card.
- Remote Coder/Reviewer processes never write Workflow stage, terminal, merge or routing authority.
- No network Coordinator, database service, shared filesystem, leader election or distributed lock
  is introduced. Agent Bus transports opaque command/result/readiness envelopes only.
- A role worker owns only exact local invocation/process/result/workspace/outbox facts needed to
  prevent duplicate provider execution and return the same stable result on redelivery.

### 2. Fresh RunSpec v2 and no legacy adoption

- Introduce a versioned fresh-only RunSpec representation that binds Architect, Coder and Reviewer
  `ProviderSelection`, attempts/rework capacity, TaskCard/report paths, role routes, exact repository,
  base/branch, semantic contract and state-root identity.
- Existing Runtime v2 disposable v1 representations remain test/oracle evidence and are never read,
  migrated, rewritten or silently defaulted into the fresh path. Unknown/old format fails closed.
- No RunLedger/checkpoint/outbox/inbox write or read is permitted in the new path. Legacy `awf
  enroll/setup/dispatch/resume/status --run` remains callable only for legacy runs.
- `.awf/active-run.json` may be a small rebuildable local pointer for zero-argument status/stop; it
  is never authority and must exactly bind the RunSpec/Store before use.

### 3. Role selection and remote readiness

- Architect selection comes from the current Phase 5-01 machine binding.
- Coder/Reviewer selection comes from exact local bindings when present, otherwise the existing
  committed TaskCard `awf-reviewer-selection` block. The command envelope carries the exact expected
  tool/model and the remote handler must match it to its local profile before provider authorization.
- Tool-default remains empty at the renderer boundary; explicit opaque tool-native refs are passed
  unchanged. No provider configuration/catalog/auth mutation or silent fallback.
- Before any business command, `awf run` sends fresh bounded no-model readiness probes to every
  required remote role. Existing local roles use ordinary node doctor/lifecycle facts. Probe replies
  bind role, route, profile digest, repo, tool/model, AWF version and Agent Bus structured capability.
- Missing, timed-out, stale or mismatched remote readiness fails before business dispatch with one
  remediation. AWF never SSH-starts, installs or kills a remote role.

### 4. Stage-blind Bus command/result worker

- Add one installed structured-argv handler entry for Runtime v2 readiness, command and result
  routes; do not use legacy `--on`.
- The source writer creates the immutable command/result delivery identity and persists outgoing
  attempt-before-I/O facts. Send non-zero/timeout/exception is ambiguous and never automatically
  creates a replacement identity or repeats a provider.
- A role worker validates RunSpec, command, role/profile/selection, source commit and TaskCard/context
  before recording local launch intent. Exact duplicate command returns/resends the same persisted
  result without another provider. Same identity/different bytes denies.
- Worker records are explicitly execution-host evidence, not Workflow authority. They contain no
  next-stage or terminal decision.
- Coder results return bounded exact workspace delta, ImplementationReport and process/result facts
  to the source writer. Reviewer results return the bounded raw/normalized ReviewReport and exact
  reviewed commit/tree facts. Source revalidates all results before adopting them.
- Result handlers persist an exact source inbox before success permits Agent Bus ACK. Duplicate exact
  result is idempotent; conflict fails with no ACK.

### 5. Trusted Coder/Reviewer/rework path

- The source writer authorizes Coder before command send. After exact result adoption, trusted code
  validates postflight/allowed paths/secrets/delta, imports it, commits, pushes to the configured
  contribution fork, creates/verifies one exact PR tuple and persists those facts.
- Reviewer command binds that exact trusted commit/tree/PR tuple and cannot review prose or an
  unverified branch name.
- `REQUEST_CHANGES` uses the existing normalized deterministic feedback, exact prior implement
  lineage and one bounded rework slot. Remote Coder reuses only its exact durable prior workspace;
  rework then produces a fresh review authorization. Do not redesign RTS-011 semantics.
- `BLOCKED` routes to Architect and never becomes automatic rework.
- Same OpenCode executable/explicit model for Coder/Reviewer remains valid; role/invocation/workspace
  identities stay distinct.

### 6. Pi Architect terminal decision

- Reviewer PASS/BLOCKED becomes a handoff to a new Architect stage, not Runtime terminal.
- Extend the existing Pi Architect renderer with one explicit terminal mode. It receives a bounded
  trusted context containing TaskCard identity/criteria, Implementation/Review summaries, exact
  commit/tree/PR and current CI observation, plus BLOCKED/escalation facts where applicable. Full
  raw history/diff is not included by default.
- Pi output is persisted by trusted code and validated as the existing method-level Decision with a
  closed Phase 5-02 verdict set: `accept`, `request_changes`, `blocked`, `reject`, `escalate`.
- Only `accept` may proceed to merge. Other verdicts preserve the Architect journal/evidence and
  produce a blocked/owner decision; they do not invent rework or next work.
- Pi cannot run shell orchestration, send/ACK Bus events, mutate Git/GitHub or write Runtime state.

### 7. Trusted CI/merge/completion

- After Architect accept, trusted code freshly verifies exact upstream/head repo/ref/SHA/PR tuple and
  required CI success using the existing Git/GitHub provenance rules. No generic SCM abstraction.
- The RunStore persists a merge attempt/intent before `gh pr merge`. A non-zero, timeout, exception
  or unconfirmed result is `AMBIGUOUS_NO_REPLAY`; automatic merge retry is forbidden.
- After explicit CLI success, trusted code re-reads the PR by exact number and proves `MERGED`, exact
  prior head SHA and a valid merge commit. Only that durable observation can authorize Runtime
  terminal `completed`.
- Provider exit zero, Reviewer prose/PASS, Architect prose, branch name, PID/liveness or pending-zero
  is never completion.
- Completion facts remain typed/durable and independently readable so a later milestone loop can
  consume them; this card defines no `NEXT_TASK_CARD` or `MILESTONE_COMPLETE` loop.

### 8. Normal CLI behavior

- `awf run <TaskCard>` loads Phase 5-01 machine config, compiles fresh RunSpec, safely starts only
  exact local profiles where needed, performs readiness, initializes the new Store and runs/waits for
  one card to terminal or a truthful block.
- `awf status` remains read-only and projects the active/last fresh Store first blocker, owner,
  stage, role/model invocation evidence, PR/CI/merge/completion and one legal action. It performs no
  recovery, send, merge or provider action.
- `awf stop` records exact fresh RunStore stop for the active run. It may stop only exact local
  lifecycle resources already owned by the current machine; it never SSH-manages remote roles or
  rewrites Bus state.
- Finding remains off unless every relevant exact profile explicitly opts into Phase A. No Feedback
  dependency enters normal completion.

## Required acceptance scenarios

1. Fresh installed-wheel `awf run <committed-card>` creates one RunSpec v2/RunStore and zero legacy
   authority files.
2. Remote-readiness denial precedes business send and names exact remediation; local role readiness
   reuses Phase 5-01 lifecycle.
3. PASS: exact Coder result -> trusted import/commit/push/PR -> exact Reviewer PASS -> Pi Architect
   accept -> CI/provenance -> one merge attempt -> exact merge observation -> completed.
4. REQUEST_CHANGES: exactly one implement, one rework and two reviews; no duplicate provider on
   command/result redelivery or restart; both reviews remain distinct fresh authorizations.
5. BLOCKED/Architect non-accept preserves evidence without merge or automatic rework.
6. Same OpenCode installation/model Coder+Reviewer works with distinct role/workspace/invocation
   identities.
7. Tool-default omits model flags; explicit refs are passed exactly and never fall back.
8. Provider launch-intent crash, command send ambiguity, result conflict and merge ambiguity preserve
   facts and forbid automatic replay/mutation.
9. Legacy RunLedger/state is neither read nor changed; old active run is not adopted.
10. Finding off creates no prompt/capture/status/Feedback dependency.
11. `status` is mutation-free; `stop` is exact/idempotent and cannot authorize remote lifecycle.
12. One isolated multi-process acceptance uses separate source/coder/reviewer roots and a disposable
    Agent Bus-compatible fake or local server to prove structured argv, handler-success ACK ordering,
    stable result replay and source-only Workflow authority. No real model is required; scripted
    providers and fake GitHub are acceptable for deterministic PASS/rework/merge ambiguity rows.
13. Built wheel runs the accepted normal journey from an unrelated cwd.

## Risk and verification

This is an L3 fresh-default/adoption seam. Reuse existing Runtime Store/application/transport,
workspace/Artifact fixtures, RTS-011 rework rows, Phase 4 envelope/outgoing tests and trusted
Git/GitHub helpers. Add only focused rows for the new source/worker/Architect/merge seams. Do not
recreate the 39-case matrix, storage/Rust comparison or real three-OS lifecycle campaign.

One independent L3 architecture/authority Review is required before freeze. One different
independent L3 candidate Review is required after exact-head tests/CI. Concrete findings receive
bounded repair and focused re-review; mechanical fixes do not reopen architecture.

## Frozen implementation scope after Review PASS

- `docs/tasks/phase5-02-fresh-single-card.md`
- `src/agent_workflow/cli.py`
- `src/agent_workflow/facade.py`
- `src/agent_workflow/status.py`
- `src/agent_workflow/runtime/application.py`
- `src/agent_workflow/runtime/architect.py`
- `src/agent_workflow/runtime/contracts.py`
- `src/agent_workflow/runtime/outgoing.py`
- `src/agent_workflow/runtime/ports.py`
- `src/agent_workflow/runtime/renderers.py`
- `src/agent_workflow/runtime/single_card.py`
- `src/agent_workflow/runtime/store.py`
- `src/agent_workflow/runtime/transport.py`
- `src/agent_workflow/runtime/worker.py`
- `scripts/awf_listen.py`
- `scripts/awf_runtime_v2.py`
- `scripts/awf_taskcard.py`
- `tests/test_cli.py`
- `tests/test_facade.py`
- `tests/test_status.py`
- `tests/test_runtime_application.py`
- `tests/test_runtime_architect.py`
- `tests/test_runtime_atomic_store.py`
- `tests/test_runtime_outgoing_adapter.py`
- `tests/test_runtime_provider_renderers.py`
- `tests/test_runtime_single_card.py`
- `tests/test_runtime_transport.py`
- `tests/test_runtime_worker.py`
- `tests/test_awf_listen.py`
- `tests/test_awf_runtime_v2.py`
- `tests/verify_installed_wheel.py`
- `.awf/artifacts/impl-report-phase5-02-fresh-single-card.md`
- `.awf/artifacts/review-report-phase5-02-fresh-single-card.md`

Closeout may additionally update:

- `docs/tasks/phase5-02-fresh-single-card-report.md`
- `README.md`
- `HANDOFF.md`
- `ROADMAP.md`
- `docs/plans/runtime-v2-development-plan.md`

## Explicit exclusions

- Multi-card/recursive milestone loop, automatic next-card generation or Architect scheduling.
- Agent Host, generic scheduler/DAG, provider/model/capability registry, worker pool, GUI or remote
  supervisor.
- Agent Bus server install/redesign/protocol/database/auth changes or legacy `--on` fallback.
- Legacy migration, dual write/import, silent fallback, default switching for old runs,
  compatibility deletion or Phase 6.
- Finding Phase B, telemetry/billing, native launcher, relocatable CPython, signing/SBOM expansion.
- Real production repository merge or live business/model event as an implementation acceptance
  requirement. External mutation tests use exact disposable/fake boundaries.

## Stop conditions

- Need for network Coordinator/shared Store, generic orchestration framework, second Workflow
  authority, legacy dual write/read, automatic ambiguous retry, direct Pi mutation or Agent Bus Core
  change is `PLAN_CONFLICT`.
- A real live service/repository mutation, retained event operation, migration/default switch,
  release or multi-card behavior requires separate owner authority.
- After reviewed closeout and Draft PR creation, stop for owner review. Do not draft or execute the
  Architect-led milestone loop.

## Proposed next milestone, not implemented

```text
Architect-led milestone loop:
Goal -> Architect -> TaskCard -> single-card primitive -> Architect
     -> next TaskCard / milestone complete
```

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/cli.py",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/status.py",
    "src/agent_workflow/runtime/application.py",
    "src/agent_workflow/runtime/architect.py",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/outgoing.py",
    "src/agent_workflow/runtime/ports.py",
    "src/agent_workflow/runtime/renderers.py",
    "src/agent_workflow/runtime/single_card.py",
    "src/agent_workflow/runtime/store.py",
    "src/agent_workflow/runtime/transport.py",
    "src/agent_workflow/runtime/worker.py",
    "scripts/awf_listen.py",
    "scripts/awf_runtime_v2.py",
    "scripts/awf_taskcard.py",
    "tests/test_cli.py",
    "tests/test_facade.py",
    "tests/test_status.py",
    "tests/test_runtime_application.py",
    "tests/test_runtime_architect.py",
    "tests/test_runtime_atomic_store.py",
    "tests/test_runtime_outgoing_adapter.py",
    "tests/test_runtime_provider_renderers.py",
    "tests/test_runtime_single_card.py",
    "tests/test_runtime_transport.py",
    "tests/test_runtime_worker.py",
    "tests/test_awf_listen.py",
    "tests/test_awf_runtime_v2.py",
    "tests/verify_installed_wheel.py",
    ".awf/artifacts/impl-report-phase5-02-fresh-single-card.md",
    ".awf/artifacts/review-report-phase5-02-fresh-single-card.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_single_card.py", "tests/test_runtime_worker.py", "tests/test_awf_runtime_v2.py"],
    ["ruff", "check", "."],
    ["git", "diff", "--check"]
  ]
}
-->
