# P0-2 Truthful Lifecycle State Model Implementation Report

## Outcome

Node doctor and factual node status now report five orthogonal machine facts instead of the
ambiguous `status=ready`: `configured`, `installed`, `running`, `connected`, and
`dispatch_capable`. Each fact identifies its evidence source and preserves false, unknown, or
stale observations. Both human and JSON output select one legal next action.

Managed start keeps the explicit idempotent install prerequisite. Missing installation fails before
desired-state or native-manager mutation and names the exact `awf node install --profile ...`
action consistently for launchd, systemd, and Task Scheduler.

## Changed files and simplifications

- `src/agent_workflow/node.py` separates configuration readiness from bounded Bus connection,
  composes the five facts once, reuses the existing Fast/Deep implementation for dispatch truth,
  and removes the managed-status dependency on a successful start/install path.
- `src/agent_workflow/node_service.py` exposes credential-free install-record/definition truth and
  gives every manager the same missing-install prerequisite.
- `src/agent_workflow/status.py` reuses the node fact composer, maps its existing bounded queue
  observation to connection truth, and prints the same single next action before detailed facts.
- README, lifecycle architecture, readiness documentation, HANDOFF, and CHANGELOG now describe the
  v2 contract and the frozen explicit-install behavior.
- Exactly three focused Level B tests were added: one table-driven transition test, one
  missing/stale Preflight test, and one manager-parameterized install-prerequisite test. Existing
  readiness/status fixtures were extended rather than duplicated.

## Verification

Allowed local Mac checks:

- Python AST parse of every changed Python file: passed.
- `git diff --check`: passed.
- Static scope review: no Agent Bus Core, payload, ACK, recovery, compiler, rework, facade, binary,
  Phase B, or Agent Host change.
- Independent pre-publication review: APPROVE after removing an unsupported next-action command
  string and ensuring managed doctor cannot abort on native-manager prerequisites.

Per the Level B policy, local pytest, Ruff, Rust, full suite, and platform lifecycle tests were not
run. GitHub CI owns those checks; final exact-head CI and independent review evidence will be
recorded on the pull request before merge.

## Remaining risks

- `connected` is deliberately a bounded observation, not a durable session claim. A later failure
  can invalidate it before the report TTL.
- `dispatch_capable` reruns Fast against the existing Deep cache and can therefore be slower than a
  pure file snapshot; this is the cost of refusing to infer authority from stale cache contents.
- No fresh cross-machine lifecycle proof is repeated in P0-2 because native manager execution did
  not change. The installed-wheel/platform CI remains the proportional verification gate.
