# TaskCard: Phase 5-02 Fresh Runtime v2 Single-Card Adoption

Status: Frozen after the owner-bounded implementation-readiness Review PASS at `b57c137`.
Implementation is authorized only within the genuine deltas and inherited-contract boundary below.

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

## Inherited canonical contract

This card adopts rather than redesigns the Frozen Runtime v2 semantics. The canonical sources are:

- Runtime v2 plan §3 non-negotiable semantic invariants;
- RTS-030 through RTS-035 for RunSpec, Store/journal, renderer, isolated workspace, trusted import,
  Artifact validation and local application composition;
- RTS-040/041 and Phase 4A for the versioned Stage-blind envelope, Store-owned outgoing intent,
  ambiguous no-replay and handler-success/transport-ACK ordering;
- RTS-011 for exact-lineage bounded rework;
- Phase 4B for exact local lifecycle ownership and stop;
- `constitution.md` §§9 and 13 for Reviewer/Decider authority and completion.

Those definitions govern persistence/replay, worker evidence versus Workflow authority, workspace
materialization/provenance, result/ACK ordering, idempotency/recovery and bounded rework. This card
does not duplicate or extend them. A contradiction exposed during implementation is repaired only as
the smallest separately identified contract delta.

## Phase 5-02 genuine delta

### 1. Fresh production adoption and ownership

- The machine running `awf run` must provide the exact Pi Architect binding and becomes the sole
  logical writer of one new fresh Runtime v2 RunStore.
- The accepted fresh-only format is `awf.runtime-v2.run-spec.v2`; no legacy RunLedger,
  checkpoint/outbox/inbox or v1 RunSpec is read, imported, dual-written or used as fallback.
- Remote workers retain only canonical per-invocation execution evidence. They never acquire
  Workflow transition, terminal, routing or merge authority.

### 2. Phase 5-01 RoleBinding compilation

- Fresh RunSpec v2 adds only the narrow role binding required by Phase 5-01: role, Agent Tool,
  `model_selection {mode, ref}`, profile identity/digest and workspace identity for Architect, Coder
  and Reviewer. It is not a provider/model registry and does not modify v1 `ProviderSelection`.
- Local bindings come from `.awf/machine.json`. When an allowed remote Coder/Reviewer selection comes
  from the committed `awf-reviewer-selection` block, empty model compiles to `tool-default` and
  nonblank model to the exact opaque explicit ref. Only the compiled v2 RoleBinding is authority.
- At rendering, tool-default omits the model override and explicit passes the exact ref. Binding drift
  denies before provider launch; explicit never falls back.

### 3. Readiness before authority

- Exact local lifecycle/readiness is reused. Missing remote roles receive one bounded no-model
  readiness probe; it must prove the configured role/profile/workspace/tool/model binding and
  `agent-bus.listen.on-argv.v1`. Version v0.3.1 is diagnostic; capability is authoritative.
- Readiness is pre-authority. Only after all bindings pass may `awf run` compile/persist RunSpec v2,
  initialize the Store and issue a business command. Failure creates neither Store nor business
  delivery and reports one manual start/refresh/re-init remediation; AWF never SSH-manages a host.

### 4. Production structured-argv handoff

- Promote the accepted Stage-blind command/result envelope and outgoing-intent adapter to one
  installed production worker/source-handler path; preserve all inherited durability and authority
  semantics without adding a Coordinator, Host, shared Store or Agent Bus change.
- Agent Bus messages retain explicit versioned type tags:
  `control:awf-runtime-v2-readiness-v1`, `control:awf-runtime-v2-readiness-result-v1`,
  `task:awf-runtime-v2-command-v1` and `result:awf-runtime-v2-result-v1`. They use only `--on-argv`;
  no untyped event or legacy `--on` fallback is allowed.
- The command carries canonical RunSpec v2 plus the exact stage authorization and source identity
  needed by the inherited workspace/provenance contract. Coder returns its bounded result for
  trusted source import/commit/push/PR; Reviewer receives and reports on that exact trusted head.

### 5. Pi Architect terminal delta

- Reviewer PASS or BLOCKED now authorizes one local `ARCHITECT` stage rather than becoming terminal.
  The existing journal/no-replay contract applies to that invocation.
- Extend the existing Pi renderer with a narrow terminal mode containing bounded trusted TaskCard,
  Artifact, review, CI and exact PR/provenance facts, not raw implementation history.
- Parse the existing Decision template and verdicts only. `approve` is the sole mapping that may
  enter merge, and Reviewer BLOCKED can never merge. Other decisions preserve a typed non-merge
  outcome; they do not create rework, next-card or shell/Git/Bus authority for Pi.

### 6. Trusted merge/completion delta

- After Reviewer PASS, exact-head required CI and Architect approve, reuse the existing trusted
  Git/GitHub provenance machinery for one deterministic merge attempt.
- Persist merge intent before external mutation. Ambiguous outcome is no-replay. Completion is
  recorded only after exact PR/head/method-specific merged observation; no `--auto`, automatic branch
  deletion or generic SCM abstraction is introduced.
- The typed completed-card fact remains independently readable for a later milestone loop, but this
  card defines no next-card behavior.

### 7. Normal CLI behavior

- `awf run <TaskCard>` performs the ordered readiness, fresh compilation, one-card dispatch and
  trusted progress above, starting only exact local profiles where existing lifecycle permits.
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
6. Architect stage records authorization/launch/result/Decision exactly once; launch/result crash or
   uncertainty cannot replay Pi, and an invalid/foreign Decision is denied. Reviewer BLOCKED cannot
   merge under any Pi verdict.
7. Same OpenCode installation/model Coder+Reviewer works with distinct role/workspace/invocation
   identities.
8. Tool-default omits model flags; explicit refs are passed exactly and never fall back. RoleBinding
   mode/ref, tool, profile or workspace drift is denied before provider launch.
9. Provider launch-intent crash, command send ambiguity, result conflict and merge ambiguity preserve
   facts and forbid automatic replay/mutation.
10. Worker result-send ambiguity leaves the command unACKed and redelivery resends only the exact
    immutable result without provider replay.
11. Source result-handler crash after inbox/adoption resumes from the same durable result and ACKs
    only after exact revalidation; no worker gains Workflow authority.
12. Legacy RunLedger/state is neither read nor changed; old active run is not adopted. Invalid fresh
    pointers never cause a legacy scan.
13. Finding off creates no prompt/capture/status/Feedback dependency.
14. `status` is mutation-free; `stop` is exact/idempotent and cannot authorize remote lifecycle.
15. One isolated multi-process acceptance uses separate source/coder/reviewer roots and a disposable
    Agent Bus-compatible fake or local server to prove structured argv, handler-success ACK ordering,
    stable result replay and source-only Workflow authority. No real model is required; scripted
    providers and fake GitHub are acceptable for deterministic PASS/rework/merge ambiguity rows.
16. Built wheel runs the accepted normal journey from an unrelated cwd.

## Risk and verification

This is an L3 fresh-default/adoption seam. Reuse existing Runtime Store/application/transport,
workspace/Artifact fixtures, RTS-011 rework rows, Phase 4 envelope/outgoing tests and trusted
Git/GitHub helpers. Add only focused rows for the new production adoption, RoleBinding, Architect,
readiness, CLI/pointer and merge/completion deltas. Reuse existing fault fixtures for inherited
protocol behavior; do not recreate the 39-case matrix, storage/Rust comparison or real three-OS
lifecycle campaign.

One bounded independent implementation-readiness Review is required before freeze. It may block only
on a canonical-contract violation, an uncovered genuine Phase 5-02 delta, a defect that directly
prevents execution/recovery/acceptance, or scope exceeding one card. It must not reopen inherited
protocol semantics for theoretical improvement. One different independent L3 candidate Review is
required after exact-head tests/CI. Concrete implementation findings receive bounded repair and
focused re-review; mechanical fixes do not reopen architecture.

## Frozen implementation scope after Review PASS

- `docs/tasks/phase5-02-fresh-single-card.md`
- `src/agent_workflow/cli.py`
- `src/agent_workflow/facade.py`
- `src/agent_workflow/node.py`
- `src/agent_workflow/status.py`
- `src/agent_workflow/runtime/application.py`
- `src/agent_workflow/runtime/__init__.py`
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
- `tests/test_node.py`
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
    "src/agent_workflow/node.py",
    "src/agent_workflow/status.py",
    "src/agent_workflow/runtime/application.py",
    "src/agent_workflow/runtime/__init__.py",
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
    "tests/test_node.py",
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
