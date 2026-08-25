# RC.2 Phase 1A — Formal Operations Package Implementation Report

## Scope and outcome

This report records the Phase 1A Terra canary defined by
[`rc2-phase1a-operations-package.md`](rc2-phase1a-operations-package.md).  It was implemented on
`codex/rc2-phase1a-operations-package`, from live `origin/main`
`366609d5b09b0721271c39ca72e40d8712f35ad3`; the frozen planning commit was
`6f7d79bf1c5718771c8adb6277bcd563a6f77eb1`.

The operations source tree is now `agent_workflow.operations`.  Production CLI, node, and status
callers use lazy package imports instead of adding a resource directory to `sys.path`.  Native
listener and service entry points invoke package modules with `python -m`; the model Git guard is
self-contained so its intentionally minimized model environment does not need a Python import-path
override.  Existing operational assets stay beside the formal package and are included by normal
package discovery rather than the former wheel force-include mapping.

No Workflow, TaskCard, provider, Agent Bus, ACK/retry, Git/PR, checkpoint/outbox/inbox, topology,
machine-binding, lifecycle, or Windows behavior was changed.

## Migration decisions

| Decision | Result | Reason |
|---|---|---|
| Move the operations tree, including assets | Reuse | Keeps one source of truth for imported modules and executable/resource assets. |
| Use lazy package imports in CLI/node/status | Adapt | Retains the previous deferred operational edges without runtime path mutation. |
| Use `python -m` for managed listener/service entry | Adapt | Preserves installed and source behavior after package-relative module ownership. |
| Keep the model Git guard self-contained | Adapt | Its restricted child environment intentionally lacks source/import-path assumptions. |
| Generic provider/lifecycle abstraction | Reject | Outside this card and unsupported by the package-boundary need. |

## Verification

| Gate | Result |
|---|---|
| `git diff --check` | PASS |
| `ruff check .` | PASS |
| `ruff format --check .` | PASS |
| Focused CLI/node/facade + runtime boundary suite | PASS: 218 passed, 1 platform skip |
| Fresh wheel built and installed outside source checkout | PASS; package assets, CLI, listener lease binding, plan check, and help surfaces passed |
| Static production search for `sys.path` mutation | PASS: no Python production hit |
| Independent review | PASS; independent full suite: 948 passed, 5 platform skips; no L2 findings |

The implementation suite was exercised in ordered portions because the interactive command boundary
ends long runs at 30 seconds.  The independent reviewer then ran the complete suite in one separate
environment; its result is the recorded full-suite gate.  The focused and runtime-boundary portions
cover the changed imports, direct handler execution, asset paths, and installed-wheel contract.

## Canary measurements

| Measure | Evidence |
|---|---|
| First deterministic pass | Initial focused run exposed seven test fixtures that still patched bare operation module names; no production failure was accepted. |
| Review/rework | One bounded mechanical test-fixture rework changed them to package-qualified imports; subsequent focused gate passed. |
| Wall time | 14 minutes, from the frozen-card commit through the first complete focused/package/wheel gate in this session. |
| Token/cost evidence | No provider/token or cost meter is available to this local implementation session; none is claimed. |

## Closeout

PR [#126](https://github.com/atongrun/agent-workflow/pull/126) merged the exact reviewed head
`c309f7ecd49b7a1e103d760b883b81421299fd83` into `main` as
`abc5ad2db8f7efcf0531d4fd844cf8bd1558f3cb`. All 18 exact-head CI checks completed SUCCESS,
including Windows recovery/configuration and fresh installed-wheel checks on macOS, Ubuntu, and
Windows. The feature branch was deleted after merge.

Phase 1B topology, machine binding, lifecycle closeout, and Windows no-console acceptance remain
separately authorized work.
