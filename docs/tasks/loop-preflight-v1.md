# TaskCard: Add a fail-closed loop-start Preflight

## Intent

Give every Agent Workflow loop one inexpensive, read-only readiness decision before architecture
and TaskCard authoring, plus a narrowly triggered disposable transport proof before remote dispatch.
The report must distinguish local authoring readiness from remote-dispatch authority.

## Frozen baseline

- Upstream: `origin/main`
- Commit: `58613cfd52f2b3afad0fda84e0c54d2486213e17`
- Feature branch: `codex/loop-preflight-v1`
- Runtime command boundary: every child process goes through `scripts/awf_executor.py`.

## Allowed paths

- `scripts/awf_preflight.py`
- `scripts/awf_handoff_check.py`
- `scripts/awf_listen.py`
- `tests/test_awf_preflight.py`
- `tests/test_runtime_command_boundary.py`
- `docs/runtime-preflight-architecture.md`
- `docs/tasks/loop-preflight-v1.md`
- `docs/tasks/loop-preflight-v1-implementation-report.md`
- `README.md`

## Required behavior

### Fast mode

1. Remains read-only: no Agent Bus `send`, `listen`, `ack`, `requeue`, or model invocation; no Git,
   GitHub, ledger, or repository mutation.
2. Checks, with bounded duration and credential-safe evidence:
   - detected runtime and unified executor;
   - strict configuration existence, ownership/ACL, required role tokens, and executable paths;
   - proxy values, both `NO_PROXY` variants, Tailscale status/reachability when the Bus endpoint is
     in the tailnet range;
   - Agent Bus health and per-role pending counts through read-only CLI operations;
   - Git worktree/remotes/authentication and contribution-fork `push --dry-run`;
   - GitHub CLI authentication and repository readability;
   - configured model-tool executable/version without starting a model;
   - authority manifest and optional Workflow run ledger/context-packet readability.
3. Emits `awf.preflight-report.v1` JSON with `allow_taskcard_authoring`,
   `allow_remote_dispatch`, `required_next_action`, overall status, per-layer status/error code/
   duration/evidence, and Deep-evidence freshness metadata.

### Deep mode

1. Runs only when explicitly selected after Fast passes. It is required for the first real remote
   dispatch, after network/config/transport failure or material fingerprint change, and when the
   previous proof TTL expires.
2. Fails closed unless both participating role queues have a zero pending baseline. This prevents
   the proof listeners from reading or handling any historical event.
3. Uses a cryptographically unique disposable probe ID and event types. It proves the real
   Agent Bus -> listener -> handler -> child subprocess -> result path in both directions.
4. Records request/reply event IDs, handler/child results, pending before/after, and automatic ACK
   evidence. It never calls manual ACK, reads event payloads through a historical-event API,
   requeues, redispatches, or invokes a model.
5. Persists only credential-free proof metadata needed for TTL reuse. Any ambiguity, timeout,
   non-zero handler, pending drift, missing ACK evidence, or mismatched probe identity denies remote
   dispatch.

### Compatibility

`scripts/awf_handoff_check.py` remains callable with its existing arguments and delegates to Fast
Preflight, rendering a legacy human checklist from the versioned report. No new dependency and no
Agent Bus protocol change are allowed.

## Decision semantics

- `allow_taskcard_authoring=true` only when the local/runtime, configuration, Git-readiness, and
  Workflow-control layers needed to author a safe TaskCard pass.
- `allow_remote_dispatch=true` only when every required Fast layer passes and a required Deep proof
  is current and fingerprint-matched.
- `required_next_action` is exactly one of `fix_fast_preflight`, `author_taskcard`,
  `run_deep_preflight`, or `remote_dispatch_allowed`.
- Errors use stable, layer-prefixed machine codes and never contain endpoint, token, credential,
  private path, or raw command output.

## Test matrix

| Area | Required coverage |
| --- | --- |
| Report contract | Exact format, decisions, stable layer fields, durations, JSON output |
| Fast purity | No mutating Bus verbs, no listener, no model invocation, no filesystem writes |
| Configuration | Missing/unsafe/unknown config, role token presence, secret-safe diagnostics |
| Network | Proxy credential rejection, dual `NO_PROXY`, tailnet conditional checks, timeouts |
| Bus | Doctor/pending success, noninteger pending, per-role failure, no historical mutation verbs |
| Git/GitHub | Remote binding, upstream read-only, fork-only push dry-run, auth/repo failures |
| Model tools | Missing/non-executable/version failure without execution or prompt input |
| Control plane | Authority format/forbidden set, empty ledger root, valid optional ledger, corruption |
| Deep trigger | First dispatch, forced/failure, expired TTL, fingerprint drift, current proof reuse |
| Deep chain | Unique request/reply, zero baselines, listener/handler/child/result, both ACKs, zero after |
| Deep failure | Nonzero baseline, wrong probe, timeout, handler failure, pending drift all fail closed |
| Compatibility | Existing handoff arguments and PASS/FAIL exit behavior map to Fast report |
| Cross-platform | PowerShell, Git Bash, macOS zsh argv/path behavior remains executor-owned |

## Verification

- `python -m pytest -q tests/test_awf_preflight.py tests/test_runtime_command_boundary.py`
- `python -m pytest -q`
- `ruff check .`
- `ruff format --check .`
- `python -m compileall -q scripts src tests`
- `awf validate roles && awf validate workflows && awf validate examples`

## Prohibited actions

- Do not send a live proof event during implementation or tests.
- Do not inspect, read, ACK, requeue, redispatch, or otherwise mutate historical Agent Bus events.
- Do not invoke a model.
- Do not push, open a PR, merge, delete branches, or change remote infrastructure.
- Do not add an Agent Host, generic workflow engine, dependency, or Agent Bus protocol feature.
