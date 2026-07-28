# Run Control Plane Implementation Report

The operations surface now persists a versioned `awf.run-ledger.v1` and bounded
`awf.context-packet.v1` outside Git checkouts. The packet binds the current
TaskCard, frozen base, branch/PR, phase/transition, evidence, prohibited
actions, and exactly one next action. A fresh session can verify it with:

```bash
python scripts/awf_control_plane.py recover --run-id <id>
```

`RunLedger.pre_invocation_gate()` atomically checks route coverage, TaskCard
stage, delivery identity/hash, durable per-stage attempt and rework budgets,
replay identity, and terminal state before OpenCode or Codex is started. Every
authorized, replay, or rejected decision is durable. Duplicate deliveries are
replay-only signals; they cannot start a second model. The ledger embeds the
packet as the atomic recovery source and mirrors it to `context-packet.json`.
The listener enables the gate and the default coder route covers both
implementation and deterministic rework.

Coder and reviewer share one run ledger. The legal `implement -> review`
transition preserves the original TaskCard/planning commit as immutable
`frozen_base` while recording the executor commit separately as
`current_stage_evidence_commit`. That evidence commit advances only with an
authorized stage transition, so reviewer continuation remains behind the
pre-invocation gate and fresh-session recovery retains both the frozen baseline
and current review evidence.

`authority-manifest.example.json` is loaded by the trusted listener and bound by
hash into every recovery packet. It permits only reversible diagnostics,
endpoint discovery, and listener restart. Credentials, destructive operations,
historical payload/ACK/requeue/redispatch, CI bypass, and trust-gate bypass
remain hard stops. Focused regression coverage is in
`tests/test_control_plane.py`, including a packet-write failure proving that no
unrecoverable sequence is authorized.

The next proof is a fresh disposable event after the PR is accepted. It must
verify recovery and every denial path without reading or mutating preserved
historical events.

## Post-Merge Review and Disposable Preflight

PR #27 merged at `f24b5fb1a4097a24b37210643dc15277f7b5dbe6`; merge-main CI passed. An
independent post-merge review found one terminal replay ordering defect: terminal denial preceded
duplicate delivery recovery. Draft PR #28 moves duplicate/reuse checks ahead of terminal denial and
adds an idempotent `finish` transition so a fresh process can persist and recover one terminal
state. Focused tests recorded 10 passed; the full suite recorded 223 passed and one expected
platform skip. Ruff, format, contract validation, independent review, and PR CI passed.

The disposable proof preflight then stopped before event creation. A fresh Windows clone matched
the frozen proof commit and was clean, but the preflight incorrectly treated a direct push to the
read-only upstream repository as the readiness test. That rejection is expected: the Windows
contributor is intended to push to a fork and open a pull request, without upstream write access.
The current trusted runner hard-codes `origin` for checkout, evidence push, and refreshed remote-SHA
verification, so it does not yet represent the intended fork/PR boundary or verify an exact PR
head. Independently, the empty transport identity could not be used on Windows without a credential
change, which the authority manifest forbids. No listener connected to the retained coder identity;
no proof or historical event was delivered, consumed, ACKed, requeued, or redispatched.

Read-only SQLite evidence recorded the complete non-payload mutable columns for retained rows 97
and 100 (`status`, timestamps, retry count, and last-error digest) and confirmed empty reviewer and
architect pending baselines. Those retained columns remained unchanged at the stop. Retained
payloads were neither selected nor hashed.
