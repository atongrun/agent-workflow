# P1-3 Structured Handler Contract Implementation Report

## Summary

Agent Workflow now emits production listener registrations through the pinned Agent Bus
`agent-bus.listen.on-argv.v1` consumer. Role, rework, terminal architect, and optional no-model
Preflight handlers are built as exact argv lists, serialized as UTF-8 JSON, and registered with
`--on-argv`.

The legacy `--on TYPE COMMAND` builders remain only as compatibility test helpers. The listener's
production path no longer uses them.

## Scope

- Added pure `awf.handler-argv.v1` builders in `scripts/awf_listen.py` for role and Preflight
  handlers.
- Preserved the existing `awf_role.py` argv parser, delivery/provenance fields, state-root binding,
  rework/terminal report mapping, and Preflight request/result fields.
- Changed listener registration for primary, coder rework, architect blocked terminal, and optional
  Preflight routes from `--on` command templates to `--on-argv` JSON.
- Updated focused tests to decode and inspect the structured argv registrations directly.

## Boundaries Preserved

- No Agent Bus, `awf_role.py`, node/facade/CLI, delivery schema, checkpoint, outbox, Feedback,
  recovery, ACK, requeue, redispatch, model-routing, or provider changes.
- No retained business event or payload was read or operated on.
- No compatibility fallback is attempted after event delivery. An old Agent Bus fails before
  listener connection/event delivery because it does not understand `--on-argv`.

## Local Verification

Local Mac verification was limited to static/compile checks per the TaskCard constraint:

- `python3 -m compileall -q scripts/awf_listen.py tests/test_awf_role.py tests/test_control_plane.py tests/test_awf_preflight.py`
- `git diff --check`
- Static search for production `listen_argv += ["--on"...]` registrations
- Allowed-path check via `git status --short` and `git diff --name-only`

Pytest, Ruff, Rust, installed-wheel, and cross-platform verification remain GitHub CI only.
