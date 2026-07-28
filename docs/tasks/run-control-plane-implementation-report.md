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
