# Windows listener startup implementation report

## Problem

A published `v0.3.0-rc.2` downstream run observed a Windows listener reach Agent Bus, but
`awf node start` stopped it after the parent's fixed three-second lease readiness deadline. The
failure occurred before Deep Preflight, dispatch, model invocation, or queue mutation.

## Change

The node lifecycle now waits up to 15 seconds for the spawned listener to publish the exact
profile-bound role, repository, and PID lease. It continues to check child exit on every polling
iteration and fails closed when the trusted lease is absent or mismatched at the deadline.

The timeout is intentionally a single cross-platform runtime constant. It does not add another
profile option, platform branch, background retry service, or Agent Bus responsibility.

## Regression contract

- A matching lease that appears after four seconds succeeds, covering the observed class that the
  former three-second deadline rejected.
- A listener that never publishes a matching lease still receives a bounded readiness error after
  15 seconds.
- Existing process binding, lifecycle lock, stop, PID, and listener ownership semantics are
  unchanged.

Complete Linux, Windows, macOS runtime, and installed-wheel validation is delegated to CI under
the repository's macOS test policy.
