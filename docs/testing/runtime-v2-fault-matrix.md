# Runtime v2 Fault Matrix

Status: **Frozen**

The normative machine-readable table is
[`runtime-v2-fault-matrix.json`](runtime-v2-fault-matrix.json). It is bound to
the RTS-024 reviewed decision head `5da55fda62119eec01844e5d6c52f91d5dd187ba` and uses evidence/outcome
IDs from [`awf.semantic-contract.v1`](../runtime-v2-semantic-contract.md).

This is a current-reference fault map, not a replacement design. A safe current denial may expose
a reference correctness gap that a later gate must fix; such a case carries `reference_gap`. A
later slice may reduce a fault window only by preserving or strengthening the normalized result.

## File contract

The JSON top level contains exactly:

- `format = awf.runtime-v2-fault-matrix.v1`;
- `maturity = Frozen`;
- the exact Git `basis`;
- the semantic-contract path;
- the declared normalized `outcomes`;
- `cases`, each with a unique stable `id`, boundary, injected/observed fault, one expected outcome,
  one legal next action, prohibited actions, and one or more semantic-contract evidence IDs.

Optional `reference_gap` and `open_question` fields never weaken the expected current outcome. They
identify implementation/reconciliation evidence still required by later gates; they do not weaken
the Frozen denial or authorize guessed recovery.

## Coverage index

| Fault family | Case IDs | Required current behavior |
|---|---|---|
| Missing/corrupt/drifted run authority | `F-RUN-001`–`003` | deny before provider; preserve exact identity |
| Structured handler/process boundary | `F-PROC-001` | incompatible Bus/argv fails before SSE/provider; no shell fallback |
| Route/selection/stage/budget/rework authorization | `F-AUTH-001`–`004` | deny before provider; never bypass durable budget/stage |
| Duplicate/conflicting delivery | `F-DUP-001`–`002` | exact replay only; conflicting identity denied |
| Authorization/provider start/result ambiguity | `F-INV-000`–`004` | invoke only from proved checkpoint not-started; missing/ambiguous evidence never auto-replays |
| Artifact/postflight/import | `F-ART-001`–`003` | skip provider after durable completion; invalid Artifact cannot ACK |
| Trusted commit/fork/PR provenance | `F-GIT-001`–`003` | revalidate exact Git/GitHub facts before mutation/handoff |
| Implement-to-rework lineage | `F-REWORK-001` | exact same lineage only; drift denies before provider |
| Handoff outbox ordering | `F-OUT-001`–`004` | durable intent precedes send; ambiguous resend keeps stable identity |
| Inbox/idempotent handler completion | `F-IN-001` | identical completion returns success without repeated effects |
| Terminal and conflicting replay | `F-TERM-001`–`003` | terminal precedes inbox; identical replay idempotent; conflict preserved |
| Handler-success/Agent Bus ACK separation | `F-BUS-001`–`002` | incomplete handler cannot ACK; unavailable ACK is external unknown |
| Historical/retained delivery authority | `F-HIST-001` | no payload read or lifecycle operation without exact owner authority |
| Lifecycle/incarnation exactness | `F-LIFE-001`–`003` | missing/mismatched identity denies mutation; legacy debt stays explicit |
| Read-only status | `F-STATUS-001` | unknown stays unknown and cannot authorize recovery |
| Independent Feedback state | `F-FEED-001` | Feedback cannot rewrite business terminal/ACK; malformed reserved content still fails Artifact validation |
| Program/state rollback boundary | `F-ROLLBACK-001` | unknown compatibility requires owner decision; state is never rolled back |

## Checkpoint phase completeness

| Current checkpoint phase | Fault cases that exercise its incoming/outgoing boundary |
|---|---|
| `model_not_started` | `F-DUP-001`, `F-INV-001` |
| `model_started` | `F-INV-002`, `F-INV-003`, `F-INV-004` |
| `model_completed` | `F-ART-001`, `F-ART-002` |
| coder `postflight_completed` | `F-ART-003` |
| `model_imported` | `F-GIT-001` |
| coder `commit_created` | `F-GIT-002` |
| coder `fork_sha_verified` | `F-GIT-003` |
| `pr_tuple_verified` | `F-REWORK-001`, `F-OUT-001` |
| `outbox_prepared` | `F-OUT-002`, `F-OUT-003` |
| `outbox_sent` | `F-OUT-004`, `F-IN-001` |

The reviewer checkpoint intentionally omits coder-only postflight/commit/fork phases. ReviewReport
raw persistence/normalization/import and exact PR verification remain distinct facts even where the
phase names are shared.

## Closed Phase 1 gaps retained as regression cases

1. `F-AUTH-004`: PR #100 and RTS-011 prove the corrected rule: one authorized rework unlocks one
   additional review-stage slot while both review deliveries retain input `attempt=1`. The case now
   protects denial of an extra slot or an input attempt greater than one.
2. `F-RUN-003`: PR #97 and RTS-010 prove end-to-end compiled-contract SHA preservation. The case now
   protects denial when a handler input actually omits or drifts that immutable binding.

## Current reference gaps exposed by the matrix

1. Gate authorization consumes stage/attempt/rework budget before later provider/workspace lineage
   checks. A later pre-provider failure is not equivalent to an invoked provider, but its durable
   authorization and budget cannot be erased. Recovery must reuse exact same-delivery evidence or
   require an explicit owner decision.
2. Current code has terminal enum values `failed`, `cancelled`, and `rejected`, but the shipped
   architect handler produces only `completed` and `blocked`. Gate-level `rejected` is nonterminal.
   Later acceptance must not infer an automatic terminal transition for the unimplemented cases.

These are mapped known boundaries, not reasons to redefine PASS or weaken Candidate semantics.

## Static validation

Frozen validation must prove:

1. the JSON parses with duplicate-key rejection;
2. `format`, `maturity`, `basis`, and `contract` are exact;
3. every case ID is unique;
4. every expected outcome occurs in the top-level outcome set and semantic contract section 10;
5. every evidence ID occurs in semantic contract section 12;
6. every case has at least one prohibited action and one legal next action;
7. all current coder/reviewer checkpoint phases appear in the coverage table above.

No live fault is injected by this matrix. Phase 2 fixtures will convert the remaining rows into
executable language-neutral cases with fresh disposable identities.
