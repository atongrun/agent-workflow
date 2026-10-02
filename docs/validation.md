# Validation scope

Development checkpoint: 2026-10-02, Go 1.27.1 on Linux amd64.

- 44 top-level Go tests pass with race detection when the opt-in native Pi test is enabled
- `go vet ./...` passes
- Linux amd64 Host/node, Windows amd64 Host/node and Windows arm64 node cross-builds pass
- Native Pi 0.99.2 integration uses the actual Go Host adapter and bundled extension, not a transport mock
- Native integration checks role-specific tool discovery, exact native session arguments, filtered control credentials, RPC state/history/commands/abort, default single-Pi completion and optional role identities, persisted synthetic history, bounded idle eviction/reopen and Host restart
- Native Pi checks do not call a model or demonstrate real coding; the persistence fixture is explicitly synthetic
- Node/client tests use an HTTP/SSE contract fixture to exercise idempotency, lost acknowledgements, recovery, terminal matching, errors, cancellation, workspace boundaries, same-task session reuse, permission/question waits and timeouts
- These automated checks do not by themselves demonstrate a model-backed workflow, production deployment, Git artifact or real acceptance task; separate native Windows evidence is recorded below

The checked OpenCode source contract is v1.18.34. An installed target version must be inspected and exercised natively; do not upgrade it silently merely to match this source reference.

The existing web application's tests, browser verification and deployment checks are maintained separately. Production acceptance remains gated on the real environment, authentication and user-approved small workspace/task.

The initial-flow scope was narrowed to one Pi after the original implementation checkpoint. Tests assert separate review is disabled by default, successful reporting retains the original Pi session, and a separate reviewer requires explicit opt-in.

Optional node model configuration is tested for native-default omission, exact structured forwarding, invalid shapes, immutable accepted-job snapshots across restart and rejection of caller-supplied overrides.

## Native Windows Go-node acceptance

A separate model-backed acceptance run on 2026-10-02 exercised the Go node from public commit `fe1edeb9922bff1efd3143dac24fe22414abbbae` (clean source tree `d9d25dfe79996ce5e4b6ac0a46cf575d74790724`).

- Environment: Windows 10.0.26200 x64, existing OpenCode 1.18.32 and checksum-verified official Go 1.27.1 windows/amd64; the native Go-node build exited successfully
- The Go node and OpenCode listened only on loopback and used a temporary process-scoped token that was not printed
- The node's server-side `openCodeModel` selected `deepseek/deepseek-flash` (DeepSeek V4.1 Flash); the global model default was unchanged
- The initial job POST returned HTTP 202; immediate and terminal repeats with the same job ID returned HTTP 200 and the same job, with one native user request and an unchanged four-message history after repetition
- Native evidence recorded two file writes and one bash execution; the task's tests passed 7/7 with exit code 0, and an independent Node.js 24.11.1 rerun also passed 7/7 with exit code 0
- Three permissions were explicitly approved once; no persistent "always" approval was used
- Node status `completed` denotes observed execution, not independently established correctness: the node evidence retained `verified: false`, and the independent test rerun was external validation
- Both temporary processes were stopped and their listening ports were confirmed closed

This establishes native Windows Go-node execution and same-job idempotency for this acceptance task. The seven-test result is separate from the earlier direct native OpenCode nine-test run and from the 44 Go tests above. It does not establish model-backed Pi operation, Host deployment, browser/mobile UI, Access/tunnel configuration or a complete web end-to-end workflow; those acceptance gates remain open.

This is a documentation-only evidence update. The tested source code is unchanged, so no release rebuild is implied.
