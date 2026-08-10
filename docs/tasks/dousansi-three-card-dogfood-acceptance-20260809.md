# Dousansi Three-TaskCard Dogfood Acceptance — 2026-08-09

## Outcome

Agent Workflow completed its first non-infrastructure, three-TaskCard downstream phase on
`atongrun/dousansi-shouzhang`. All three cards followed the same serial production path:

`Mac architect -> Windows OpenCode coder -> Mac Pi reviewer -> architect terminal consumer`

Each card produced a trusted implementation commit, structured `PASS` ReviewReport, upstream pull
request, green CI result, terminal ledger state, success-gated ACK, and merge. The three role queues
were empty at closeout. No business delivery was manually ACKed, requeued, redispatched, or replaced.

## Accepted Runtime Baseline

- Agent Workflow release candidate: `v0.3.0-rc.7`
- Agent Workflow source: `b7c913751d84733f1e3e01ca8339a9a40979a488`
- Mac and Windows used the published wheel rather than an Agent Workflow source checkout.
- The Windows coder used the managed node lifecycle. A fresh session B proved that its manager,
  listener PID, launch identity, lease, and queue connection survived the complete exit of session A.
- The original Deep probe result was recovered after caller timeout by `awf preflight resume-deep`.
  Recovery made no model call and did not send, inspect, ACK, requeue, or redispatch an event.

## Card Evidence

| Card | Business change | Delivery events | Implementation commit | Pull request | Merge commit | CI |
|---|---|---:|---|---|---|---|
| `DOUSANSI-RC2-DOGFOOD-001` | First bean | 151-153 | `38d335c8dd21378efe97a6fb70389e3c9fa3b0c6` | [#32](https://github.com/atongrun/dousansi-shouzhang/pull/32) | `a197b9a35c0ce80db36ccb37ea46dbb83926697f` | [green](https://github.com/atongrun/dousansi-shouzhang/actions/runs/31312785318) |
| `DOUSANSI-RC2-DOGFOOD-002` | Plan-change record | 154-156 | `b81b92a868e7683f14c7b3bbb79a49b0665a506a` | [#33](https://github.com/atongrun/dousansi-shouzhang/pull/33) | `f28d91cb0d2a4c64003cdc2168607a86901034c1` | [green](https://github.com/atongrun/dousansi-shouzhang/actions/runs/31313667788) |
| `DOUSANSI-RC2-DOGFOOD-003` | 24-hour reconsideration | 157-159 | `4d8ca33b4e97a357e598810d12437ca9e3892e83` | [#34](https://github.com/atongrun/dousansi-shouzhang/pull/34) | `fd5ed77be77e8b4d2fed32c99ad3115a79e76a6f` | [green](https://github.com/atongrun/dousansi-shouzhang/actions/runs/31314327668) |

The downstream repository owns the TaskCards, reports, ledgers, and exact product assertions. This
report records only the cross-project acceptance evidence needed by Agent Workflow.

## Capacity-Isolation Metrics

| Metric | Observed result |
|---|---:|
| Completed TaskCards | 3 |
| OpenCode coder model invocations | 3 |
| Pi reviewer model invocations | 3 |
| High-value model calls inside business delivery handlers | 0 |
| High-value-model-free business delivery paths | 3/3 |
| Deterministic rework loops | 0 |
| Escalations inside the business deliveries | 0 |
| Manual ACK/requeue/redispatch actions | 0 |
| Additional model calls for Deep late-result recovery | 0 |

The architect terminal consumer is deterministic and invoked no model. Phase planning,
infrastructure diagnosis, and milestone acceptance occurred outside the three delivery handlers;
those surrounding Codex interactions were not instrumented as a comparable invocation count. Do
not infer exact token or cost savings from this run. A later phase may establish a comparable
high-value-model-led baseline without retroactively estimating unavailable data.

## Failures That Had To Close First

The accepted run was not produced by bypassing its failures:

1. Windows `CREATE_NEW_PROCESS_GROUP` was proven session-bound under the observed OpenSSH host.
   The managed node lifecycle moved listener ownership to the OS user manager without adding
   PowerShell, WinSW, a service password, or Agent Bus runtime behavior.
2. A completed Deep result arrived after the caller timeout. The payload-blind installed recovery
   command revalidated the exact durable result and current zero queues instead of sending a second
   probe.
3. The stable TaskCard identity and branch-derived delivery identity produced two candidate report
   paths. Dispatch and listener validation were unified around the sole safe report path declared by
   the exact committed TaskCard.

All three repairs landed before the affected business path continued. No preserved historical
payload was used as a shortcut.

## Acceptance Decision

The three-card operational product gate is accepted. This evidence is sufficient to publish
Agent Workflow `v0.3.0` as the first release whose installed operations surface has completed a
real multi-card downstream phase across Mac and Windows.

This acceptance does not promote the operations surface into the stable core, make Agent Bus a
supervisor, justify Agent Host, or claim a universal provider/runtime abstraction. The next phase
is evidence-driven hardening and a second downstream run, with quantitative baseline comparison
remaining an explicit measurement gap.
