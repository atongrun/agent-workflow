# Goal: Agent Bus Diagnostic Command

> Infrastructure-development dogfood: reliability and evidence quality take precedence over
> reducing high-value-model use. This example is not the downstream product-value benchmark.

Add the first non-mutating `agent-bus doctor --json` slice for the existing Agent Bus CLI.

## Outcome

An operator can distinguish:

- missing or invalid local configuration;
- network connection failure;
- unhealthy Agent Bus service;
- unauthorized or incorrectly scoped token;
- successful configuration, health, and authentication checks.

## Scope

- `client/cli.py`
- focused CLI tests in `tests/test_cli_helpers.py` or one new CLI test file
- CLI documentation

## Constraints

- Preserve current send, pending, ACK, listen, and handler-success ACK behavior.
- Do not modify server schemas or event state.
- Do not add dependencies.
- Use deterministic HTTP mocking for automated tests.
- A live endpoint probe is optional evidence, not a required test.

## Later

- send/pending/ACK mutation probes
- dashboard or tray UI
- generic diagnostics framework
- retry orchestration
- cross-machine Workflow integration
