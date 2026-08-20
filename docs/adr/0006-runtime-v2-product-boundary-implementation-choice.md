# ADR-0006: Runtime v2 Product Boundary and Implementation Choice

**Status:** Accepted
**Date:** 2026-08-20
**Decision gate:** RTS-024
**TaskCard:**
[`runtime-v2-rts-024-decision`](../tasks/runtime-v2-rts-024-decision.md)

Independent review evidence:

- [Architecture Review — PASS](../reviews/2026-08-20-runtime-v2-rts-024-architecture-review.md)
- [Adversarial Review — PASS after one focused evidence repair](../reviews/2026-08-20-runtime-v2-rts-024-adversarial-review.md)

## Context

The Runtime v2 plan deliberately deferred product boundary, implementation language, Store and
Coordinator topology until Python, storage and native-language candidates had been exercised against
the same language-neutral fault fixture. Phase 2 has now completed that comparison:

- RTS-020 proved a removable Python shared slice with one RunStore writer, one InvocationJournal
  API, exactly one implement and one review child, an exact disposable Git effect, idempotent
  terminal replay, read-only status, exact local stop and all 14 shared machine rows.
- RTS-021 ran the same 14 rows and four named local ordering windows against checksummed atomic-file
  and Python stdlib SQLite Stores. Both removed `W-AUTH`, `W-RESULT`, `W-HANDOFF` and `W-TERMINAL`
  inside one local writer boundary. SQLite passed its minimum eligibility gate but removed no unique
  Workflow ownership boundary and added schema migration, database locking, backup/restore and
  platform SQLite responsibilities.
- RTS-022A produced a zero-dependency Rust executable that passed the same 14 rows on Linux
  x86_64/arm64, Windows x86_64 and macOS x86_64/arm64 without invoking Python. Its measured
  nonblank/noncomment source numerator was 3,471 lines. The Python experiment runner measured 1,380
  lines at pre-final-review head `77c7023` and 1,396 lines at repair head `457a336`; the RTS-020
  measurement separately records 74 lines for its scripted provider fixture. This correction does
  not change the comparative size conclusion. RTS-022B then proved that a fresh maintainer could
  diagnose and repair one blinded launch-intent ambiguity/no-replay defect in one semantic attempt.

The comparison is intentionally asymmetric. Python is the existing production language and has
evidence across real Codex, OpenCode and Pi process boundaries, Agent Bus delivery/handler-success
ACK separation, trusted Git/GitHub provenance, cross-platform native lifecycle and fresh downstream
dogfood. The Rust evidence is a disposable shared slice with synthetic provider intelligence,
transport/ACK and remote provenance plus a bounded maintainer gate. It proves feasibility and a
distribution-relevant prerequisite reduction; it does not provide equivalent production-boundary
evidence. This asymmetry is evidence, not a claim that Rust is infeasible.

The owner accepted the following decision on 2026-08-20. Independent architecture and adversarial
reviews passed, including focused re-review of one LOC evidence correction, so this ADR is accepted
and the semantic contract may be promoted to `Frozen`. This acceptance authorizes no default switch,
migration, release or launcher claim.

## Decision

### 1. Implementation route: Python plus a deferred native launcher candidate

Runtime v2 will be implemented as a bounded Python refactor. Python remains the production/default
Runtime through Phase 3. The refactor must preserve the frozen language-neutral semantics while
reducing representation and interface ownership in independently reversible PRs.

A native launcher is a separate, later distribution candidate, not Runtime Core and not a second
Runtime implementation. It is evaluated only after the selected Python package/application boundary
is stable. Rust shared-slice source, tests and RTS-022 evidence remain comparison oracles until a
later per-item closeout gate decides their archival treatment; they are not an implicit fallback.

RTS-023 does not enter. No production Rust Runtime or Go fallback is authorized.

### 2. Store: checksummed atomic-file RunStore plus per-invocation journal API

The selected local authority shape is:

```text
immutable compiled RunSpec
  -> one logical RunStore transition writer/API
       -> Workflow stage, authorization, exact local handoff intent, terminal
       -> one journal API per invocation
            authorization -> launch intent/process observation -> result
            -> validation/trusted effect -> recovery facts
  -> disposable/rebuildable derived status
```

The RunStore uses checksummed atomic-file replacement and exact writer identity/locking. The
interface, not the number of files, owns Workflow authority. Each invocation journal is bound to the
immutable RunSpec, run, role, stage/attempt, input delivery, provider selection and exact workspace/
provenance identities. Unknown, missing, stale, corrupt or conflicting authority denies and cannot
authorize a provider, handoff, terminal or mutation.

The new Core does not reproduce the legacy checkpoint/outbox/inbox graph as multiple competing
authority records. It still preserves the separately observable meanings of authorization, launch,
result, Artifact validation, trusted effect, outgoing intent, input completion, handler success,
Agent Bus ACK and terminal. Existing representations are not deleted or migrated by this decision.
They remain compatibility evidence until replacement fixtures pass and Phase 6 proves no live
dependency for each deletion.

SQLite is not selected. RTS-021 showed no unique Workflow ownership or ordering-window reduction
over the atomic candidate, while SQLite adds migration, locking, backup/restore and compatibility
ownership. This is not a general rejection of databases; it is the result for this bounded local
RunStore evidence.

### 3. Coordinator: logical single writer, no physical always-on service

All Workflow transitions pass through one logical RunStore writer/API. Worker/provider renderers do
not write Workflow authority. Cross-machine results remain Agent Bus deliveries and become eligible
for adoption only after the Runtime revalidates exact current RunSpec, authorization, delivery,
lineage, workspace and provenance.

No network Coordinator service, daemon, leader election, distributed lock, new availability domain
or Coordinator recovery model is added. Provider execution, Agent Bus, Git, GitHub, OS/native
managers and another host remain external to the local writer transaction. A future independently
approved ADR may revisit physical coordination only if real cross-host evidence proves the logical
writer insufficient.

### 4. Runtime v2 Core boundary

Runtime v2 Core owns:

- immutable compiled RunSpec identity;
- Workflow Stage and transition authority;
- provider invocation authorization and per-invocation durable recovery;
- duplicate, idempotency, conflict and ambiguity/no-replay decisions;
- Artifact validation;
- isolated workspace and trusted local Git lifecycle;
- exact implement/review/rework lineage;
- `PASS`, `REQUEST_CHANGES`, bounded rework, `BLOCKED` and terminal semantics;
- read-only factual status and exact local stop;
- outgoing intent, identity and provenance semantics required for Agent Bus handoff.

Runtime v2 Core does not own:

- Agent Bus transport, retry or ACK implementation;
- AI Memory or repository history outside explicit RunSpec/TaskCard inputs;
- Agent Host, arbitrary DAGs, scheduler, provider/plugin registry, dashboard or SaaS control plane;
- agent context management or Codex/OpenCode/Pi inner loops;
- Git, GitHub, OS/native manager, provider process or filesystem external truth.

Codex, OpenCode and Pi remain the only evidenced provider integrations. Each narrow renderer accepts
a fully bound `InvocationSpec`, produces structured argv/stdin/file inputs, understands no Workflow
Stage and cannot modify Runtime state. This decision does not create a generic provider framework.

Feedback remains an optional compatibility utility outside normal `run/status/stop`. It cannot
affect business terminal or ACK authority. Its retain/externalize/delete decision is a later
per-item closeout. Native lifecycle remains only where exact process/incarnation identity is needed
for safe local operation and stop; it does not become a Host, scheduler or plugin manager, and PID,
process name, liveness or desired state alone never authorizes mutation.

This boundary narrows and amends the runtime-deferred wording in ADR-0001, ADR-0002 and ADR-0005.
Those ADRs still govern separation from Agent Bus, AI Memory, generic execution/scheduling/inner
loops and product expansion. Runtime v2 is the small method-execution authority described above,
not the broad hosted runtime or generic engine those ADRs reject.

### 5. CLI and support boundary

The steady-state golden path is:

```text
awf run
awf status
awf stop
```

Normal use does not expose state-root, checkpoint, outbox, inbox, profile snapshot or listener lease
concepts. Status remains strictly read-only and reports current facts, the first blocker, owner and
cause, plus one legal next action. Stop is exact-bound. Ambiguity is visible and never hidden by
automatic replay or guessed recovery.

`init`, `doctor`, read-only debug/explain and exact-target admin/recovery commands remain explicit
support surfaces. They are not forced into the three steady-state commands and cannot mutate through
status or bypass authority.

### 6. Native launcher deferral

After Phase 3 accepts the selected Python package/application boundary, one bounded distribution
candidate may start from the existing five-target Binary Readiness evidence:

```text
small native launcher
  -> relocatable real CPython runtime
  -> installed Agent Workflow application
  -> preserved sys.executable, module and script re-entry
```

Agent Bus remains independently distributed and versioned. The candidate must record the CPython
supplier and redistribution/license terms; launcher/runtime/application compatibility; checksum,
SBOM and provenance; exact argv, UTF-8, resources and module/script re-entry; immutable install,
upgrade and program rollback without state rollback; artifact size, startup and all five supported
target results.

A single-file executable is not required. A verifiable, installable and rollback-safe native
archive/runtime bundle is acceptable. If the bounded candidate cannot meet the gate, the verified
Python wheel/installed-application path remains supported. Runtime semantics are not weakened, Rust
is not automatically reopened and no production distribution claim is made by this ADR.

## Same-fixture comparison

| Candidate/evidence | Same 14 rows | Demonstrated ownership/prerequisite value | Evidence boundary | Decision use |
|---|---:|---|---|---|
| RTS-020 Python slice | PASS | One RunStore writer and one InvocationJournal API with no new dependency; smallest measured implementation | Disposable provider intelligence/Bus/GitHub, but production Python has separate real external-boundary and dogfood evidence | Selected implementation/reference |
| RTS-021 atomic Store | PASS | Removes all four named local ordering windows behind one logical writer without schema migration | Local disposable Store/process/Git evidence; no external transaction claim | Selected Store |
| RTS-021 SQLite Store | PASS; `SQLITE_MEETS_MINIMUM_GATE` | Removes the same four windows, no unique Workflow ownership reduction | Adds DB lock/schema/backup/restore/platform responsibilities | Eligible but rejected for this Core |
| RTS-022A/B Rust slice | PASS on five native targets; maintainer gate PASS | Removes Python prerequisite for the disposable slice; zero Cargo dependencies | No installed AWF, real provider intelligence, Bus/ACK, remote provenance, production migration or default evidence | Retained comparison oracle, not production route |

The Candidate shared fixture remains an immutable Phase 2 comparison snapshot. The Frozen semantic
contract preserves its outcomes and prohibitions; Phase 3 selected-boundary tests must consume or
derive an explicitly bound Frozen fixture without rewriting the historical Candidate evidence.

## Rejected alternatives

### Production Rust Runtime

Rejected for the current route, not declared infeasible. Rust proved native distribution value and
bounded maintainability, but a production Rust Runtime would duplicate the full semantics and
existing real external-boundary integrations to solve a distribution problem. The Python slice met
the same semantics with materially smaller implementation ownership, and Python already owns the
production evidence base. Preserve Rust evidence instead of expanding it.

### Go fallback

Rejected because RTS-023 entry is conditional on a Rust-specific stop with remaining native value.
RTS-022B passed, and the owner selected Python plus a later launcher candidate. Starting Go would add
another Runtime implementation without a new demonstrated ownership question.

### SQLite

Rejected because it removed the same four local windows as the atomic candidate and introduced
migration, locking, backup/restore and platform responsibilities without unique Workflow ownership
reduction. Its passing experiment remains valid evidence.

### Physical always-on Coordinator

Rejected because the required invariant is one logical transition writer, while the physical
service would introduce a new availability and recovery domain without evidence that it can own
provider, Bus, Git/GitHub, OS or cross-host truth atomically.

### Immediate broad scope expansion

Rejected: no arbitrary DAG, scheduler, provider/plugin registry, Host, dashboard, SaaS control
plane, generic provider framework or Feedback authority enters Runtime v2 Core. These would reopen
the product boundary before the selected local vertical slice is accepted.

## Consequences

### Positive

- Phase 3 can simplify the proven production language rather than migrate semantics and external
  integrations simultaneously.
- Workflow authority has one named RunStore writer/API and invocation recovery has one named journal
  API without conflating logically distinct facts.
- Distribution remains measurable and independently stoppable.
- Agent Bus, external truth and provider inner loops retain their owners.
- Historical representations and Rust evidence remain available for equivalence and rollback
  analysis without becoming fallbacks.

### Costs and limits

- Python remains a runtime prerequisite until a separate launcher candidate passes.
- Atomic files still require exact checksum, atomic replacement, writer identity/locking, backup and
  corruption handling; “not SQLite” does not make durability free.
- Legacy representations coexist temporarily, but the new Core must not dual-write them. Each old
  item needs a Phase 6 deletion decision after replacement evidence and live-dependency audit.
- Logical single-writer semantics do not solve cross-host adoption; unknown/foreign local recovery
  remains denied pending separate evidence.
- This ADR does not prove installed UX, Phase 4 transport/lifecycle equivalence, distribution,
  dogfood, default change, migration or release readiness.

## Rollback and fallback

- Every Phase 3 PR is independently reversible. Python production/default behavior stays in place
  until its replacement boundary passes.
- Old representations remain readable/retained until replacement fixtures pass and no live run
  depends on them. There is no dual write and no destructive cleanup under rollback.
- Program rollback never rolls back, downgrades or silently reinterprets Runtime/Bus state. Unknown
  schema or identity preserves evidence and denies.
- A failed Python refactor PR is reverted without selecting Rust/Go or weakening semantics.
- A failed native-launcher candidate preserves the wheel/installed-app route and records its
  evidence. It does not reopen Rust automatically.
- Agent Bus remains independently released and versioned; Runtime rollback cannot rewrite Bus ACK,
  pending or retained-event history.

## Review and freeze gate

This ADR is `Accepted`, and `awf.semantic-contract.v1` plus the normative fault matrix are `Frozen`,
because:

1. an independent architecture Reviewer returned `PASS` on ownership, interfaces, external truth,
   evidence, rollback and plan consistency;
2. a different independent adversarial Reviewer returned `PASS` after challenging evidence
   asymmetry, hidden dual-write/migration/default claims, invariant preservation and scope drift;
3. any repair is focused-revalidated and re-reviewed by the affected Reviewer;
4. the 39-case/11-outcome matrix remains internally consistent and no normalized outcome or
   prohibited effect is weakened.

The freeze authorizes only owner-approved Phase 3 Python TaskCards. It does not authorize a default
switch, state migration, launcher implementation, production deployment, release, retained-event
operation or destructive cleanup.

## Evidence

- [`awf.semantic-contract.v1`](../runtime-v2-semantic-contract.md)
- [`runtime-v2-fault-matrix`](../testing/runtime-v2-fault-matrix.md)
- [`RTS-010 fresh production-boundary acceptance`](../tasks/runtime-v2-rts-010-fresh-pass-acceptance-report.md)
- [`RTS-011 deterministic rework acceptance`](../tasks/runtime-v2-rts-011-deterministic-rework-acceptance-implementation-report.md)
- [`RTS-020 Python shared-slice closeout`](../tasks/runtime-v2-rts-020-python-shared-slice-implementation-report.md)
- [`RTS-021 storage comparison closeout`](../tasks/runtime-v2-rts-021-storage-comparison-implementation-report.md)
- [`RTS-022A Rust shared-slice closeout`](../tasks/runtime-v2-rts-022-rust-shared-slice-implementation-report.md)
- [`RTS-022B maintainer-gate closeout`](../tasks/runtime-v2-rts-022-maintainer-fault-gate-implementation-report.md)
- [`Runtime v2 development plan`](../plans/runtime-v2-development-plan.md)
