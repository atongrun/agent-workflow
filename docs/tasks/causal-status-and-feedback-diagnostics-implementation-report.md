# Implementation Report: P1-1 Causal Status and Feedback Diagnostics

## Result

Run-aware node status now turns existing lifecycle, RunLedger and exact delivery-checkpoint facts
into one payload-blind causal explanation. It reports the current stage/attempt, first observed
blocker, owner/cause, checkpoint-proven model invocation and one legal next action. Feedback
capture/outbox/flush state is a separate top-level component and cannot rewrite business terminal
or ACK state.

## Changed files

1. `docs/tasks/causal-status-and-feedback-diagnostics.md`
2. `docs/tasks/causal-status-and-feedback-diagnostics-implementation-report.md`
3. `src/agent_workflow/status.py`
4. `src/agent_workflow/node.py`
5. `src/agent_workflow/cli.py`
6. `tests/test_status.py`
7. `tests/test_node.py`
8. `README.md`
9. `CHANGELOG.md`
10. `ROADMAP.md`
11. `HANDOFF.md`
12. `docs/runtime-execution-architecture.md`

## Simplifications and behavior

- Reused `lifecycle_facts()`, `RunLedger.recover()`, existing checkpoint files and
  `feedback_status()` instead of adding a status database or controller.
- Bound model-invocation evidence to checkpoint filenames derived from authorized delivery IDs in
  the requested run. A same-branch checkpoint from another run is not considered.
- Reduced event output to count and selected event metadata. Payload, delivery ID and payload hash
  values are never projected; status reports only whether a hash was observed.
- Kept `awf.node-status.v1` additive and made `--explain` a human-rendering option. JSON and listener
  health exit semantics are unchanged.
- Feedback status reads local outbox records only. It does not load Bus credentials or call flush,
  ingest, queue or handler paths.

## Focused regressions

- Lifecycle-not-runnable identifies the installed boundary, node-lifecycle owner, unknown model
  invocation and the existing install action.
- A synthetic rejected pre-model event reports the control-plane blocker and no model invocation,
  excludes payload/delivery/hash values, and fails if lifecycle mutation or Feedback send/ingest/
  queue helpers are reached.
- A completed business run remains terminal while Feedback is independently pending with an
  explicit flush action.
- Existing node CLI routing and human-rendering tests were extended in place for `--explain`; they
  do not increase the three-test behavioral budget.

## Verification

Local Mac checks completed:

- `python3 -m compileall -q src scripts tests`
- `git diff --check`
- changed-path comparison against the frozen TaskCard allowlist
- manual inspection of payload-blind output and exact authorized-delivery checkpoint lookup

Per policy, Pytest and Ruff were not run on the Mac. Full Linux/Windows/macOS GitHub CI and an
independent exact-head review are required before merge.

## Remaining risks

- A missing or unreadable exact checkpoint remains `unknown`; status deliberately does not infer a
  model call from authorization alone.
- `--explain` reports the first blocker visible in current durable evidence. It cannot diagnose an
  external failure that left no trusted lifecycle, ledger or checkpoint fact.
- The earlier P1-1a package replaces undecodable runtime text deterministically; a narrow console
  may still display replacement characters rather than the original unsupported glyph.
