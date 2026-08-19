# Runtime v2 compiled handler binding remediation report

Status: Implementation complete; exact-head GitHub CI remains the publication gate.

Date: 2026-08-20

TaskCard: `runtime-v2-handler-contract-binding-remediation`

## Result

The pre-invocation handler now preserves an existing ledger packet's exact non-empty
`run_contract_sha256` when it reconstructs the packet for a role gate. The value is read only after
`RunLedger.recover()` verifies the stored ledger/packet relationship. It is not accepted from the
delivery, environment, command line, TaskCard or provider.

Legacy handler-created ledgers remain unbound because the local default is empty and
`build_context_packet()` omits an empty compiled binding. The existing immutable identity check
continues to reject a genuinely different digest.

## Changed paths

- `scripts/awf_role.py`
- `tests/test_control_plane.py`
- this report

No schema, dependency, CLI, file layout, migration, stage transition, attempt/rework budget, route,
provider, Git, outbox, inbox, ACK, terminal or status behavior changed.

## Regression evidence

The focused regression creates the same boundary as an owner-compiled run:

1. initialize `task-task-1` with a verified authority binding and a non-empty compiled RunContract
   SHA;
2. enter the first coder role gate against the same state root;
3. require authorization;
4. recover the ledger and require the exact digest to remain unchanged.

Existing control-plane coverage still requires a different digest to fail as
`run already exists with a different context packet`. Existing legacy coder-to-reviewer coverage
continues without a compiled digest.

## Verification before publication

- Python `compileall` for the changed implementation and regression: `PASS`.
- `git diff --check`: `PASS`.
- Independent implementation Review: `PASS`, zero findings.
- Reviewer confirmed the only authority source is the verified current packet and found no stage,
  budget, route, provider, outbox or ACK semantic change.
- Local pytest and Ruff were not run because repository policy assigns them to GitHub CI on this
  Mac. Exact-head CI evidence will be added before merge.

## Live-system boundary

No Agent Bus server/listener/event, provider invocation, historical or retained delivery,
production/default switch, release, migration, credential, ACK, requeue or redispatch was used.
RTS-010's fresh business branch and isolated environments remain unstarted at the provider and
transport boundaries until this remediation is reviewed, green and merged.
