# Runtime v2 Storage Comparison Experiment

This directory is a removable RTS-021 experiment. It compares one atomic-file
Store and one Python stdlib SQLite Store behind the same local Runtime v2 slice
control flow. It is not the installed `awf` command surface and it does not
select a production Store.

The intended command surface is:

```text
python experiments/runtime-v2-storage/runner.py run --store atomic|sqlite
python experiments/runtime-v2-storage/runner.py status --store atomic|sqlite
python experiments/runtime-v2-storage/runner.py stop --store atomic|sqlite
```

Fault-only maintenance commands such as backup, restore and schema migration are
experiment-local evidence helpers. They must not be treated as installed UX,
release behavior, migration machinery or cross-host recovery.

Authoritative local facts are kept in one Store payload for each candidate:
immutable RunSpec, Workflow phase, authorizations, invocation journals, exact
handoff intent, trusted Git effect identity, local stop and terminal facts.
Provider execution, Git, Bus, GitHub, native lifecycle, transport ACK and
cross-host ownership remain external observations.

The atomic candidate persists the payload as one checksummed JSON envelope with
an exact cross-process writer lock. The SQLite candidate persists the same
payload in one per-run database using explicit transactions, `mode=ro` status
reads, integrity checks, backup and offline schema migration. Derived status
files are non-authoritative; deleting or forging them cannot authorize a
provider, handoff, stop or terminal transition.
