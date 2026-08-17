# Fresh-Machine Usability Benchmark Report

## Outcome

This original benchmark's local synthetic beginner journey passed, while its first cross-machine
attempt stopped truthfully before Deep Preflight at `BLOCKED_BEFORE_DEEP`. That remains the correct
historical result for PR #93 and the authority available during that run.

A separately authorized, fully isolated rerun subsequently cleared the prerequisites and passed
Mac/VPS/Windows Fast plus Mac-to-Windows Deep Preflight. The program's current no-model acceptance
result is therefore `PASS`; see the
[acceptance closeout report](fresh-machine-usability-acceptance-closeout-report.md). The follow-up
did not inspect or operate the production pending delivery that blocked this original run.

No model was invoked. No business event was created, read, dispatched, acknowledged, requeued,
recovered, or reused. The benchmark did not inspect the identity or payload of any pending
delivery and did not mutate a production service.

## Measured journeys

| Surface | Fresh preparation | Measured command time | Result | First blocking boundary |
|---|---:|---:|---|---|
| Local Mac synthetic facade | fresh virtual environment and disposable Git/config/state roots | 0.0379 s for seven facade commands; 8.7 s including the successful wheel install | PASS | none inside the synthetic journey |
| Mac remote-dispatch Fast Preflight | fresh installed wheel over the current exact checkout | 14.1 s wall time | FAIL before Deep | payload-blind coder queue count was 1; Deep requires both scoped counts to be zero |
| VPS remote-dispatch Fast Preflight | shallow exact-main clone and disposable Python 3.12 environment | about 149.7 s including clone/install/probe | FAIL | strict operations configuration was absent |
| Windows remote-dispatch Fast Preflight | shallow exact-main clone and disposable Python 3.12 environment | 30.1 s including clone/install/probe | FAIL | strict operations configuration was absent |

The VPS and Windows probes also reported the expected downstream consequences of a deliberately
fresh checkout: Bus/network/tool configuration was unavailable and the canonical upstream/fork
Git relationship had not been enrolled. The Windows exact-SHA checkout was detached. These are
reported as facts; the benchmark did not silently repair them or borrow a production configuration.

## Local beginner journey

The successful synthetic path used exactly seven operator commands:

1. `awf init`
2. `awf doctor --explain`
3. `awf start`
4. `awf run check`
5. bare `awf run`
6. `awf status --explain`
7. `awf stop`

It recorded five explicit human decision groups: machine, project, coder runtime/model, reviewer
runtime/model, and upstream/head repository relationship. Init generated two existing node
profiles, one owner RunManifest, and one compiled run contract. The compiler check and real
no-model run-ledger initialization executed against disposable state. Doctor/start/status/stop
used deterministic lifecycle seams, so this result measures the facade and configuration journey,
not native service-manager behavior.

Per-command timings were 0.0110, 0.0031, 0.0034, 0.0040, 0.0103, 0.0034, and 0.0025 seconds. The
measurement excludes time for a person to choose values and excludes external runtime
authentication.

## Cross-machine facts

- Mac Fast Preflight passed runtime, strict configuration, private-network reachability, Agent Bus
  health, local/remote Git, read-only GitHub access, the architect `not-applicable` model policy,
  and workflow-control checks. Remote dispatch remained denied because no current Deep proof was
  valid and the coder-scoped pending count was nonzero.
- VPS Fast Preflight ran from the merged exact main revision in a disposable Python 3.12
  environment. Runtime and workflow-control checks passed; the first prerequisite was the absent
  strict operations configuration.
- Windows Fast Preflight ran from the same merged revision in a disposable native Python 3.12
  environment. The PowerShell runtime and workflow-control checks passed; the first prerequisite
  was likewise the absent strict operations configuration.

Because Deep requires zero pending counts before it sends disposable control events, the Mac fact
is a hard stop. Fixing it would require separate authority over the current queued delivery; this
benchmark is permanently forbidden from inspecting or operating that delivery. VPS and Windows
would additionally need credential provisioning and repository enrollment, which are live
environment actions outside this package.

## Baseline comparison

The 2026-08-14 review estimated 90–240 minutes for an expert fresh setup but explicitly labeled
that range unmeasured. The seven-command local synthetic surface is materially smaller and now has
a real command/runtime measurement. The complete fresh remote-dispatch journey did not pass, so
this report does not claim a percentage reduction in time-to-first-useful-run and does not replace
the review estimate with a successful end-to-end number.

## Original decision and subsequent closeout

- Keep the merged usability contracts and the P2 `NO_GO_PRODUCTION_BINARY` decision.
- At the end of this original run, do not authorize or dispatch a new business TaskCard.
- The subsequent separately authorized attempt did start from fresh host configuration, enrolled
  repository identities, payload-blind zero queue observations, and new disposable Preflight
  identities. It passed without recovering or reusing retained business events.
- The passed no-model gate permits a separately scoped business TaskCard to be considered, but
  neither this benchmark nor its closeout invents or dispatches that work.

## Verification

- All probes used the merged main commit
  `bb0d597ee6a08a48a071908a259e4d88316d6a5f` or a branch directly based on it.
- Local verification used an installed wheel and no pytest, Ruff, Rust, or Go build/test.
- The P2 post-merge normal CI run `32039204943` and Binary Feasibility run `32039204743` were green
  before this milestone began.

## Remaining risks

- Native service-manager lifecycle timing was not measured by the synthetic local seams.
- VPS/Windows credential provisioning, repo enrollment, and Deep transport proof were open at the
  end of this run and were later closed by the isolated acceptance rerun.
- The pending coder delivery remains untouched and unidentified; its legal owner and lifecycle are
  intentionally not inferred here.
