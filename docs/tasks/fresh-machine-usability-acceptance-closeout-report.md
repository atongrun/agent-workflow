# Fresh-Machine Usability Acceptance Closeout Report

## Outcome

The separately authorized fresh-machine rerun passed. Mac, VPS, and Windows Fast Preflight each
passed all nine layers against a fully isolated disposable environment, and one Mac architect to
Windows coder Deep Preflight completed with handler-success ACK evidence and scoped queues
returning from `0/0` to `0/0`. The final no-model usability gate is `PASS`.

This result supersedes the original benchmark's current milestone status, but not its historical
evidence. PR #93 correctly recorded `BLOCKED_BEFORE_DEEP` before authority existed to provision an
independent Bus and fresh host configurations. The rerun cleared that prerequisite without
inspecting, identifying, or operating the production pending delivery.

No model was invoked. No production or retained business event was read, dispatched, ACKed,
requeued, recovered, redispatched, or reused. This acceptance does not itself authorize a new
business TaskCard.

## Exact source and isolation

- Agent Workflow was installed fresh from exact merged main commit
  `83e706b1339dd3fbac64576abf25a1b61d5840bd` on all three hosts.
- Each host used a fresh Python 3.12 virtual environment, fresh checkout, owner-only strict
  configuration, and disposable state.
- Fork dry-run used the same unpushed disposable `codex/*` local branch on each host. The branch
  carried no source change and did not exist on the remote.
- The acceptance Bus used its own process, Tailnet-only binding, SQLite database, role tokens,
  configuration, state, repositories, and listener identities.
- Production Bus identity remained distinct and active throughout the proof.

## Fast Preflight

| Host | Result | Elapsed time | Queue observation | Model boundary |
|---|---|---:|---|---|
| Mac | 9/9 layers PASS | 6.849 s | architect=0, coder=0 | architect `NOT_APPLICABLE` |
| VPS | 9/9 layers PASS | 7.559 s | architect=0, coder=0 | architect `NOT_APPLICABLE` |
| Windows | 9/9 layers PASS | 10.609 s | architect=0, coder=0 | version-only OpenCode probe |

Before Deep, the top-level Fast result correctly required `run_deep_preflight`; this was not a
layer failure. After Deep produced an HMAC-bound proof cache, Mac Fast returned top-level `PASS`
with remote dispatch allowed in 6.762 seconds.

## Cross-machine Deep Preflight

- Route: Mac architect to Windows coder.
- Result: 9/9 layers PASS in 9.303 seconds.
- Scoped queues: `0/0 -> 0/0`.
- Transport: exactly two distinct disposable control events, one request and one result.
- Execution: source and target handlers and their child subprocesses all returned success.
- ACK proof: both control records reached acknowledged state only after handler success and zero
  pending evidence.
- Payload-blind database audit: exactly two Preflight-type records; acknowledged=2,
  pending=0, delivered=0, failed=0, and non-acknowledged=0.

The evidence uses the existing handler-success plus zero-pending ACK contract and cross-checks it
against the isolated SQLite record states. It does not change transport, ACK, provenance,
delivery-hash, checkpoint, outbox, postflight, or PR-tuple semantics.

## Cleanup and production separation

- Mac listener exited normally.
- Windows session interrupt did not stop the listener child across its PowerShell/SSH boundary.
  Cleanup therefore selected only the process whose exact command line contained the unique
  acceptance scope, listener entry point, and disposable state root, then terminated that exact
  process tree.
- The VPS Bus was stopped by its exact PID plus working-directory and database binding.
- Temporary repositories, branches, virtual environments, tokens, configurations, state roots,
  SQLite database, logs, and reports were removed from all three hosts.
- Post-cleanup scope checks found no remaining Windows acceptance process, no disposable VPS Bus,
  and no remote disposable branch. The production Bus stayed active under a different PID.

## Decision

- Mark the final fresh-machine no-model usability gate complete.
- Retain `NO_GO_PRODUCTION_BINARY`; supported distribution remains the Python wheel/environment
  path used by this acceptance.
- Do not repair, inspect, or infer the identity of the untouched production pending delivery.
- A new business TaskCard may now be considered only through its own explicit product scope and
  normal contract. This report neither invents nor dispatches one.

## Remaining risk

Windows foreground listener cleanup across SSH/PowerShell remains less ergonomic than the normal
interrupt path. Exact process identity made this disposable cleanup safe, but future lifecycle
work should evaluate a first-class session-bound stop mechanism without weakening native managed
service identity gates.
