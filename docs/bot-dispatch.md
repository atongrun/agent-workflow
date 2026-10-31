# Bot dispatch and pluggable executors

This is the local design for using AWF as a coding-task dispatch platform. It does not deploy the Host, change Cloudflare, or claim that a live Tailscale path or a WorkBuddy daemon has been accepted.

The active product line is `codex/dash-magpie-provider`. `main` is stale and its README incorrectly says the project is terminated. This document lives on the active line.

## What Pi already provides

Checked against this repo and the published docs on 2026-10-28:

| Surface | What was checked | What it already does | Gap left for Go |
| --- | --- | --- | --- |
| Pi coding agent | `internal/pi/client.go` launches `pi --mode rpc --extension <file>` with task-scoped `AWF_*` environment variables. Extension API is `extensions/awf.ts` (`registerTool` on `@earendil-works/pi-coding-agent`). | Conversation, context, tools, and the planning/result session. | The extension cannot authenticate Tailscale callers or bind a public listener. |
| Pi package | [Pi packages](https://pi.dev/docs/latest/packages) and [extensions](https://pi.dev/docs/latest/extensions). A directory `package.json` may set `keywords: ["pi-package"]` and `pi.extensions`. Host-provided imports (`@earendil-works/pi-coding-agent`, `typebox`) belong in `peerDependencies` as `"*"`, not in `dependencies`. | Discovers and loads an extension directory. | A package does not know the task, role, or extension token. Those still have to be injected per process. |
| Pi Durable `@earendil-works/pi-durable@1.0.4` (`gitHead` `7c10bd4337495ee613f2224843ecdf349b80d1df`) | [Architecture principles](architecture-principles.md) and the existing `internal/durablebridge` content adapter. | Conversations, submissions, checkpoints, native abort and resume. Dedup is conversation-scoped and does not compare payloads. | It is not AWF's public HTTP, Tailscale allowlist, request-fingerprint ledger, or Windows executor. |

## Decisions

**Pi package.** `extensions/package.json` publishes the existing `awf.ts` tools as a Pi package. The Host keeps passing that file to `--extension`. The package is how Pi discovers the same file; it is not a second tool implementation. The Host must keep supplying the scoped URL, token, task, and role. Loading the package as a global user extension would talk to the Host without that scope, so that is not the launch path.

**Pi Durable is not the bot ledger.** Bot create/cancel/answer receipts stay in the existing Host request store (`requestId`, payload hash, `needs_verification`). That store is the public idempotency boundary already used by `/v1`. Durable's dedup would not reject a same-id/different-payload admission, and a second event log would compete with the Host SSE log the dashboard already reads. Auto-start does not open a Pi process and does not copy session recovery into Go. The planning conversation, when a person uses the dashboard, remains the native Pi session. Executor progress stays on the node, which is the machine that can see the local daemon.

**Go owns the remaining service edges.** The bot listener is public HTTP plus source allowlisting. The node executor is a local process adapter. Both are the gaps Pi does not fill. No second task scheduler was added.

**MCP stays inside `awf host`.** `POST/GET/DELETE /mcp` is served on the bot listener in the Host process. A separate `cmd` would either open a second writer on the same state directory or be a proxy with the same token and no extra boundary. One listener keeps the dashboard `/v1` routes off this socket.

## Bot API

The dashboard listener (`listen`, bearer `tokenEnv`, routes under `/v1`) is unchanged. Bot routes are not mounted there, so an existing proxy that only forwards `/v1` cannot reach them.

`bot.listen` is a literal IP and port. Loopback with an empty `allowedSourceIPs` accepts only loopback peers. Any other bind requires an explicit allowlist. The allowlist replaces loopback; it does not add to it. Entries are exact unicast IPs, the same rule as the node's `allowedSourceIPs` (Tailscale CGNAT `100.64.0.0/10` is accepted by Go 1.24's unicast check). The peer is `RemoteAddr`. `X-Forwarded-For` is ignored. A denied peer gets HTTP 403 `source_denied` before the token is checked. A matching peer still needs `Authorization: Bearer`.

Each caller has its own `tokenEnv` (at least 24 characters, distinct from the Host token, the extension token, and other callers). The token selects the caller. The body cannot name a different caller.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/bot/v1/targets` | Same target/node view as `/v1/targets`. No paths or credentials. |
| GET | `/bot/v1/projects` | Projects grouped from that view. |
| GET | `/bot/v1/tasks` | Tasks created by this caller. Dashboard tasks are omitted. |
| POST | `/bot/v1/tasks` | Create. See auto-start. |
| GET | `/bot/v1/tasks/:id` | Status for this caller's task. Other callers get 404. |
| GET | `/bot/v1/tasks/:id/events` | SSE, same `event: awf` framing as `/v1`. |
| GET | `/bot/v1/tasks/:id/events?view=snapshot` | JSON `{events, sequence, reset}`. `Accept: application/json` selects the snapshot when `view` is omitted. |
| POST | `/bot/v1/tasks/:id/questions/:questionId/reply` | Same bound question reply as `/v1`. |
| POST | `/bot/v1/tasks/:id/cancel` | Same execution cancel as `/v1`. |

There is no delete and no general RPC. Writes use the existing `requestId` rule: `[A-Za-z0-9._:-]{1,128}`, same operation and payload replay the receipt, any change is HTTP 409. Create's operation is `bot/create`. A duplicate returns the task and, if execution is still active, reattaches observation. It does not reserve a second execution. If the node POST was already attempted, the existing dispatch fence still refuses another POST. An uncertain execution stays `needs_verification`. Do not mint a new `requestId` to retry it.

Create body: `requestId`, `title`, and, when auto-start applies, `projectId`, `nodeId`, a canonical `repository` (`owner/name`), plus `plan` or `goal`. Optional `repositoryId`, `acceptanceCriteria`.

## Auto-start policy

Default for a bot caller is auto-start. Set `callers.<id>.autoStart` to `false` to turn it off for that caller. `callers.<id>.projects.<projectId>.autoStart` overrides the caller for one configured project (`managed` is allowed as a project key).

The choice is stored on the task as `dispatch` (`auto` or `manual`) and `caller`. Later config edits do not restart old tasks.

Auto-start, in the same durable admission as the create receipt:

1. Creates the restricted task the dashboard create path already creates.
2. Binds the requested target at revision 1 after the same node catalog preflight `/v1` uses.
3. Records the plan (`plan`, otherwise `goal`) with `source: "bot"`, confirms that revision, and queues execution through the existing `prepareExecution` path.
4. The existing monitor performs the one node dispatch. HTTP 202 means the receipt was admitted, not that the daemon finished.

Manual bot creates, and every dashboard `/v1` create, still need the explicit confirm and start actions. Auto-start does not call Pi and does not click through the plan tool.

## MCP

Streamable HTTP on the bot listener at `/mcp` (protocol `2025-03-26`). The same bearer and source check run first. `initialize` returns `Mcp-Session-Id`. Later requests must send it. `DELETE /mcp` drops the session. `GET /mcp` with `Accept: text/event-stream` is the server stream (keepalive). Notifications get HTTP 202.

Tools: `list_targets`, `list_projects`, `list_tasks`, `get_task`, `create_task`, `get_events`, `stream_events`, `reply_question`, `cancel_task`. They call the bot routes. `stream_events` stays open only when the request accepts `text/event-stream`; otherwise it returns the snapshot page. Tool failures are `isError` results so the caller can see HTTP 409 and keep the original `requestId`.

## Executor plugin

`awf-node` selects `executor`. Empty means `opencode`.

`internal/executor.Driver` is the session, one-shot prompt, status, message, question, abort, and event surface the node already sequences. `executor.OpenCode` embeds the existing OpenCode client and changes none of its HTTP calls. Job durability, the prompt fence, and "do not resubmit an uncertain prompt" stay in the node.

`workbuddy` does not accept `openCodeModel`. Its URL must be an HTTP(S) loopback origin. The password comes from `workBuddyPassword` or `WORKBUDDY_PASSWORD` (at least 8 characters). `workBuddyPermissionMode` is `default`, `acceptEdits` (the default), or `plan`. `bypassPermissions`, `auto`, and `dontAsk` are rejected. Every dispatch sends `bgIsolation: "worktree"` and the registered project directory as `cwd`. The node still refuses unknown projects. The daemon is not started by the node.

The single daemon POST is `PromptAsync`. The correlation note (`messageId`, remote id, dispatched) is written under the node state directory before that POST. A second call, a lost response, or a restart reads the note and `GET /api/v1/jobs`; it does not POST again. Completion is still "a terminal assistant turn", expressed in the message shape the node already trusts, with `providerExecuted: true` on the synthetic tool part so a finished job is not mistaken for another model iteration.

### WorkBuddy contract and uncertainty

Public beta pages checked on 2026-10-28:

- [CodeBuddy HTTP API](https://www.codebuddy.ai/docs/cli/http-api)
- [Daemon mode](https://www.codebuddy.ai/docs/cli/daemon)
- [Tencent HTTP API](https://www.tencentcloud.com/document/product/1316/84473)

Those pages agree on `X-CodeBuddy-Request: 1`, `Authorization: Bearer <password>`, `POST /api/v1/jobs` with `prompt`, `cwd`, `permissionMode`, and `bgIsolation` (`none` or `worktree`), plus `GET /api/v1/jobs/:id`, `GET /api/v1/jobs/:id/stream`, `GET /api/v1/jobs/events`, `POST /api/v1/jobs/:id/reply`, and `POST /api/v1/jobs/:id/stop`. Responses use a `data` envelope. Job `state` is `working`, `blocked`, `done`, `failed`, or `stopped`; `status` is `busy`, `waiting`, `idle`, or `stopped`. Unknown combinations fail closed.

Not specified clearly enough to treat as stable, so this client does not guess past them:

- The reply body. AWF sends `{"text":"..."}` once. A 4xx stays on the existing question fence and is not rewritten into another shape.
- The SSE event JSON. The client accepts one JSON object per event (`type` or `event`). Polling `GET /api/v1/jobs` remains authoritative. The stream is only the pre-prompt handshake the node already requires.
- The serve port. Docs show both `8080` and `8321`. Configure the URL you actually start.
- `codebuddy -p ... --output-format stream-json` and `codebuddy --acp` exist as CLI modes. They are not the adapter.

**Why not a generic ACP adapter.** ACP (`codebuddy --acp`, and the daemon's `/api/v1/acp` SSE) would make the node spawn or speak a second agent protocol and invent session recovery for it. The OpenCode path is the v1.18.34 HTTP API, and changing it would change behavior. The WorkBuddy HTTP daemon matches the node's existing "already running on loopback" model, including the one-shot POST fence and worktree isolation. A generic ACP driver can wait until both daemons are actually accepted through that protocol.

## Operator configuration

Nothing here is applied to a machine by this change.

On the Host, add a bot listener to `host.json` and export the caller token (24+ random characters) in the service environment:

```json
"bot": {
  "listen": "<HOST_TAILSCALE_IP>:7072",
  "allowedSourceIPs": ["<GROKBOT_BOX_TAILSCALE_IP>"],
  "callers": {
    "grokbot": {"tokenEnv": "AWF_BOT_GROKBOT_TOKEN"}
  }
}
```

Omit `autoStart` to keep the bot default (auto). Set a project's `autoStart` to `false` when that project must wait for the dashboard. Restart `awf host` so it binds `bot.listen`. Leave the existing `listen` on loopback for the dashboard proxy.

On the Windows laptop, keep `awf-node` reachable from the Host over Tailscale, as [deployment](deployment.md#node-source-restriction) already describes. For WorkBuddy, install and start the daemon yourself, on loopback only, for example `codebuddy --serve` (or `codebuddy daemon install` / `daemon start` if that is how this machine is supervised). Point the node at it:

```json
"executor": "workbuddy",
"workBuddyUrl": "http://127.0.0.1:<SERVE_PORT>",
"workBuddyPermissionMode": "acceptEdits"
```

Put the serve password in `WORKBUDDY_PASSWORD`, not in the repo. `projects` stays an allowlist of existing directories. The node will not follow a non-loopback daemon URL. OpenCode nodes omit `executor` and keep `openCodeUrl`.

The bot on `grokbot-box` calls `http://<HOST_TAILSCALE_IP>:7072` with its bearer token, or the MCP endpoint on that same origin. It cannot use the dashboard Host token, and the dashboard proxy does not need a new route.
