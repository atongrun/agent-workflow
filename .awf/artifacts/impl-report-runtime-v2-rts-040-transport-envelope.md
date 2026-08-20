# ImplementationReport: RTS-040 Stage-Blind Command/Result Envelope

## Outcome

Implemented one installed `awf.runtime-v2.command-result-envelope.v1` family with immutable command
and result values, strict canonical JSON decoding, stable `awfv2:` delivery/idempotency identity and
exact result causation. Added one no-I/O `LocalTransportBoundary` that validates transport identity
before delegating once to the accepted `LocalRuntimeApplication`.

The candidate uses only disposable no-model fixtures. Production handlers, Agent Bus, retained
deliveries, legacy authority, defaults, migration, native lifecycle, launcher and release paths are
unchanged.

## Exact boundary and ordering

- Top-level envelope identity binds kind, run/task/RunSpec, source and target roles, route, source
  invocation/authorization, target invocation, canonical payload hash and result causation.
- Command/result bytes must be exact canonical UTF-8 JSON. Duplicate/unknown/missing fields,
  noncanonical bytes, floats/non-finite values, bad controls, excessive size/depth/node count,
  unsupported role pairs and every recomputed identity mismatch deny.
- Payload stays opaque to the codec. No top-level Stage, attempt, rework, terminal, Store,
  checkpoint/outbox/inbox/ACK or provider-launch field exists.
- The receive boundary checks the supplied RunSpec/local request before application entry. A result
  additionally joins the exact read-only Store pending-handoff identity; the boundary has no Store
  mutation method and no external I/O surface.
- After Artifact/workspace/provider validation, the local application computes the exact result
  envelope identity before atomically recording its existing handoff or terminal fact. Result
  preparation can succeed only when the recomputed envelope matches that Store-owned identity/hash.
- Identical redelivery continues through existing Store idempotency. A durable launch intent without
  result remains `AMBIGUOUS_NO_REPLAY`; the envelope never implies send, handler success or ACK.

## Files and budgets

- `src/agent_workflow/runtime/transport.py`: 478 nonblank/noncomment lines (budget: 480).
- `src/agent_workflow/runtime/application.py`: narrow result-identity/rework-binding refinement,
  under the 100-line net budget.
- `src/agent_workflow/runtime/__init__.py`: explicit installed exports only.
- `tests/test_runtime_transport.py` plus focused application/Core refinements: under the 900-line
  net test budget.
- No dependency, persistent file family, alternate Store/writer, adapter registry or background
  component was added.

## Focused evidence

- `python3 -m compileall -q src/agent_workflow/runtime tests/test_runtime_transport.py
  tests/test_runtime_application.py tests/test_runtime_core_boundary.py
  tests/test_runtime_command_boundary.py` — PASS.
- Direct disposable Git/scripted-provider smoke — PASS for implement/review/PASS, BLOCKED and
  REQUEST_CHANGES/rework/second-review/PASS through the transport receive boundary.
- Direct static package/export/no-I/O boundary checks — PASS.
- `git diff --check` — PASS.
- Payload hashing matches the current `awf_delivery.py` canonical payload oracle while the new
  delivery identity is intentionally version-distinct.
- Frozen-TaskCard baseline CI at `9cb16cf`: ordinary CI PASS. Binary Feasibility had one macOS x64
  external GitHub API `403 rate limit exceeded`; every other binary job passed, and the immediately
  preceding TaskCard baseline at `a1d5f45` passed the full Binary matrix.

Exact-head full pytest/Ruff/installed-wheel/cross-platform and Binary Feasibility evidence is the
next candidate gate; local macOS intentionally did not install or run pytest/Ruff.

## Fault coverage

- per-field run/task/spec/role/route/source/target/payload/delivery drift;
- duplicate, malformed, noncanonical, deep, oversized and non-integer JSON;
- payload and causation mutation changing delivery identity;
- valid-but-foreign result rejected against byte-stable Store authority before provider;
- exact PASS/BLOCKED and bounded rework result chains;
- exact command redelivery after process observation with no result, proving one provider start;
- static prohibition of network/HTTP/Agent Bus/process launch/send/ACK/authority mutation surfaces.

## Preserved limitations and next gate

This card does not persist a complete external send record, implement a Bus adapter, observe ACK or
claim cross-machine acceptance. The current Store handoff/terminal identity and hash are sufficient
for the local envelope gate, but full outgoing payload reconstruction and real transport adoption
remain a separately frozen Phase 4A adapter gate. That gate must use fresh isolated no-model events
and must not touch production/retained deliveries.
