# Deployment guide

This guide does not assert that any production machine has been deployed or authenticated. Build/test in a development environment, then validate the actual target OS, service accounts, existing services, resources, model authentication, network identities and project workspace before deployment. Do not stop unrelated services or copy another machine's credentials.

## Control Host

Run Pi and AWF as a dedicated unprivileged account. Pi is an agent with native tool access, not a sandbox; scope that account's filesystem and network permissions accordingly. Keep model authentication in its native Pi location. The Host filters its control credential environment variables before launching Pi; only a task/role-scoped extension capability is passed. This does not protect files accessible to the same OS account from native coding tools.

Example `host.json` (local, gitignored):

```json
{
  "listen": "127.0.0.1:7070",
  "internalUrl": "http://127.0.0.1:7070",
  "dataDir": "/var/lib/awf",
  "maxPiProcesses": 1,
  "enableReviewer": false,
  "tokenEnv": "AWF_HOST_TOKEN",
  "extensionTokenEnv": "AWF_EXTENSION_SECRET",
  "piBinary": "/opt/pi/bin/pi",
  "piExtension": "/opt/awf/extensions/awf.ts",
  "projects": {"acceptance": "/srv/awf/acceptance"},
  "nodes": {"windows": {"url": "http://execution-node.example:7071", "tokenEnv": "AWF_WINDOWS_TOKEN"}}
}
```

Use distinct randomly generated tokens of at least 24 characters, installed by the operator in a protected service environment. Never put real tokens in Git, CLI arguments, browser storage or application HTML. The example hostname is a placeholder; use the verified private network node address and enforce its network ACL. If transport is not on an authenticated private network, use TLS. The Host refuses redirects when forwarding credentials.

The Host defaults to at most one live Pi process (configurable 1–4). It evicts only idle sessions with no queued/in-flight prompt or native dialog and preserves their native session files. If every slot is active or needs recovery, new sessions fail clearly instead of growing unbounded. Measure actual target memory with the selected model/tool workload before production acceptance.

Run `awf host --config /etc/awf/host.json`. For a service manager, configure graceful SIGTERM, restart-on-failure, a private writable state directory and resource limits. Do not deploy two Host writers against the same state directory. Back up the whole state directory, including native Pi sessions, together with node job state using an operationally consistent snapshot. Do not delete locks/state to make a failing startup pass.

## Native Windows execution node

Install the supported native Windows OpenCode release and authenticate its provider through its official interface. Start the native server on loopback:

```powershell
opencode.exe serve --hostname 127.0.0.1 --port 4096
```

Example `node.json` (local, gitignored):

```json
{
  "listenAddress": "127.0.0.1:7071",
  "stateDir": "C:\\AWF\\state",
  "projects": {"acceptance": "C:\\AWF\\workspaces\\acceptance"},
  "openCodeUrl": "http://127.0.0.1:4096"
}
```

Optional server-side `openCodeModel: {"providerID":"verified-provider","modelID":"verified-model"}` selects an installed native model per accepted job. Omit it to use the native default. Verify the provider/model IDs against the actual native catalog; neither the browser nor job submission can override them. The selection is persisted before dispatch and survives restart without changing accepted work; it does not edit global OpenCode configuration.

Set `AWF_NODE_TOKEN` in a protected process/service environment. Optional native server authentication uses `OPENCODE_SERVER_USERNAME` and `OPENCODE_SERVER_PASSWORD`. Run `awf-node.exe -config node.json`. When allowing the Host over a private network, bind only the necessary private interface and limit inbound access to the control machine. Never expose unauthenticated native OpenCode to the public Internet.

### Node source restriction

With `allowedSourceIPs` omitted or empty, every node route accepts only loopback TCP peers. The default listener remains `127.0.0.1:8788`; the example above explicitly chooses port 7071. A non-loopback `listenAddress` (including a wildcard address or `-listen` override) requires a nonempty source list before startup. Listen addresses must use a literal IP and numeric port, with IPv6 in brackets; hostnames and an omitted IP such as `:7071` are rejected.

For a remote control Host over Tailscale, replace these placeholders with the verified Windows node and control Host Tailscale IPs in the local configuration:

```json
{
  "listenAddress": "<WINDOWS_TAILSCALE_IP>:7071",
  "allowedSourceIPs": ["<CONTROL_HOST_TAILSCALE_IP>"]
}
```

These are fields to add to the complete node configuration, not a standalone config. Use only the control Host's exact address; add its exact IPv6 address only if that transport is used. Entries must be unicast IP literals without a port, CIDR, zone or whitespace. No DNS lookup or subnet expansion is performed. IPv4-mapped IPv6 addresses match the corresponding IPv4 address.

A configured list replaces the loopback default: loopback is not implicitly allowed. The node checks the connection's actual `RemoteAddr`, never `X-Forwarded-For`, `Forwarded` or other proxy headers. Missing, malformed or unlisted peers receive HTTP 403 (`source_denied`) before any route runs, including health and job writes. An allowed peer still needs the separate bearer token. If a proxy is inserted, its socket address is the peer; do not put the node behind a shared proxy that could admit other machines.

Keep the Windows firewall/Tailscale ACL restricted to the verified private interface and control Host source as well. The application check is an additional restriction and does not depend on the global Windows firewall default. Verify both permitted control-Host access and rejection from another peer on the actual target before treating deployment as accepted.

Project IDs must map to explicit existing absolute directories on both machines. These paths can differ between machines. The node sends directory scope on native instance routes and keeps one active job per project. A directory allowlist is routing control, not an OS sandbox. Native OpenCode permissions/questions may still require action in its interface.

The Host supplies repository/branch/plan instructions to the agent; it never creates directories as a substitute for Git setup, and does not perform Git itself. Initially use a dedicated user-approved acceptance workspace, not an arbitrary existing business repository.

## Protected web application boundary

The existing web server authenticates the user and enforces same-origin writes. It proxies only the documented `/v1` routes, injects the server-side Host bearer token, and authenticates its own protected tunnel access. Do not allow `/internal` through this proxy. The Host default listener is loopback. Reject credential-bearing redirects and preserve SSE cancellation/replay semantics.

Production acceptance must independently verify authentication, origin protection, secret redaction, blocked cross-origin writes, desktop/narrow UI, a real streamed model conversation, exact plan confirm/start, a small native Windows edit/test with real artifacts, same-Pi execution reporting, refresh/reconnect, duplicate submissions, separated stop/cancel and recovery after lost acknowledgements.
