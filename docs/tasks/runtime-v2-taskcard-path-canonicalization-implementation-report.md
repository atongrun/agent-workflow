# Runtime v2 TaskCard path canonicalization implementation report

## Result

The owner-side `awf run` packet now serializes its repository-relative TaskCard identity with
`Path.as_posix()`. The canonical delivery and the first role handler already use `/`; the ledger and
handler therefore compare the same immutable value on Windows without weakening context-drift
rejection.

## Exposed failure

The second fresh RTS-010 authority reached the trusted Windows upstream fetch successfully, then
failed before provider invocation with `run already exists with a different context packet`.
Credential-free evidence showed:

- the Windows ledger TaskCard was
  `docs\\tasks\\runtime-v2-rts-010-home-reconsideration-r2.md`;
- the canonical delivery TaskCard was
  `docs/tasks/runtime-v2-rts-010-home-reconsideration-r2.md`;
- RunLedger sequence, authorized events and attempts remained zero;
- the handler evidence contained no `model_invocation_started` record;
- the listener was stopped after the first failed delivery attempt, and the delivery was not ACKed,
  requeued, redispatched, recovered or hot-patched.

The failed authority, isolated Bus database, ledger, branch and handler evidence are retained. They
are not converted into RTS-010 PASS evidence.

## Change

- `src/agent_workflow/cli.py` uses `card.relative_to(repo).as_posix()` when building the initial
  context packet.
- `tests/test_cli.py` places the fixture TaskCard under `docs/tasks/` and asserts the exact
  `docs/tasks/card.md` packet value. The assertion is platform-neutral on POSIX and specifically
  rejects Windows separator drift in the Windows CI cell.

No route, authority binding, compiled contract, stage, budget, delivery, provider, checkpoint,
outbox, inbox, ACK or terminal behavior changed.

## Verification

- `git diff --check`: PASS.
- Python compile check for the changed source and regression module: PASS.
- GitHub ordinary CI run `32282971933`: PASS. The Ubuntu suite, Windows suite, macOS runtime
  boundary and installed-wheel jobs on Ubuntu, macOS and Windows all passed. The Windows suite is
  the cross-platform regression proof for the canonical TaskCard value.
- GitHub Binary Feasibility run `32282971981`: PASS. All five native target cells and the aggregate
  decision-input job passed.
- Independent implementation review of commit `92fb180d788174eb4123ba83cfe9396ffc0b1818`:
  `PASS` with zero findings. The reviewer confirmed that normalization occurs at the owner identity
  source, does not weaken immutable ledger comparison, and is locked by the nested-path regression.
- Final exact-publication-head CI and independent review: pending after this evidence-only update.

The Mac execution policy did not run pytest or Ruff locally. No live Bus, retained event, provider,
queue, production/default, migration or release action was performed by this implementation
TaskCard.
