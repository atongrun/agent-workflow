# Node Readiness Snapshot Implementation Report

## Problem

A fresh architect session could spend several SSH round trips rediscovering one role node's host,
checkout, installed Agent Workflow version, selected model executable, Bus health, and listener
state. The remote commands did not invoke a model, but each tool round trip consumed architect
reasoning and enlarged the high-value session context. Repeating that discovery for every card in
a serial downstream run would undermine the capacity-isolation goal.

## Decision

`awf node doctor --profile <profile> --json --ttl-seconds <seconds>` now emits
`awf.node-readiness.v2`. The report contains only credential-free facts: observation and expiry
times, installed Agent Workflow/Python/platform identity, the role/tool/model selection, profile
digest, an opaque readiness fingerprint, listener binding, passed local readiness layers,
explicit invalidation reasons, and independent lifecycle facts. The former umbrella
`status: ready` is removed: configured, installed, running, connected, and dispatch-capable
observations retain false, unknown, not-applicable, and stale distinctions.

The fingerprint binds the installed Agent Workflow version and operations tree, profile, strict
configuration, role repository, Agent Bus executable, selected model executable and version hash,
and listener observation. Secret configuration values and private paths contribute only through
the opaque hash and never appear in JSON. The maximum reuse window is 24 hours.

## Boundary

The snapshot is operator-discovery evidence, not a second preflight cache. The command does not
write a file, send or read an event, ACK, requeue, start a listener, invoke a model, or modify a
repository. Known profile, configuration, workspace, tool, listener, or Bus changes invalidate the
observation before its stated expiry. Fast/Deep Preflight retains its fingerprint, HMAC cache,
transport proof, and sole authority to permit remote dispatch.

Agent Bus remains transport-only. A successful bounded Bus doctor probe is reported as connected
only for that observation window; listener or manager state does not imply a connection. Readiness JSON is intentionally not added to its protocol or
queue lifecycle; an operator may collect the first report with one remote command and reuse that
bounded evidence for the healthy portion of a short serial run.

## Verification

Regression coverage locks the JSON shape, bounded TTL, secret/path omission, tool-version
fingerprint drift, CLI argument routing, and installed-wheel command availability. Existing human
doctor output and node lifecycle behavior remain compatible. Full pytest, Ruff, formatting, and
Linux/Windows/macOS installed-wheel verification run in GitHub CI under the repository's macOS
validation policy.
