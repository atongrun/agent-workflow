# RTS-043 Phase 4A Evidence Adjudication and Closeout

## Result

`PASS`. Independent Gate Review found the Phase 4A evidence complete and found no semantic or
architecture conflict. Its closeout-completeness and tracked-artifact findings were repaired without
changing evidence content; final focused re-review returned `PASS` with no residual findings.

No Runtime Core, Agent Bus, lifecycle, launcher, migration, default, release, compatibility or
cleanup behavior changes in this TaskCard. No live or retained event was queried or operated.

## Phase 4A exit-criteria matrix

| Exit criterion | Owner | Evidence | Adjudication |
|---|---|---|---|
| One versioned command/result envelope has stable idempotency and no Workflow-stage authority. | Runtime v2 local transport boundary; Agent Bus remains transport owner. | RTS-040 closeout and independent Review: strict `awf.runtime-v2.command-result-envelope.v1`, stable delivery/causation identity, Stage-blind payload. | `SATISFIED` |
| Local outgoing intent and transition commit atomically where the selected Store permits; send/ACK remain external. | Logical RunStore writer owns local effect/intent; Agent Bus owns send outcome, handler success and ACK. | RTS-041 closeout/review: exact canonical envelope bytes in the accepted Store mutation; `attempting` before I/O; only `sent`/`ambiguous`; no automatic replay or ACK claim. | `SATISFIED` |
| Malformed or mismatched delivery fails before provider start. | Runtime v2 receive/preparation boundary. | RTS-040 invalid/foreign/stale/conflicting-envelope fixtures and independent Review; RTS-042-01 also failed closed at exact envelope comparison before proof child/Store, without weakening the gate. | `SATISFIED` |
| Fresh isolated Mac-to-Windows no-model request/result proves real children, handler-success ACK and `0/0 -> 0/0`. | Fresh acceptance fixture plus external Agent Bus observations. | Sole success `rts042-live-20260820-02`: new isolated identities; two real children rc=0; command/result records both `acked`; retry total zero/no error; Store sequence 8 with `attempting -> sent`; scoped queues `0/0 -> 0/0`. | `SATISFIED` |
| Production/retained events remain untouched; Agent Bus is independently versioned. | Operator boundary and Agent Bus release identity. | RTS-042 report: Bus v0.3.0 at `6ca8f281`; `-02` used fresh isolated resources; production was never queried/changed; retained `-01` roots/database/logs/evidence were confirmed present after exact `-02` cleanup. | `SATISFIED` |

## Failure and success identities

`rts042-live-20260820-01` remains terminal failed and
`EXTERNAL_BLOCKED / evidence preserved`. It can never be cited as future PASS evidence. The command
was delivered to Windows and its handler started, but exact RunSpec identity split on host-normalized
Markdown bytes; the handler denied before its bounded child and before Store initialization. It
therefore generated no result event. The Windows listener reported normal handler failure to Agent
Bus, and the Bus server atomically changed its own attempt count from zero to one under the frozen
one-attempt fixture. Neither Runtime v2 nor a later closeout wrote `retry_count=1`.

`rts042-live-20260820-02` is the only successful acceptance identity. It was independently fresh,
not a retry or replacement of `-01`. Exactly two child processes returned zero, exactly two isolated
events were ACKed, transport intent progressed `attempting -> sent`, retry/error facts stayed zero,
and scoped queues converged `0/0 -> 0/0`.

There was no retry, requeue, manual ACK, replacement delivery, identity mutation, hidden fallback,
manufactured completion or third acceptance. Later success does not rewrite, ACK, delete, repair or
reclassify the retained failed delivery.

## Repair rationale

Repair `037d514787cbf3a4b5b7852a6bae53d1b20f32ba` reads the two frozen Markdown inputs from exact
candidate Git blobs, so Mac and Windows derive identical immutable RunSpec bytes regardless of
working-tree newline conversion. Ordinary CI `32386481057` and Binary Feasibility `32386481051`
passed exact repair head. This is fixture/provenance glue only; it adds no Runtime authority,
transport contract, ACK semantic, distributed ordering rule or Frozen-boundary change.

## Scope and next gate

Changed paths are documentation/evidence only and inside the RTS-043 TaskCard allowlist. Phase 4A
is closed. The next legal action is to freeze a separate Phase 4B TaskCard. This closeout does not begin native
lifecycle implementation or authorize production/default/migration/release/destructive action.
