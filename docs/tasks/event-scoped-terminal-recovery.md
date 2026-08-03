# Event-Scoped Terminal Recovery

## Intent

Recover one original Agent Bus event after its model stage completed and its durable Workflow
checkpoint crossed a trusted import boundary, without enabling listeners to requeue events and
without creating a replacement delivery.

## Boundary

The normal `awf.authority-manifest.v1` remains unchanged: listeners cannot ACK, requeue,
redispatch, inspect historical payloads, or bypass trust gates. Explicit operator recovery uses
`scripts/awf_terminal_recovery.py` as a separate, one-shot surface.

`prepare` binds an authorization to:

- one run ID and non-terminal run ledger;
- one already-authorized event ID, role, delivery ID, and payload hash;
- one source commit;
- the exact bytes and phase of the corresponding recovery checkpoint;
- the preserved model workspace, model manifest, and reviewer report hash.

Only `model_imported`, `pr_tuple_verified`, and `outbox_prepared` checkpoints qualify. The command
does not read an Agent Bus payload or invoke a model.

`requeue` reloads and revalidates all bound evidence, loads credentials through the strict Python
configuration loader, then invokes exactly `agent-bus requeue <same-event-id>`. The authorization
is single-use. A timeout, process error, or non-zero result is persisted as `ambiguous` and cannot
be retried automatically.

## Operations

```bash
python scripts/awf_terminal_recovery.py prepare \
  --state-root <state-root> \
  --run-id <run-id> \
  --event-id <event-id> \
  --role reviewer \
  --delivery-id <delivery-id> \
  --payload-sha256 <payload-sha256> \
  --source-commit <commit> \
  --reason "explicit operator recovery"

python scripts/awf_terminal_recovery.py requeue \
  --state-root <state-root> \
  --event-id <event-id> \
  --config <dispatch.env>
```

After a successful requeue, start the ordinary trusted Python listener. Checkpoint recovery, PR
provenance validation, ReviewReport parsing, outbox preparation, routing, and ACK remain owned by
the existing handler. Stop at the first failure; never create a replacement event merely because
the same-event recovery failed.

## Verification

- `python -m pytest -q tests/test_terminal_recovery.py`
- `python -m pytest -q tests/test_control_plane.py tests/test_runtime_command_boundary.py`
- `ruff check scripts/awf_terminal_recovery.py tests/test_terminal_recovery.py`
- `ruff format --check scripts/awf_terminal_recovery.py tests/test_terminal_recovery.py`
- `python -m compileall -q scripts tests`
