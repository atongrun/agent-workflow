# Node Readiness Snapshot Implementation Report

## Problem

A fresh architect session could spend several SSH round trips rediscovering one role node's host,
checkout, installed Agent Workflow version, selected model executable, Bus health, and listener
state. The remote commands did not invoke a model, but each tool round trip consumed architect
reasoning and enlarged the high-value session context. Repeating that discovery for every card in
a serial downstream run would undermine the capacity-isolation goal.

## Decision

`awf node doctor --profile <profile> --json --ttl-seconds <seconds>` emits
`awf.node-readiness.v2`. The v2 report removes the umbrella `status=ready` field. It contains only
credential-free facts: observation and expiry times, Agent Workflow/Python/platform identity, the
role/tool/model selection, profile digest, an opaque readiness fingerprint, and the orthogonal
`configured`, `installed`, `running`, `connected`, and `dispatch_capable` facts. False, unknown,
and stale observations remain explicit, and one `next_action` identifies the legal operator step.

The fingerprint binds the installed Agent Workflow version and operations tree, profile, strict
configuration, role repository, Agent Bus executable, selected model executable and version hash,
and listener observation. Secret configuration values and private paths contribute only through
the opaque hash and never appear in JSON. The maximum reuse window is 24 hours.

## Boundary

The snapshot is operator-discovery evidence, not a second preflight cache. The command does not
write a file, send or read an event, ACK, requeue, start a listener, invoke a model, or modify a
repository. Configuration proves only profile/config/tool/workspace readiness. Managed
installation comes only from the native install record and definition digest; running retains the
existing exact identity agreement; connection is a bounded Bus doctor observation. A true
`dispatch_capable` fact is emitted only when the existing read-only Fast gate accepts the current
bound Deep proof. Fast/Deep Preflight retains its fingerprint, HMAC cache, transport proof, and
sole authority to permit remote dispatch.

Agent Bus remains transport-only. Readiness JSON is intentionally not added to its protocol or
queue lifecycle; an operator may collect the first report with one remote command and reuse that
bounded evidence for the healthy portion of a short serial run.

## Verification

Regression coverage locks representative lifecycle transitions, missing/stale Preflight facts,
the shared explicit install prerequisite, bounded TTL, secret/path omission, tool-version
fingerprint drift, CLI argument routing, and installed-wheel command availability. Full pytest,
Ruff, formatting, and Linux/Windows/macOS installed-wheel verification run in GitHub CI under the
repository's macOS validation policy.
