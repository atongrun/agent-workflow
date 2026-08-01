# Runtime Preflight architecture

## Boundary

Preflight is part of the non-core operations surface. It does not change the stateless `awf` core,
Agent Bus protocol, Workflow stage semantics, model runner, or event retry policy. Every external
command is structured argv executed by `scripts/awf_executor.py`.

`scripts/awf_preflight.py fast` is the loop entry gate. It is read-only and emits
`awf.preflight-report.v1`. It never sends or listens for an event, invokes a model, advances a run
ledger, changes Git state, creates a PR, or writes a cache/report file. Its layers cover:

- runtime and the unified executor boundary;
- strict operations configuration and permissions;
- credential-free proxy configuration, dual `NO_PROXY`, and conditional Tailscale reachability;
- Agent Bus doctor and role-scoped pending counts;
- local Git readability, canonical upstream/fork remotes, and fork-only push dry-run;
- read-only GitHub authentication/repository access;
- model-tool `--version` execution without a prompt or model call;
- authority manifest and optional run-ledger/context-packet readability.

Fast is host-local. Operators run it on each participating machine and explicitly pass that
runtime's selected CLI with `--model-tool`. Preflight does not map roles to products: Pi, Codex,
Claude Code, OpenCode, or another compatible executable can be selected without changing source
code. The probe runs only `<selected-tool> --version` and never starts a model.

TaskCard authoring and remote dispatch are separate decisions. Local authoring can proceed when its
runtime/configuration/Git/control-plane prerequisites pass even if a remote-only probe is down.
Remote dispatch additionally requires every remote layer plus a current Deep proof.

## Deep trigger and cache

Deep mode is explicit. The caller uses it for the first real remote dispatch, after a material
configuration/network/transport change or failure, or after the proof TTL expires. A SHA-256
fingerprint binds the proof to runtime, repository, roles, remotes, strict configuration, and proxy
facts; only the hash is reported. The cached report also carries an HMAC derived from both scoped
role tokens and is accepted only after full Deep evidence is revalidated. A mismatch, tamper, or expiry makes Fast return
`required_next_action=run_deep_preflight`.

Deep writes its credential-free proof below the platform control-plane state root. Fast only reads
that cache. `--force` bypasses a current cache after a failure or deliberate environment check.

## Disposable transport proof

Role listeners started with `--enable-preflight` register two additional no-model control handlers:

1. `control:awf-preflight-v1` invokes `handle-request`.
2. `control:awf-preflight-result-v1` invokes `handle-result`.

Before sending, Deep requires both participating role pending counts to be exactly zero. It
therefore cannot select, print, or handle a retained historical event. A cryptographically unique
probe ID is carried by one request and one result event.

The target request handler validates the event type, probe, fingerprint, and listener role; starts
a trivial child Python subprocess through the unified executor; sends the bounded result payload;
and returns success. Agent Bus automatically ACKs the request only after that success. The source
result handler repeats the identity/role/child checks, atomically writes source evidence, and
returns success, allowing the result event's automatic ACK.

Agent Bus v0.3 splits the handler template once, replaces every standalone placeholder with one raw
argv element, and executes with `shell=False`. The malicious-metacharacter contract is locked by the
Preflight tests; handler-side identity validation is an additional semantic gate, not the injection
boundary.

The initiating command accepts the proof only when both event IDs and both child results match and
both role pending counts return to zero. Handler success plus matching durable evidence plus a zero
post-baseline is the v1 ACK evidence. The report labels it as inferred because Agent Bus v1 has no
read-only per-event ACK-status endpoint. No code path invokes `agent-bus ack`, `read`, `requeue`, or
redispatch. Failure stays fail-closed and never becomes dispatch authority.

## Listener deployment rule

Existing listeners must be restarted on the new code with `--enable-preflight` before Deep can
pass. If a non-default
`--state-root` is used on the source machine, the source listener and initiating Deep command must
receive the same path. Target evidence stays under that target listener's own state root and is not
used as a cross-machine file pointer; the reply payload carries the bounded proof facts.

## Report decisions

The report exposes four next actions:

- `fix_fast_preflight`: a required local or remote readiness layer failed;
- `author_taskcard`: the loop may proceed through architecture and frozen TaskCard authoring;
- `run_deep_preflight`: remote Fast checks pass but no current bound proof exists;
- `remote_dispatch_allowed`: all Fast checks and the bound Deep proof pass.

Endpoint values, tokens, credentials, raw process output, and absolute config/cache paths are never
included in the report.
