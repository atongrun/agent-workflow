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

A real local Fast run from macOS zsh emitted valid `awf.preflight-report.v1`, detected the unified
executor/config/Git/control-plane layers as authoring-ready, and correctly denied remote dispatch
for the current live environment. It did not create an event or read an event payload. The live
environment's remote-only failures were reported as stable codes without endpoints, tokens,
private paths, or raw output.

## Deliberate verification boundary

No live Deep event was sent. The frozen TaskCard prohibits live proof events during implementation,
and the user explicitly reserved merge/remote lifecycle authority for the parent session. Deep was
verified with fake Bus boundaries, direct handler/result tests, opt-in listener argv tests, pending
baseline/identity/TTL failure tests, and the repository-wide executor AST gate.

The next real remote TaskCard should restart the participating listeners with
`--enable-preflight`, run Fast for remote-dispatch intent, then perform one separately authorized
Deep proof. A non-default source `--state-root` must match its listener.

## Remaining risks

- Agent Bus v1 exposes no listener registry. Fast cannot prove that a remote production listener
  has opted into the control handler; Deep itself is the fail-closed proof and times out if it has
  not.
- Automatic ACK evidence is explicitly labelled inferred from matching handler evidence plus zero pending before/after because
  v1 has no read-only per-event ACK-status endpoint. No manual ACK is used to manufacture proof.
- Real PowerShell/Git Bash/macOS listener behavior remains CI/runtime-matrix work after the branch is
  published; local verification covered macOS zsh and the cross-platform executor regression suite.
