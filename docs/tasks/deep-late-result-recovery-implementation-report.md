# Deep late-result recovery implementation report

Date: 2026-08-09

## Problem

A managed Windows listener naturally consumed a retained Deep request after the original caller
had timed out. The target and source handlers both returned zero, the reply was ACKed, and both
queues returned to zero, but only the no-longer-running caller could sign `latest-deep.json`.
Operators could either send a prohibited second probe or fabricate the cache; neither is a valid
same-delivery recovery path.

## Contract

`awf preflight resume-deep --probe-id <id>` finalizes only an existing `source-result.json`. It
reruns the complete Fast gate, binds the result to the current fingerprint and exact source/target
roles, validates both positive event IDs and child return codes, and requires both queues to be
exactly zero. The original Deep path cannot send until its zero baseline succeeds, so the exact
same-probe result preserves that `pending_before` invariant after caller loss. The finalizer then
uses the existing scoped-token HMAC and cache validator.

The command has no send, listen, ACK, read, requeue, or redispatch path. It does not inspect an
event payload; the result handler has already reduced the delivery to canonical credential-free
evidence. Identity drift, missing evidence, current Fast failure, or pending drift denies cache
creation.

## Regression coverage

- A matching durable late result becomes a signed dispatch-authorizing cache.
- The recovered report preserves the original request/reply event IDs and labels the timeout
  recovery.
- Fingerprint mismatch and nonzero queues remain fail closed and write no cache.
- The successful recovery path invokes no Agent Bus lifecycle or send command.

Full Python, Ruff, installed-wheel, and cross-platform validation is delegated to GitHub CI under
the repository's macOS test policy.
