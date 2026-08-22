# Phase 5-01 Capability-First Init Closeout

## Result

`PASS` candidate at `d9f470c`. Phase 5-01 is implementation/review complete on Draft PR #121;
integration into `main` remains an owner boundary. Phase 5-02 did not start.

## Exact user journey

```text
awf init
  Checking dependencies...
  ✓ Agent Workflow
  ✓ Agent Bus
    ✓ agent-bus.listen.on-argv.v1
  ✓ Git / GitHub

  Detected agent tools:
  ✓ OpenCode
  ✓ Pi
  ○ Codex

  Recommended setup:
  Architect  pi / tool-default
  Coder      opencode / tool-default
  Reviewer   opencode / tool-default

  Press Enter to accept, or C to customize.
  Finding: off
  Ready.

awf doctor
awf status
awf start | awf stop | awf drain | awf logs
```

`awf init` configures only the current machine and may select zero, one, two or three product roles.
Non-interactive flags support the same bindings. Existing TaskCard-bound setup remains available as
`awf enroll` and the compatibility `awf init --card ...` path.

## Role and model bindings

| Role | Agent Tool support |
|---|---|
| Architect | Pi |
| Coder | OpenCode |
| Reviewer | OpenCode, Pi, Codex |

One installed/authenticated Agent Tool may back several roles. Each role still owns a different
profile, lifecycle identity, state node/listener lease and deterministic checkout. Same OpenCode and
same explicit model for Coder/Reviewer is accepted with one informational independence warning.

Model selection is either:

- `tool-default`: persisted explicitly in machine config; profile `model` is empty; no model flag is
  rendered; or
- `explicit`: one opaque tool-native reference such as `opencode-go/deepseek-v4-flash`; profile and
  renderer preserve it unchanged.

AWF does not authenticate tools, edit provider endpoints/credentials/defaults, parse private tool
configuration, query remote model catalogs or silently fall back from explicit to default.

## Pi Architect

Pi Architect is now a real `InvocationSpec`/closed-renderer capability. It binds one trusted context
file, uses `--no-session`, `--no-approve` and only `read,grep,find,ls`, and returns TaskCard Markdown
on stdout. A separate trusted helper validates identity, postflight/report paths, secret shapes,
UTF-8, repository containment and create-only destination before returning a non-authorizing
Artifact fact. Phase 5-01 does not connect this seam to Runtime application/Store/transport.

## Workspace, Agent Bus and Finding

- Init stages one full local clone per role, preserves exact source HEAD and trusted upstream/fork
  remotes, and rejects dirty/drifted existing destinations. Multi-role same-path rejection is not
  weakened.
- Profile/config replacement is a staged recoverable batch. Four injected fresh/replace fault rows
  prove no split binding remains after profile/config failure.
- Agent Bus compatibility is capability-first: `listen --help` must expose `--on-argv`; readiness
  records executable/help provenance before health checks. No Agent Bus installation/server action
  occurs.
- Finding profile omission means off: no prompt, capture or normal status Feedback. Explicit
  `finding_enabled=true` preserves existing Phase A only.

## Evidence

- Focused: `470 passed, 2 skipped`.
- Full: `913 passed, 5 skipped`.
- Local Ruff/format/compileall/resource/diff gates: PASS.
- Installed wheel unrelated-cwd verification: PASS, SHA-256
  `a9d44e394df6bc68a1f306b56d949a64213e89b289ca21f318499609f8f2d9b5`.
- Ordinary CI `32574488604`: PASS.
- Binary Feasibility `32574488742`: PASS.
- Independent L2 Review: initial one P1, repaired and focused re-review `PASS`.

## Remaining limits and stop

- A formal Agent Bus client release carrying `agent-bus.listen.on-argv.v1` remains required before
  real Phase 5 dogfood; Phase 5-01 intentionally does not publish it.
- Pi Architect is not invoked by `awf run` in this milestone.
- Machine role checkouts do not silently update after init.
- No TaskCard, model, event, ACK/retry/requeue, Runtime default, migration, launcher, release or
  legacy deletion occurred.
- Only a separately frozen owner-approved Phase 5-02 TaskCard may implement fresh
  `awf run <TaskCard>`. Stop here.
