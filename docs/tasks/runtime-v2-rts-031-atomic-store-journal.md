# TaskCard: RTS-031 Checksummed Atomic RunStore and Invocation Journal

## Task ID

runtime-v2-rts-031-atomic-store-journal

## Goal

Implement the selected checksummed atomic-file `RunStore` and one scoped `InvocationJournal` API
behind the installed `agent_workflow.runtime` ports. Use one owner envelope and one exact writer
lock per run so Workflow authorization, invocation recovery facts, outgoing intent and terminal
facts have one logical writer and no competing authority files.

This is a pure disposable local-state TaskCard. It does not integrate a production handler, read or
write a legacy checkpoint/outbox/inbox/ledger, invoke a provider, send an Agent Bus event, mutate
Git/GitHub/OS truth, implement lifecycle/stop, or change a default.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@c0645310157b380c2ec14d35269765fcc223fd0b`
- **Task branch**: `codex/runtime-v2-rts-031-atomic-store-journal`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 3 / RTS-031 successor seam
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Selected ports**: `src/agent_workflow/runtime/ports.py` from RTS-030
- **Read-only comparison evidence**: RTS-020/021 reports, shared fixtures and experiment sources

RTS-030 passed with the production/default Runtime unchanged. The new package contains values and
ports only. RTS-031 may implement those ports and make the minimum port-signature refinement needed
to join local facts atomically; it cannot adopt the implementation into an existing handler.

## Frozen storage and ownership shape

### One owner envelope

Each disposable run owns exactly one checksummed JSON authority envelope beneath its selected state
root. The payload contains:

- schema version and immutable canonical `RunSpec` plus exact digest;
- run ID, exact writer ID, monotonic sequence, Workflow Stage and terminal;
- exact authorization records and bounded attempt/rework consumption;
- invocation journals embedded as separately typed facts;
- exact outgoing handoff intents.

The envelope checksum covers the complete canonical payload. JSON duplicate keys, unknown schema,
unknown fields, malformed nested facts, checksum mismatch, RunSpec drift, run/state-root/writer
identity drift, impossible ordering and conflicting replay fail closed. A status reader never
repairs, migrates, deletes, rewrites or treats a temporary/derived file as authority.

Invocation journals are logical per-invocation API views into this one envelope. RTS-031 MUST NOT
create separate journal authority files or reproduce checkpoint/outbox/inbox representations.

### Exact writer and atomic replacement

- A mutation first acquires an exact owner-created lock with exclusive create.
- An existing lock always denies mutation as `AMBIGUOUS_NO_REPLAY`; PID, age or process name cannot
  authorize stale-lock removal or takeover.
- The mutator re-reads and validates current authority only after lock acquisition.
- It writes canonical UTF-8 to a unique same-directory temporary file, flushes/fsyncs the file,
  atomically replaces the authority file, and fsyncs the containing directory where supported.
- It removes only the exact lock token it created. A conflicting/replaced lock is preserved and the
  mutation fails closed.
- A failed write/replace never promotes a partial/new authority. Temporary files are evidence only
  and are never read as current authority.

No automatic lock recovery, backup restore, schema migration, state rollback or destructive
cleanup enters this card.

### Atomic local joins and port refinement

RTS-030 exposed method names but did not freeze a Python signature ABI. RTS-031 refines the ports so
the selected atomic implementation cannot recreate four known local ordering windows:

- `RunStore.authorize(command, authorization_fact)` persists Workflow authorization and the exact
  journal authorization in one replacement.
- `RunStore.record_handoff(command, validation_effect)` persists the exact validation/trusted
  effect, outgoing intent and legal next Workflow Stage in one replacement.
- `RunStore.record_terminal(command, validation_effect)` persists the exact review validation
  effect and terminal in one replacement.
- `RunStore.journal(invocation_id)` returns the scoped journal view after authorization.
- `InvocationJournal` mutates only launch intent, process observation and provider result, and reads
  the complete journal snapshot. Authorization and validation facts remain visible in the snapshot
  but have no separate public mutation method.

This refinement preserves the Frozen facts and authority owner. It removes, rather than adds, an
escape hatch. Provider execution and external handoff/ACK remain outside the transaction boundary.

## Workflow and recovery rules in scope

1. Initialization is exact-idempotent only for the same canonical RunSpec, run, state root and
   writer ID. Fresh authority starts at `implement` with no authorization or terminal.
2. Authorization binds RunSpec, invocation, authorization, role, Stage, attempt, delivery, payload
   and InvocationSpec digest. Exact replay is idempotent; conflicting identity or exhausted capacity
   denies before provider and does not consume another attempt.
3. Implement and rework may hand off only to review through the bound review route. Review may hand
   off only to one bounded rework through the bound rework route. Handoff replay with the exact
   delivery/payload is stable; drift denies before mutation.
4. Only an authorized journal may record launch intent. Exact replay is idempotent. Conflicting
   launch identity denies. Launch intent without a trusted result is `AMBIGUOUS_NO_REPLAY`.
5. Process observation requires the exact launch authorization. Provider result requires the exact
   process identity. Missing/drifted prerequisites deny; exact repeated facts are idempotent.
6. A result without validation is recoverable `SAFE_CONTINUE`; no provider replay is authorized.
7. Completed or blocked terminal is legal only from an exact authorized review result plus exact
   validation effect. Exact terminal replay is idempotent; any conflict is `TERMINAL_CONFLICT`.
8. `failed`, `cancelled` and `rejected` terminal ownership remains outside this bounded card; the
   Store denies rather than inventing an owner transition.
9. Status reconstructs current facts, first blocker, owner/cause and one legal next action solely
   from the validated authority envelope. It performs no filesystem mutation.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-031-atomic-store-journal.md`
- `src/agent_workflow/runtime/__init__.py`
- `src/agent_workflow/runtime/ports.py`
- `src/agent_workflow/runtime/store.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_core_contracts.py`
- `tests/test_runtime_atomic_store.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-031-atomic-store-journal.md`
- `.awf/artifacts/review-report-runtime-v2-rts-031-atomic-store-journal.md`

After implementation, CI and independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-031-atomic-store-journal-implementation-report.md` and update only the
Phase 3 gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Any modification of current production `scripts/`, CLI/facade/node/status, provider adapters,
  schemas, lifecycle, CI workflows, package dependencies or existing state formats.
- Reading, converting, importing, shadowing, dual-writing or deleting RunLedger/context packet,
  checkpoint, outbox, inbox, RunEvidence, profile/process/lease, Feedback or retained state.
- Provider process execution, Artifact contents/import, workspace/Git/PR implementation, Agent Bus
  send/receive/ACK, handler success, CI/merge truth, OS manager or native process stop.
- SQLite, database migration, backup/restore, stale-lock repair, physical Coordinator, daemon,
  scheduler, generic provider framework, native launcher, default switch, production migration,
  release or destructive cleanup.
- Editing the Frozen semantic contract, ADR-0006, RTS-020/021 experiments or shared fixtures.
- Live/remote repository mutation other than this scoped branch/PR/CI workflow.

## Budgets and stop rules

- New `store.py`: at most 650 nonblank/noncomment lines.
- New focused store tests: at most 900 nonblank/noncomment lines.
- No new dependency; Runtime package remains standard-library only.
- One authority envelope and one lock representation per run; no second journal authority family.
- One implementation candidate, one TaskCard Gate Review and at most two L3 repair/re-review rounds.
- If exact atomic joins cannot be expressed without a second authority graph, provider/external
  transaction claim, cross-process lock takeover, migration or >650 implementation lines, stop with
  `PLAN_CONFLICT` rather than widening scope.

## Acceptance criteria

- [ ] Task ID equals branch leaf; all changed paths remain in frozen/closeout scope.
- [ ] One strict checksummed authority envelope contains RunSpec, run and embedded journal facts;
      no checkpoint/outbox/inbox or separate journal authority file exists.
- [ ] Exact writer lock and same-directory flush/fsync/replace semantics fail closed on contention,
      replacement failure, conflicting lock token, temporary file and stale lock.
- [ ] Initialization and re-open bind exact RunSpec/run/state-root/writer identity; missing, foreign,
      corrupt, duplicate-key, rechecksummed-drifted and newer-schema authority cannot authorize.
- [ ] Authorization + journal authorization, validation + handoff, and validation + terminal each
      commit through one lock and one envelope replacement.
- [ ] Exact duplicate authorization/launch/process/result/handoff/terminal replay is idempotent;
      conflicting reuse denies without mutation or extra budget consumption.
- [ ] Implement/review/rework legality and bounded attempts/rework are enforced before mutation.
- [ ] Launch/process/result recovery projects `SAFE_CONTINUE` or `AMBIGUOUS_NO_REPLAY` exactly and
      never authorizes guessed provider replay.
- [ ] Terminal completion/blocking is exact-idempotent; conflicting or unsupported terminal denies.
- [ ] Status is byte-for-byte read-only and returns facts, first blocker, owner/cause and one legal
      next action from validated authority only.
- [ ] Focused tests inject write/replace failure, lock contention, stale lock, checksum corruption,
      duplicate keys, identity drift, rechecksummed semantic drift and all scoped replay/order faults.
- [ ] No provider, Bus, Git/GitHub, OS manager, production state, legacy state or external mutation
      occurs in tests; all state roots and identities are disposable.
- [ ] Store/test LOC and dependency/representation budgets pass.
- [ ] Focused tests, full pytest/Ruff and ordinary Linux/Windows/macOS CI pass on candidate head.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; L3 repairs receive focused re-review.
- [ ] Closeout names the next single production integration seam without claiming Phase 3 complete,
      changing the default or authorizing migration/deletion.

## Verification

- Local Mac: AST/static checks, direct pure-value smoke, LOC/scope audit and `git diff --check` only.
- CI: focused store/core tests, full pytest/Ruff and ordinary cross-platform/installed-wheel jobs.
- Fault tests snapshot every file before status/denied operations and assert byte stability.
- Independent Review checks atomic joins, lock ownership, fail-closed parsing, immutable replay,
  no-replay ambiguity, Stage/budget semantics, read-only status and representation/dependency budget.

## Required output

- one installed standard-library atomic Store/journal implementation;
- focused deterministic storage/transition/recovery tests;
- ImplementationReport and independent ReviewReport;
- owner closeout naming exactly one later production integration seam.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-031-atomic-store-journal.md",
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/ports.py",
    "src/agent_workflow/runtime/store.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_core_contracts.py",
    "tests/test_runtime_atomic_store.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-031-atomic-store-journal.md",
    ".awf/artifacts/review-report-runtime-v2-rts-031-atomic-store-journal.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "tests/test_runtime_atomic_store.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_core_boundary.py", "tests/test_runtime_core_contracts.py", "tests/test_runtime_atomic_store.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credential, token, private URL, provider/business payload, retained-state content or personal environment fact may enter Store fixtures or reports.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-031-atomic-store-journal.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-031-atomic-store-journal.md"
}
-->
