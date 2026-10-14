# Read-only orchestration acceptance — 2026-10-14

The deployed Host source is `d4097a614cbd8146fa54dd9c34b4766985dbd08e`. Windows uses the packaged CLI `v1.0.0-rc.11` (protocol 3). This documentation commit does not deploy another binary or change services.

## What was actually accepted

The existing fixed-source reader authenticated successfully. Pi performed real repository reads, published a typed plan, and normal confirmation pinned the public repository `atongrun/agent-workflow`, tag `v1.0.0-rc.11`, SHA `f549f054d7ef47d43ecaeac72fe4c2b81830832e`, and the existing Windows managed target. Normal same-task rework then used the real native OpenCode session; its terminal result returned to the same Pi session for review.

The final approved scope used existing PowerShell and Git only. Four native command calls completed with exit 0 and untruncated outputs. The source-structure gate reported 23 checks passed. Initial/final HEAD matched the pinned SHA, the managed task branch stayed unchanged, and status, diff and cached diff were empty. The public tag matched that SHA and the remote task branch was absent. There were no source edits, commits, pushes, generated artifacts, Go/WSL calls, installations or persistent PATH/configuration changes in this final execution.

**The scoped orchestration chain passed.** This proves the reader → Pi plan/confirmation → managed native execution → terminal receipt → same-task Pi review path for this bounded read-only task. It does not establish arbitrary repository delivery, cancellation/restart scenarios or source runtime correctness.

## Go and the task verdict

Running the packaged Windows CLI does not require a Go compiler. Go is a development dependency for building or running Go source tests. Earlier native Windows rc.11 fixture tests ran Windows `.test.exe` binaries cross-compiled with Go on Mac; that does not prove a compiler exists in the current OpenCode environment.

This task did **not** execute rc.11 Go tests, vet or builds. PowerShell text/structure assertions cannot substitute for those checks. Pi therefore reported the scoped chain PASS while retaining the original task's overall `needs_changes` verdict with Go-test evidence `unknown`. Previous clone failure and unsupported-toolchain history remain intact; the later narrowed scope does not rewrite them. The earlier run's additional directory/registry/WSL probes after finding Go unavailable were a recorded plan deviation; none occurred in the final narrowed run.

## Operational boundary

Only the previously approved stale global Git `http.proxy` and `https.proxy` settings were removed. Windows autostart remains **false**. Lazy startup and login appearance work are deferred. This acceptance did not restart services, change credentials or network policy, install Go, modify the original project, or publish code remotely.

Host `d4097a6` permits an explicit managed rework after a verified pre-native preparation failure only when a fresh authenticated original Node receipt proves no native session/work/output began. Unknown submission, cancellation, timeout, partial output and stale identities remain rejected. The local full Host race regression and independent source review passed; that is separate from this Windows source-test boundary. No new CI run is claimed for this closeout.
