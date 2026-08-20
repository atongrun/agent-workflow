# TaskCard: RTS-024 Product Boundary and Implementation Choice

## Task ID

runtime-v2-rts-024-decision

## Goal

Record and independently verify the owner's Phase 2 Runtime v2 decision: **PYTHON + NATIVE
LAUNCHER**. Freeze the language-neutral semantic contract only after one independent architecture
review and one separate independent adversarial review pass the same bounded decision candidate.

This TaskCard selects Python refactoring, a checksummed atomic-file RunStore with a per-invocation
journal API, and one logical Workflow transition writer without a new physical always-on
Coordinator. The native launcher is a later, bounded distribution candidate after the Phase 3
Python package/application boundary is stable. It is not a production launcher acceptance,
distribution cutover, default switch, migration, release, or authorization to modify production
Runtime behavior.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@a43b9be1e7f25f9035b9b4c5302f8c78dee527c3`
- **Task branch**: `codex/runtime-v2-rts-024-decision`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 2 / RTS-024
- **Contract**: `docs/runtime-v2-semantic-contract.md`, initially `Candidate`
- **Fault matrix**: `docs/testing/runtime-v2-fault-matrix.{md,json}`
- **Shared fixture**: `tests/fixtures/runtime_v2_shared_slice_cases.json`
- **Owner decision**: explicit 2026-08-20 acceptance selecting `PYTHON + NATIVE LAUNCHER`

RTS-020, RTS-021, RTS-022A and RTS-022B are complete comparison inputs. Their code, fixtures,
artifacts and evidence are read-only under this card.

## Frozen owner decision

### Language and distribution

- Select a Python refactor for the production Runtime v2 implementation.
- Keep current Python production as the default during Phase 3.
- Treat a native launcher plus relocatable real CPython plus the installed Agent Workflow
  application as a separate, later distribution candidate.
- Do not implement a production Rust Runtime or enter the RTS-023 Go fallback.
- Preserve the Rust shared slice, tests and RTS-022 evidence as comparison oracles until a later
  per-item closeout gate decides their archival disposition.

### Store and Workflow writer

- Select a checksummed atomic-file RunStore plus one per-invocation journal API.
- The RunStore owns immutable compiled RunSpec identity, Workflow transition authority, exact local
  handoff intent and terminal facts through one logical transition writer/API.
- The invocation journal durably distinguishes authorization, launch intent/process observation,
  result, validation/effect and recovery facts.
- Derived status is disposable and reconstructable. Unknown, stale, corrupt or conflicting state
  denies and cannot authorize.
- Do not select SQLite, introduce dual write, or preserve the legacy checkpoint/outbox/inbox graph
  as a second authority inside the new Runtime Core.
- Do not delete or migrate legacy representations in this TaskCard. Phase 6 per-item deletion gates
  require replacement fixtures and proof that no live dependency remains.

### Coordinator and external truth

- All Workflow transitions pass through one logical writer/API.
- Provider renderers and workers cannot mutate Workflow authority.
- Cross-machine results remain Agent Bus payloads and are adopted only after exact identity,
  authority, lineage and provenance revalidation.
- Add no physical always-on Coordinator, network service, leader election, distributed lock,
  daemon availability domain or Coordinator recovery model.
- Provider processes, Agent Bus, Git, GitHub, OS/native managers and filesystems remain external
  truth boundaries outside any claimed local transaction.

### Product boundary

Runtime v2 Core owns only:

- immutable RunSpec and Workflow Stage/transition authority;
- provider invocation authorization and per-invocation durable recovery;
- duplicate, idempotency and ambiguity handling;
- Artifact validation, isolated workspace and trusted local Git lifecycle;
- exact implement/review/rework lineage, bounded rework and terminal outcomes;
- read-only status, exact local stop and the intent/identity/provenance semantics needed for Agent
  Bus handoff.

Runtime v2 Core does not own Agent Bus transport, AI Memory, Agent Host, arbitrary DAGs, scheduling,
a provider/plugin registry, dashboard, SaaS control plane, agent context management, provider inner
loops, or external Git/GitHub/OS/provider truth. Codex, OpenCode and Pi remain the only evidenced
provider integrations. A renderer receives a fully bound `InvocationSpec`, understands no Workflow
Stage and cannot mutate Runtime state. No generic provider framework is authorized.

Feedback remains an optional compatibility utility outside normal `run/status/stop`, business
terminal and ACK authority. Native lifecycle retains only exact process/incarnation safety needed
by Workflow and must not expand into a Host, scheduler or plugin manager.

### CLI and support boundary

- The steady-state golden path is `awf run`, `awf status`, `awf stop`.
- Normal use does not expose internal state-root/checkpoint/outbox/inbox/profile/lease concepts.
- Status reports current facts, the first blocker, owner/cause and one legal next action without
  mutation.
- Stop is exact-bound and ambiguity is never hidden by automatic recovery.
- `init`, `doctor`, read-only debug/explain and exact-target admin/recovery commands remain explicit
  low-frequency support surfaces rather than being forced into the three normal commands.

## Evidence comparison contract

The ADR must compare the same 14-row language-neutral fixture and name unequal evidence:

- RTS-020 Python: existing production-language basis plus one disposable shared slice, one
  RunStore writer, one InvocationJournal API, 14 shared rows, one implement/review provider child,
  exact disposable Git effect, read-only status and exact local stop.
- RTS-021 Store comparison: atomic and SQLite preserve the same 14 rows and remove the same four
  local ordering windows. SQLite passes its minimum eligibility gate but adds migration, locking,
  backup/restore and platform cost without unique Workflow ownership reduction.
- RTS-022A/B Rust: zero-dependency native shared slice passes the same 14 rows on five targets and
  one bounded maintainer repair gate, but has only disposable/synthetic external-boundary evidence
  and a larger measured implementation. Its proved benefit is removal of a Python prerequisite for
  that slice, which is a distribution dimension.
- Current Python production/reference evidence additionally covers real Codex/OpenCode/Pi process
  boundaries, Agent Bus handoff/ACK separation, Git/GitHub provenance, cross-platform lifecycle and
  fresh downstream dogfood. Rust does not have equivalent production evidence.

The comparison must not turn unequal evidence into a claim that Rust is infeasible or that the
launcher candidate has already passed.

## Review and freeze protocol

1. Draft the ADR and revise the semantic contract decision/topology/product-boundary language while
   the contract remains `Candidate` and the ADR remains review-pending.
2. Obtain one independent architecture review of ownership, interfaces, evidence sufficiency,
   external truth, rollback and plan consistency.
3. Obtain one different independent adversarial review that actively challenges evidence symmetry,
   invariant preservation, hidden migration/dual-write/default claims and product-boundary drift.
4. Repair document/evidence/boundary findings within this owner decision and run focused review of
   only the affected areas. Do not ask the owner to repeat the accepted choices.
5. Only after both reviews return `PASS`, mark the semantic contract and fault matrix `Frozen`, mark
   the ADR `Accepted`, and record exact review evidence.
6. A demonstrated invariant violation or irreconcilable plan contradiction returns `PLAN_CONFLICT`;
   ordinary wording/evidence findings do not.

## Native launcher deferral contract

The ADR records a later bounded candidate, not implementation:

- Phase 3 Python package/application boundary passes first; no launcher ABI is frozen earlier.
- Candidate shape starts from the existing five-target readiness evidence: small native launcher,
  relocatable real CPython, installed Agent Workflow application, preserved
  `sys.executable`/module/script re-entry, independently distributed Agent Bus.
- Evidence must cover CPython supplier/license, launcher/runtime/app compatibility, checksum, SBOM,
  provenance, argv/UTF-8/resources/re-entry, immutable install, upgrade, program rollback without
  state rollback, size, startup and five-target behavior.
- Failure preserves the verified wheel/installed-app path, does not weaken semantics and does not
  reopen Rust automatically. A verifiable native archive/runtime bundle is sufficient; a single
  file is not mandatory.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-024-decision.md`
- `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- `docs/adr/0001-project-boundaries.md`
- `docs/adr/0002-contract-first-design.md`
- `docs/adr/0005-high-value-model-capacity-isolation.md`
- `docs/runtime-v2-semantic-contract.md`
- `docs/testing/runtime-v2-fault-matrix.md`
- `docs/testing/runtime-v2-fault-matrix.json`
- `docs/reviews/2026-08-20-runtime-v2-rts-024-architecture-review.md`
- `docs/reviews/2026-08-20-runtime-v2-rts-024-adversarial-review.md`
- `.awf/artifacts/impl-report-runtime-v2-rts-024-decision.md`
- `.awf/artifacts/review-report-runtime-v2-rts-024-decision.md`
- `docs/tasks/runtime-v2-rts-024-decision-implementation-report.md`
- `docs/plans/runtime-v2-development-plan.md`
- `HANDOFF.md`
- `ROADMAP.md`

Reviewers are read-only; the owner/lead persists their reports. Old ADR headers may be changed only
to link the accepted successor ADR. Plan, HANDOFF, ROADMAP and the implementation report are
closeout-only after review PASS.

## Out of scope

- Production `src/`, `scripts/`, schemas, CLI, facade, package metadata, state formats, provider
  adapters, lifecycle code, installer, distribution implementation or CI workflow changes.
- Edits to RTS-020/021/022 experiments, tests, fixtures, artifacts or evidence.
- SQLite adoption, database/schema migration, production Rust/Go work, launcher implementation,
  physical Coordinator, generic provider framework, Host/scheduler/DAG/dashboard/SaaS expansion.
- Dual write, silent fallback, ambiguous provider replay, state rollback, retained-event operation,
  default switch, production migration, release or destructive cleanup.
- Live/retained event, payload, delivery, queue, listener, service, state root, credential, provider,
  ACK, remote Git or GitHub business mutation.

## Acceptance criteria

- [ ] Task ID equals the branch leaf and every changed path is in the frozen writable scope.
- [ ] One ADR records the exact owner choice, same-fixture comparison, unequal evidence, product
      boundary, Store, logical writer, provider renderer and launcher deferral decisions.
- [ ] Rejected alternatives include production Rust, Go fallback, SQLite, physical Coordinator and
      immediate broad scope expansion, with evidence-based reasons rather than feasibility denial.
- [ ] Rollback/fallback keeps Python wheel/installed-app production, never rolls back state, never
      dual-writes and never silently falls back across Runtimes.
- [ ] The semantic contract preserves every normalized outcome, transition, ambiguity/no-replay,
      idempotency, lineage, provenance, ACK ordering, status and exact-stop invariant.
- [ ] The contract names the selected atomic RunStore/journal API, logical writer, narrow provider
      boundary, optional Feedback boundary and external truth ownership without prescribing a
      physical representation ABI.
- [ ] Architecture Review and separate adversarial Review both return `PASS`; repairs receive
      focused re-review from the affected Reviewer.
- [ ] Only after both PASS, ADR status is `Accepted`, semantic contract/fault matrix maturity is
      `Frozen`, and the prior ADR relationship is explicit.
- [ ] Static duplicate-key JSON validation, evidence/outcome references, changed-path audit,
      `git diff --check` and repository documentation/link checks pass.
- [ ] No production/default/migration/release/destructive/live/retained operation or representation
      deletion occurs.
- [ ] Phase 2 exit criteria are all explicitly closed and the first Phase 3 TaskCard is identified,
      not silently implemented inside this decision card.

## Verification

- Parse the fault matrix with duplicate-key rejection; verify exactly 39 unique cases and 11
  normalized outcomes, all outcome/evidence references present in the semantic contract.
- Verify the 14-row shared fixture and comparison closeouts are unchanged and their cited commits,
  CI runs, provider counts, LOC/dependency facts and evidence asymmetry are accurately represented.
- Search the ADR/contract for prohibited ownership claims, implicit Rust/Go fallback, SQLite,
  physical Coordinator, generic provider framework, default/migration/release or launcher-PASS
  language.
- Run focused documentation/link/static checks locally. Run one exact-head required repository CI
  gate for the final publication candidate; do not repeat unrelated matrices for L1 repairs.
- Persist both independent review reports and one compiled aggregate ReviewReport before freeze
  closeout.

## Required output

- one accepted product-boundary/implementation-choice ADR;
- one independently reviewed Frozen semantic contract and fault matrix;
- architecture and adversarial review reports;
- compiled ImplementationReport and aggregate ReviewReport;
- owner closeout updating plan, HANDOFF and ROADMAP with the selected Phase 3 entry.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-024-decision.md",
    "docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md",
    "docs/adr/0001-project-boundaries.md",
    "docs/adr/0002-contract-first-design.md",
    "docs/adr/0005-high-value-model-capacity-isolation.md",
    "docs/runtime-v2-semantic-contract.md",
    "docs/testing/runtime-v2-fault-matrix.md",
    "docs/testing/runtime-v2-fault-matrix.json",
    "docs/reviews/2026-08-20-runtime-v2-rts-024-architecture-review.md",
    "docs/reviews/2026-08-20-runtime-v2-rts-024-adversarial-review.md",
    ".awf/artifacts/impl-report-runtime-v2-rts-024-decision.md",
    ".awf/artifacts/review-report-runtime-v2-rts-024-decision.md",
    "docs/tasks/runtime-v2-rts-024-decision-implementation-report.md",
    "docs/plans/runtime-v2-development-plan.md",
    "HANDOFF.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "json.tool", "docs/testing/runtime-v2-fault-matrix.json"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credentials, tokens, private URLs, payloads, retained event data, or personal environment facts may appear in this decision evidence.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-024-decision.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-024-decision.md"
}
-->
