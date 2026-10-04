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
  "piAgentDir": "/var/lib/awf/pi-agent",
  "piProvider": "magpie",
  "piExtension": "/opt/awf/extensions/awf.ts",
  "projects": {"acceptance": "/srv/awf/acceptance"},
  "nodes": {"windows": {"url": "http://execution-node.example:7071", "tokenEnv": "AWF_WINDOWS_TOKEN"}}
}
```

Use distinct randomly generated tokens of at least 24 characters, installed by the operator in a protected service environment. Never put real tokens in Git, CLI arguments, browser storage or application HTML. The example hostname is a placeholder; use the verified private network node address and enforce its network ACL. If transport is not on an authenticated private network, use TLS. The Host refuses redirects when forwarding credentials.

The Host defaults to at most one live Pi process (configurable 1–4). It evicts only idle sessions with no queued/in-flight prompt or native dialog and preserves their native session files. If every slot is active or needs recovery, new sessions fail clearly instead of growing unbounded. Measure actual target memory with the selected model/tool workload before production acceptance.

Run `awf host --config /etc/awf/host.json`. For a service manager, configure graceful SIGTERM, restart-on-failure, a private writable state directory and resource limits. Do not deploy two Host writers against the same state directory. Back up the whole state directory, including native Pi sessions, together with node job state using an operationally consistent snapshot. Do not delete locks/state to make a failing startup pass.

### AWF model configuration

Use the same installed Pi 1.0.2 executable for products that need it; keep AWF's writable agent configuration independent. `piAgentDir` defaults to `<dataDir>/pi-agent` and must be absolute; `piProvider` defaults to `magpie` and is fixed by server configuration. Every Host-owned Pi process receives this exact `PI_CODING_AGENT_DIR`, overriding an inherited value, and `--offline` disables startup model-catalog networking. The Host does not install another Pi, mutate another product's defaults, or write native provider files.

Provision `<piAgentDir>/models.json` through the operator. This non-secret example follows Pi 1.0.2's native custom-model format:

```json
{
  "providers": {
    "magpie": {
      "baseUrl": "http://127.0.0.1:3425/v1",
      "api": "openai-completions",
      "apiKey": "magpie",
      "models": [
        {"id": "deepseek/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
        {"id": "qwen-cn/qwen3.8-flash", "name": "Qwen 3.8 Flash"}
      ]
    }
  }
}
```

`magpie` is a public dummy key for this loopback bridge, not an upstream credential. The bounded adapter accepts only `openai-completions`, HTTP loopback port 3425 with path `/v1`, this literal dummy key and models without transport overrides. Provider headers and per-model URL/key/API overrides are refused. Missing, malformed or unreadable configuration fails explicitly; there is no native/direct-provider fallback. Catalog listing alone cannot prove the bridge or upstream model is healthy; target acceptance must verify the real installed native catalog and approved model operation. The public API exposes only model references/names and opaque revisions.

The product default is stored in Host state, independently of native Pi settings. Updating it during active work affects only new native sessions. Existing histories resume without model CLI overrides. If their verified actual model is outside the allowed catalog, they remain available for the existing explicit idle model control while prompt/compact fail with `needs_model_selection`; no migration scan, session reconstruction or history rewrite is performed. Map the web proxy's model settings endpoint to authenticated `GET/PATCH /v1/model-settings`; the existing `/v1` boundary still excludes `/internal`.

### Host permission checks across operating systems

The production control-Host deployment described above uses Linux/POSIX private
state permissions. On Windows, Go's `FileMode.Perm`, `Mkdir(..., 0700)` and
`Chmod(..., 0600)` do not describe or install a Windows DACL. A standalone
`awf host` on Windows requires an operator-provisioned private `dataDir` whose
files and planning directories inherit the intended account's ACL; the Host does
not automatically harden an arbitrary Windows directory. A passing Windows
functional test is not evidence that this separate deployment has been secured.

The managed Windows execution-node CLI has a different, explicit boundary: its
installer protects the per-user AWF root and its launcher validates real owners,
DACLs and reparse attributes. Native Windows security tests inspect the actual
DACLs on inherited state files, replacements and nested directories, including a
negative broad-DACL fixture. POSIX mode assertions remain active on Unix; their
Windows replacement is this native ACL coverage, not a claim that `0600` secures
Windows files.

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

Project IDs must map to explicit existing absolute directories on both machines. These paths can differ between machines. The node sends directory scope on native instance routes and keeps one active job per project. A directory allowlist is routing control, not an OS sandbox. Native OpenCode permissions still require action in its interface; bound native questions can use the authenticated Host API when Host, node and Pi extension versions match.

The Host supplies repository/branch/plan instructions to the agent; it never creates directories as a substitute for Git setup, and does not perform Git itself. Initially use a dedicated user-approved acceptance workspace, not an arbitrary existing business repository.

## Protected web application boundary

The existing web server authenticates the user and enforces same-origin writes. It proxies only the documented `/v1` routes, injects the server-side Host bearer token, and authenticates its own protected tunnel access. Do not allow `/internal` through this proxy. The Host default listener is loopback. Reject credential-bearing redirects and preserve SSE cancellation/replay semantics.

Production acceptance must independently verify authentication, origin protection, secret redaction, blocked cross-origin writes, desktop/narrow UI, a real streamed model conversation, exact plan confirm/start, a small native Windows edit/test with real artifacts, same-Pi execution reporting, refresh/reconnect, duplicate submissions, separated stop/cancel and recovery after lost acknowledgements.

## Single-task loop compatibility and cold rollout

Deploy the matching Host, execution node and `extensions/awf.ts` together after explicit deployment approval and target-OS acceptance. Older nodes lack the bound-question routes; the Host fails closed and never falls back to browser/native credentials or an unbound answer endpoint. The question adapter follows the official OpenCode v1.18.34 API (`GET /question`, `POST /question/{requestID}/reply`, scoped `directory`, boolean acknowledgement). The actual installed native release, including v1.18.32 deployments, needs operator-owned target acceptance; local fixtures do not establish native Windows or model compatibility.

Prefer a cold rollout with no in-flight execution, native dialog/question or Pi prompt. Coordinate existing work in its current interface and back up durable Host/node/Pi state before restarting services; do not stop a waiting job merely to install this change. OpenCode's pending question map is native in-memory state. This change cannot promise that a currently pending question survives an OpenCode restart, service replacement or upgrade. An upgrade does not synthesize or replay a missing native question. Native question replies are fenced in node state, so preserve that state; an ambiguous answer outcome needs original receipt verification, never a fresh-ID retry.

Existing job fingerprints, native sessions, accrued budgets, waits and rework counters are preserved. Existing completed verdicts and terminal histories remain unchanged. Already-Blocked failed or Cancelled tasks from before this version are not automatically reopened for review. Persisted `reporting` results and newly observed terminal receipts can join the same-Pi result loop. Old unsent `execution_result` receipts resume only when their persisted dispatch fence is false; accepted/sent receipts with unknown native acknowledgement remain `needs_verification`. The updated Pi extension supplies evidence assessments for new Done calls; old tools omitting them cannot declare Done, while a legacy Needs Changes call records unknown evidence. Operators must verify cold restart, active-job polling, busy-session delivery, lost acknowledgements and frontend receipt handling on the actual target before considering rollout accepted.

### Cancelled native question compatibility

Matching node/Host source now cleans precisely bound residual questions after explicitly authorized cancellation and confirmed abort, using the node-owned native authentication. OpenCode v1.18.34 officially exposes `POST /question/{requestID}/reject` with scoped `directory` and boolean ACK. Its successful non-null session-status map omits idle sessions; a missing entry is accepted only with a separately verified native Session. Unknown map responses still block cleanup. Native Windows/model acceptance remains required; fixtures are not that acceptance.

For a staged rollout, upgrade the node first, then the Host. The node keeps the existing cancel route and adds optional job receipt fields; an older Host ignores those fields and does not refresh terminal question waits. A newer Host with an older node cannot establish cleanup and retains those waits. This patch requires no Pi extension change. Once both ends are upgraded, an exact retry of the original Host cancellation request can reconcile an old terminal cancelled execution only when it still has pending questions and its original receipt is `accepted_native` or `needs_verification`. GET polling alone does not dispatch cleanup; a fresh cancellation request for a terminal execution remains rejected. The node also requires durable explicit cancellation authority, confirmed abort and provable original native turn ownership, so upgrading never creates authority for an unrelated or merely timed-out execution.

A running older supervisor/node does not gain this capability by replacing files. An old RC7 instance already blocked by an orphan question cannot hot-load this repair or pass the unchanged update/stop idle gate merely because a new binary is available. Coordinate any separately authorized maintenance recovery with the native owner; this change supplies no force-stop, credential extraction, state surgery, permission approval or gate bypass. Retain original Host/node/Pi state and use the exact original cancellation identity for receipt reconciliation after an approved cold rollout. Malformed/missing original turn evidence stays blocked instead of guessing ownership.
