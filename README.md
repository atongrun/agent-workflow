# Agent Workflow (AWF)

AWF is a small personal control plane: a Go Host adapts native Pi sessions to a protected web client, and a Go node sends explicitly authorized coding work to a pluggable local executor. OpenCode is the default executor. WorkBuddy is the other built-in executor. The web interface lives in its existing application repository; this repository contains no frontend or private handoff material.

## Active branch

Development continues on `codex/dash-magpie-provider` and branches cut from it. The `main` branch is stale: its README describes the project as terminated, and that description is wrong. This tree is the current Host, node, and Pi extension. Do not treat `main` as the product baseline.

Historical `archive/final` and tags are preserved. The retired runtime is not restored. Bot dispatch and the executor plugin are described in [bot dispatch](docs/bot-dispatch.md).

## Status

The implementation includes task/request persistence, explicit plan confirmation and start, native conversation recovery, scoped Pi tools, a native OpenCode execution adapter, separate cancellation controls, same-session Pi result reporting, optional independent review, evidence projection and bounded budgets. Automated Go tests and a real isolated Pi RPC smoke are available. A model-backed end-to-end run, native Windows execution and production deployment are separate acceptance gates, not established by mocks or cross-compilation.

## Build and test

Go 1.24 or later; the Go implementation uses the standard library only.

```sh
go test ./...
go test -race ./...
go vet ./...
go build -o bin/awf ./cmd/awf
go build -o bin/awf-node ./cmd/awf-node
GOOS=windows GOARCH=amd64 go build -o bin/awf-node.exe ./cmd/awf-node
GOOS=windows GOARCH=amd64 go build -o bin/awf.exe ./cmd/awf
```

The optional native Pi test uses `AWF_PI_BINARY=/absolute/path/to/pi go test ./internal/host -run NativePiHostIntegration -v`. Without that variable it explicitly skips. It proves the native transport/session contract, not a model-backed coding result. Pi 0.99.2 is the initial supported baseline; the restricted draft/session contract is also verified with official Pi 1.0.0; the OpenCode API adapter was checked against the v1.18.34 native contract.

## Run

1. Install and authenticate Pi and OpenCode using their official instructions. Keep model credentials on their respective machines. Never assume credentials or workspace identities transfer between machines.
2. Configure existing, dedicated project workspaces and separate Host, extension and node secrets. See [deployment](docs/deployment.md). The workspace allowlist routes jobs; native tool permissions and OS access still govern what each agent can do.
3. Run `awf host --config host.json` on the control machine. On the execution machine run `awf-node -config node.json` and the selected local daemon: `opencode serve` for the default executor, or a loopback `codebuddy --serve` when `executor` is `workbuddy`. Windows does not require WSL. Bot callers use the separate Tailscale listener in [bot dispatch](docs/bot-dispatch.md); they do not replace the dashboard `/v1` flow.
4. Put the Host behind the existing authenticated application server and protected tunnel. Browser clients never receive Host/node tokens. See the [API contract](docs/api.md).
5. Create a task with a title, converse with its restricted planning Pi, and ask Pi to propose the plan using `awf_plan`. Explicitly save an existing repository/configured execution target, confirm the current plan revision, then explicitly start that target revision. Completion of a native OpenCode turn returns real evidence to that same Pi session. Pi explains the result and submits a structured Done or Needs Changes conclusion. There is no separate reviewer in the default initial flow; Git merge remains independently unknown unless verified by an agent.

Only agents perform Git operations. The Host and node do not clone, branch, commit, push or merge repositories.

See [recovery and security boundaries](docs/recovery.md) and [remaining acceptance work](docs/roadmap.md).

The initial path uses one Pi process/session for planning, dispatch coordination and results. An independent reviewer is retained as an explicit `enableReviewer: true` deployment option, disabled by default and snapshotted only into newly created tasks.

## Native Windows CLI installation

The fresh Windows product uses a one-line ordinary-terminal bootstrap, followed
by `awf init`, `awf start`, `awf stop`, and `awf update`. Pairing and login
autostart remain separately confirmed. Installation preserves ordinary per-user
program ACLs; credentials, runtime tokens, and job state remain private.
The sole root is the Windows `FOLDERID_UserProgramFiles` known folder's `AWF`
child, normally `%LOCALAPPDATA%\Programs\AWF`. Planning never creates Programs;
native installation may create it with inherited permissions after consent.
Existing destination roots are never migrated or repaired. The historical
`%LOCALAPPDATA%\AWF` tree is ignored and untouched, with no fallback to it.

**Local source only, not yet published or natively accepted.** The unchanged
Go channel selects protocol-2 RC3, while this fresh product requires protocol 3.
A reviewed release, explicit publication approval, and native Windows acceptance
are still required. See [fresh-install design and acceptance](docs/fresh-install.md)
and [the Windows CLI contract](docs/windows-cli.md).
`awf update --all` remains unimplemented. No new runtime or hosting is required.
