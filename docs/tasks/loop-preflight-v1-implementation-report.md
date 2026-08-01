# Loop-start Preflight v1 implementation report

## Result

Implemented a versioned, fail-closed Preflight in the operations surface without changing the
stable core or Agent Bus protocol.

- Fast is read-only and separates `allow_taskcard_authoring` from
  `allow_remote_dispatch`.
- Fast requires an explicit host-local `--model-tool` selection and has no role-to-product mapping;
  every participating host verifies its chosen executable only.
- Deep is explicit, TTL/fingerprint-bound, and uses one disposable request plus one disposable
  result event through opt-in real role listeners and dedicated no-model handlers.
- Both handlers start a real child subprocess through the unified executor and publish bounded
  identity/result evidence.
- Deep accepts automatic ACK only when handler evidence matches and both role pending counts return
  from an exact zero baseline to zero. It has no manual ACK, historical read, requeue, or redispatch
  command path.
- The legacy handoff-check entry now renders the Fast layer report instead of maintaining a second
  independent probe flow.

## Changed paths

| Path | Purpose |
| --- | --- |
| `scripts/awf_preflight.py` | Fast/Deep CLI, report/decision model, disposable handlers, TTL cache |
| `scripts/awf_handoff_check.py` | Legacy human-readable compatibility entry over Fast |
| `scripts/awf_listen.py` | Explicit `--enable-preflight` registration for request/result handlers |
| `tests/test_awf_preflight.py` | Fast purity, failure, cache, Deep, handler, and listener coverage |
| `docs/runtime-preflight-architecture.md` | Boundary, trigger, proof, ACK, and listener deployment design |
| `README.md` | Operator entry point and opt-in listener route |

The frozen TaskCard is commit `e99819c`; its semantic content was not edited during implementation.

## Report contract

`awf.preflight-report.v1` includes mode/status, generated time, both allow decisions,
`required_next_action`, stable layer status/error code/duration/evidence, a credential-free
fingerprint, Deep freshness, and—after success—request/reply IDs, pending before/after, child
results, and automatic ACK evidence.

Fast never writes the proof cache. Deep writes only credential-free JSON beneath the platform
control-plane state root after an exact proof succeeds. A missing, corrupt, expired, or
fingerprint-mismatched cache cannot authorize dispatch. Cache reuse revalidates the complete Deep
evidence and an HMAC derived from the two scoped role tokens, so a minimal or locally altered JSON
record fails closed.

## Exact verification

| Command | Result |
| --- | --- |
| `python -m pytest -q tests/test_awf_preflight.py tests/test_runtime_command_boundary.py tests/test_awf_role.py` | PASS: 289 passed, 2 skipped |
| `python -m pytest -q` | PASS: 371 passed, 3 skipped |
| `ruff check .` | PASS |
| `ruff format --check .` | PASS: 96 files formatted |
| `python -m compileall -q scripts src tests` | PASS |
| `awf validate roles` | PASS: 6/6 |
| `awf validate workflows` | PASS: 4/4 |
| `awf validate examples` | PASS: 3/3 |

A real macOS zsh Fast run with an explicit Pi executable and a real Windows PowerShell Fast run
with an explicit OpenCode executable passed every layer. Both reported zero architect/coder pending
baselines and `required_next_action=run_deep_preflight`. Neither Fast run created an event, read an
event payload, or invoked a model.

## Authorized live Deep proof

After explicit remote and scoped-credential-transfer authorization, Windows used a fresh disposable
checkout at exact PR head `ae91d5a7d6d095fac4c82bc40717e2ccd1415873`. Its legacy configuration
was replaced atomically with strict role-scoped configuration after validation; the owner-only
original remains as `dispatch.env.bak`, and both transfer-temporary files were removed.

One Mac architect listener and one Windows coder listener opted into only the disposable Preflight
control routes and were stopped immediately afterward. Deep produced request event `105` and result
event `106`. Both handlers and both executor-owned child subprocesses exited successfully; both
events were automatically ACKed after handler success; architect/coder pending moved from exact
`0/0` baselines back to `0/0`. The final signed `awf.preflight-report.v1` set
`allow_remote_dispatch=true` and `required_next_action=remote_dispatch_allowed`. No historical
event was read, ACKed, requeued, or redispatched, and no model was invoked.

## Remaining risks

- Agent Bus v1 exposes no listener registry. Fast cannot prove that a remote production listener
  has opted into the control handler; Deep itself is the fail-closed proof and times out if it has
  not.
- Automatic ACK evidence is explicitly labelled inferred from matching handler evidence plus zero pending before/after because
  v1 has no read-only per-event ACK-status endpoint. No manual ACK is used to manufacture proof.
- Real macOS zsh and Windows PowerShell listener behavior is proven. Windows Git Bash remains
  covered by the executor regression/CI matrix rather than a second live Bus event.
