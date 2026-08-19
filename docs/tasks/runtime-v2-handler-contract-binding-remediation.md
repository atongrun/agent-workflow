# TaskCard: Preserve compiled RunContract identity at the handler gate

Status: Frozen Phase 1 remediation required before RTS-010 provider execution.

## Task ID

`runtime-v2-handler-contract-binding-remediation`

## Context

RTS-001 gap CG-2 records that `awf run` initializes the local RunLedger with the compiled
`run_contract_sha256`, while `pre_invocation_gate()` reconstructs a packet without copying that
immutable field. On a host that owns both the initialized run and a later role handler, the first
handler would fail closed as a different context packet before provider start. RTS-010 uses a Mac
reviewer and deterministic architect terminal consumer on the owner run state root, so this known
entry fault must be repaired and independently verified before any live model invocation.

## Required behavior

1. When a RunLedger already exists, a role handler must preserve its exact non-empty compiled
   `run_contract_sha256` while reconstructing the pre-invocation packet.
2. The handler must obtain the value only from the verified existing ledger packet. It must not
   accept a payload, environment variable or CLI override as a new authority source.
3. Legacy handler-created ledgers with no compiled binding must remain compatible and unbound; this
   card must not invent or backfill a digest.
4. A genuinely different compiled binding must remain an immutable context conflict and fail
   closed.
5. Do not change stage, attempt, rework, duplicate, route, terminal, state-root, provider, outbox,
   inbox, ACK or status semantics.

## Allowed paths

1. `scripts/awf_role.py`
2. `tests/test_control_plane.py`
3. `docs/tasks/runtime-v2-handler-contract-binding-remediation-implementation-report.md`
4. `docs/plans/runtime-v2-development-plan.md`
5. `HANDOFF.md`
6. `ROADMAP.md`

The frozen TaskCard itself is owner intent and must not be modified after this commit.

## Acceptance criteria

- [ ] A regression initializes a ledger with a non-empty compiled RunContract SHA and proves the
      first role gate is authorized without dropping or changing that SHA.
- [ ] Existing tests continue to prove a different SHA is rejected as context drift.
- [ ] Legacy no-binding behavior is unchanged.
- [ ] The fix is a minimal propagation repair with no schema, dependency, CLI or state migration.
- [ ] Relevant CI and the full repository CI pass on the exact head.
- [ ] An independent Reviewer returns `PASS` with no weakened invariant or hidden authority source.
- [ ] The implementation report records that no Agent Bus event, provider, production/default,
      release, migration or historical delivery was used.

## Verification

```bash
pytest -q tests/test_control_plane.py tests/test_cli.py
ruff check scripts/awf_role.py tests/test_control_plane.py
ruff format --check scripts/awf_role.py tests/test_control_plane.py
git diff --check
```

Full cross-platform CI remains the authoritative Mac-policy validation surface.
