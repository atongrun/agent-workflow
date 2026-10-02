# Validation scope

Development checkpoint: 2026-10-02, Go 1.27.1 on Linux amd64.

- 44 top-level Go tests pass with race detection when the opt-in native Pi test is enabled
- `go vet ./...` passes
- Linux amd64 Host/node, Windows amd64 Host/node and Windows arm64 node cross-builds pass
- Native Pi 0.99.2 integration uses the actual Go Host adapter and bundled extension, not a transport mock
- Native integration checks role-specific tool discovery, exact native session arguments, filtered control credentials, RPC state/history/commands/abort, default single-Pi completion and optional role identities, persisted synthetic history, bounded idle eviction/reopen and Host restart
- Native Pi checks do not call a model or demonstrate real coding; the persistence fixture is explicitly synthetic
- Node/client tests use an HTTP/SSE contract fixture to exercise idempotency, lost acknowledgements, recovery, terminal matching, errors, cancellation, workspace boundaries, same-task session reuse, permission/question waits and timeouts
- No actual Windows native OpenCode run, production deployment, model-backed workflow, Git artifact or real acceptance task is claimed by these tests

The checked OpenCode source contract is v1.18.34. An installed target version must be inspected and exercised natively; do not upgrade it silently merely to match this source reference.

The existing web application's tests, browser verification and deployment checks are maintained separately. Production acceptance remains gated on the real environment, authentication and user-approved small workspace/task.

The initial-flow scope was narrowed to one Pi after the original implementation checkpoint. Tests assert separate review is disabled by default, successful reporting retains the original Pi session, and a separate reviewer requires explicit opt-in.

Optional node model configuration is tested for native-default omission, exact structured forwarding, invalid shapes, immutable accepted-job snapshots across restart and rejection of caller-supplied overrides.
