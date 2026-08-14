# P0-2 Truthful Lifecycle State Model Implementation Report

## Outcome

Node doctor and factual status now report configured, installed, running, connected, and
dispatch-capable as independent facts. The ambiguous doctor `status: ready` is gone. Missing,
unknown, not-applicable, and stale evidence remains visible, and the first blocking fact yields one
legal next action.

Managed start uses the TaskCard's frozen fail-closed choice. It validates the current native
manager install record and definition before writing desired `running`; an absent installation
names the exact `awf node install --profile <resolved-profile>` command, while drift names
`upgrade`. Start never installs implicitly on launchd, systemd, or Task Scheduler.

## Changed files and simplifications

- `src/agent_workflow/node_service.py` exposes one read-only installation snapshot over the existing
  record/definition verifier and one shared pre-start requirement. No adapter-specific state
  machine or new manager command was added.
- `src/agent_workflow/node.py` assembles one lifecycle block, removes the umbrella doctor state,
  preserves exact listener identity for running, records the bounded Bus-doctor observation for
  connected, and refuses to infer dispatch authority from a cache file alone.
- `src/agent_workflow/status.py` reuses that lifecycle block and renders unknown observations
  without running doctor or Preflight.
- README, lifecycle architecture, readiness documentation, changelog, and HANDOFF describe the
  same vocabulary and explicit install/start contract.
- Exactly two focused tests were added: one table-driven configured/uninstalled,
  installed/stopped, and running transition test; one stale-listener plus missing-Preflight test.
  The existing managed start-order test was extended to cover validation before desired-state
  mutation and the exact install action.

## Verification

Allowed local Mac gates:

- Python compilation/AST parsing of changed Python modules and tests — passed.
- `git diff --check` and TaskCard allowed-path inspection — passed.
- Static review confirmed no Agent Bus Core, business/Finding ACK, checkpoint, outbox, postflight,
  PR tuple, retained-event, or P0-3 surface changed.

Per the frozen Level B policy, local Pytest, Ruff, and Rust were not run. GitHub CI owns the full
suite and installed-wheel platform matrix. Final exact-head CI and independent review evidence are
recorded in the pull request before merge.

## Remaining risks

- A listener lease is not an Agent Bus session heartbeat, so factual status intentionally reports
  connected as unknown unless doctor made its bounded live probe. No daemon or transport protocol
  was added to manufacture stronger evidence.
- A non-expired Deep cache is not sufficient by itself because current Fast observations may have
  changed. Doctor/status therefore leave it unpromoted; operators run the existing Fast/Deep gate
  to obtain dispatch authority.
- Native service registration and platform behavior continue to be exercised by the existing
  installed-wheel CI and prior live lifecycle acceptance. This package changes only the shared
  state contract and start ordering, not adapter rendering.
