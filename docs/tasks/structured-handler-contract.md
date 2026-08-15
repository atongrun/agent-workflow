# TaskCard: P1-3 Structured Handler Contract

## Task ID

AWF-USABILITY-P1-3

## Objective

Keep Agent Workflow's role and preflight handler inputs as exact argv through the Agent Bus process
boundary. Remove production command-template construction without changing delivery payloads,
handler semantics, Workflow stages, recovery, checkpoints, outboxes, or ACK-sensitive behavior.

## Frozen compatibility tuple

- Producer contract: `awf.handler-argv.v1`.
- Consumer contract: `agent-bus.listen.on-argv.v1`.
- Upgrade order: Agent Bus first, then Agent Workflow. Rollback order: Agent Workflow first, then
  Agent Bus.
- Agent Bus retains legacy `--on TYPE COMMAND`; this Workflow package emits only
  `--on-argv TYPE ARGV_JSON`. An old Bus fails during local CLI argument parsing before SSE connect
  or event delivery. There is no event-time retry or implicit fallback.

## Base and branch

- Repository: `atongrun/agent-workflow`
- Base: `main@3ba544c2e2d0c58c94e7364bc28e3b7ad1c358d2`
- Branch: `codex/structured-handler-contract`
- Cross-repository peer base: Agent Bus
  `master@6b3955d172d1d1709998af3b93205a40f2803b3a`

## Allowed changes

1. `docs/tasks/structured-handler-contract.md`
2. `docs/tasks/structured-handler-contract-implementation-report.md`
3. `scripts/awf_listen.py`
4. `tests/test_awf_role.py`
5. `tests/test_control_plane.py`
6. `tests/test_awf_preflight.py`
7. `README.md`
8. `CHANGELOG.md`
9. `ROADMAP.md`
10. `HANDOFF.md`
11. `docs/runtime-execution-architecture.md`

Do not modify `awf_role.py`, node/facade/CLI modules, delivery schemas, Agent Bus code, checkpoints,
outboxes, Feedback, recovery, provider adapters, dispatch, or workflow state.

## Required behavior

- Workflow owns `awf.handler-argv.v1`: pure builders return the current role/preflight executable,
  fixed flags, literal configuration and payload placeholders as a list of strings.
- Listener registration serializes each list as UTF-8 JSON and passes it through the pinned Bus
  `--on-argv` input for primary, implement-to-rework, terminal ready/blocked, and optional
  no-model Preflight routes.
- Executable, script, repository/config/state-root paths with spaces or Unicode remain one element;
  payload values containing quotes or metacharacters remain data after Bus placeholder rendering.
- Existing `awf_role.py` argv parsing, delivery hash/provenance gates, state-root binding, stage and
  rework authority, model invocation, checkpoint/outbox/postflight, and handler return codes remain
  unchanged.
- Workflow never reads a payload to construct the registration and does not add any ACK, requeue,
  recovery, redispatch, model-routing, or server behavior.
- Compatibility is fail-closed and operational: install/activate the pinned Bus consumer before
  starting this Workflow listener; no handler-mode auto-detection occurs after event delivery.

## Verification level

**Level B; two focused contract tests, reusing existing suites for unchanged semantics.**

- One table-driven argv/JSON test covers role and Preflight registrations with spaces, Unicode and
  a representative metacharacter while preserving all current delivery/provenance/report fields.
- One listener-routing test proves primary plus rework/terminal and optional Preflight routes all
  use `--on-argv`, never `--on`, without connecting to Bus or invoking a model.
- Existing cross-platform GitHub CI supplies Linux/macOS/Windows installed-wheel and full-suite
  coverage. The Agent Bus peer PR separately proves non-zero remains unacknowledged.

Local Mac verification is limited to compile/static/diff checks. Pytest and Ruff run only in
GitHub CI.

## Out of scope and stop conditions

- No retained business event or payload may be read, ACKed, failed, requeued, recovered,
  redispatched, or reused, including events 163, 166, or 173.
- No server protocol/state change, Workflow stage move, Phase B, Agent Host, DAG, provider registry,
  model router, generic invocation result contract, credential, private URL, or live business action.
- Stop if the change requires weakening delivery-hash, provenance, checkpoint, outbox, postflight,
  PR-tuple, business/Finding ACK separation, or the transport-only Bus boundary.

## Required output

Minimal code/tests, implementation report, Lore commits, independent PR, green CI, exact-head
independent review, fresh mergeability, merge, post-merge main/CI proof, pinned peer tuple, necessary
shared Memory, and short-branch cleanup.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/structured-handler-contract.md",
    "docs/tasks/structured-handler-contract-implementation-report.md",
    "scripts/awf_listen.py",
    "tests/test_awf_role.py",
    "tests/test_control_plane.py",
    "tests/test_awf_preflight.py",
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "HANDOFF.md",
    "docs/runtime-execution-architecture.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_awf_role.py", "tests/test_control_plane.py", "tests/test_awf_preflight.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
