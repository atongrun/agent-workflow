# Agent Workflow

Agent Workflow lets an AI Architect safely execute an approved repository Plan through a serial
Coder → Reviewer → merge loop. It generates one TaskCard at a time and continues until the
milestone is complete or blocked.

```text
Human + Agent agree on a Plan
            ↓
Human approves and commits it
            ↓
Human authorizes the Agent to use AWF
            ↓
Architect → Coder → Reviewer → Architect decision → CI → Merge
            ↓
AWF reads the new main
            ↓
next TaskCard / MILESTONE_COMPLETE / BLOCKED
```

**The Human owns the Plan and authorization. AWF owns the execution loop.**

Humans do not normally write TaskCards or manually coordinate Coder, Reviewer, PRs, merges, and the
next card. Agent Bus carries events between machines; it is transport, not workflow authority.

Current release: [`v0.4.0-rc.1`](https://github.com/atongrun/agent-workflow/releases/tag/v0.4.0-rc.1)

## The normal workflow

### 1. Install

Prerequisites:

- Python 3.11+
- Git and an authenticated [GitHub CLI](https://cli.github.com/)
- [Agent Bus v0.3.1](https://github.com/atongrun/agent-bus/releases/tag/v0.3.1)
- the Agent Tools used on this machine, already installed and authenticated

Install Agent Workflow from the GitHub release:

```bash
python -m pip install \
  https://github.com/atongrun/agent-workflow/releases/download/v0.4.0-rc.1/agent_workflow-0.4.0rc1-py3-none-any.whl

awf version
```

Expected output:

```text
awf 0.4.0rc1
```

AWF currently expects an owner-only `~/.config/awf/dispatch.env` containing the Agent Bus URL and
role tokens:

```dotenv
AGENT_BUS_URL=http://your-agent-bus-host:8800
AWF_ARCH_TOKEN=architect-token
AWF_CODER_TOKEN=coder-token
AWF_REVIEWER_TOKEN=reviewer-token
```

Use `chmod 600 ~/.config/awf/dispatch.env` on macOS/Linux. Windows requires an owner-only ACL.

### 2. Initialize each participating machine

Run this in the downstream repository:

```bash
awf init
```

Choose the roles hosted on that machine and their Agent Tools/models. Init checks the prerequisites,
creates separate role workspaces, installs and starts the managed listeners, waits for Agent Bus
connectivity, and prints `Ready` only when the selected roles can receive work.

Roles describe responsibilities, not permanent Agent Tool bindings. A machine may host any subset
of them. The published `v0.4.0-rc.1` release ships the narrow matrix below; unreleased RC.2 main
has completed deterministic conformance and fresh non-business CLI/model smoke for the full matrix:

| Role | Published RC.1 | Unreleased RC.2 main |
|---|---|---|
| Architect | Pi | Pi, OpenCode, Codex |
| Coder | OpenCode | Pi, OpenCode, Codex |
| Reviewer | OpenCode, Pi, Codex | Pi, OpenCode, Codex |

The RC.2 matrix does not claim the two official real-machine topology acceptances or release
publication; those remain separate gates. Run `awf init` separately on each machine in a
cross-machine setup.

### 3. Discuss and commit a Plan

The Human and an Agent discuss the goal and write a Plan in the downstream repository, for example:

```text
docs/plans/my-milestone.md
```

The Human reviews, approves, and commits that Plan. It must match the current upstream `main`.

The Human does **not** write the TaskCards. The configured Architect creates them dynamically from
the approved Plan and the latest main, one card at a time.

### 4. Authorize the Agent to run it

The normal Human interaction is a request like:

> This Plan is approved and committed. Use Agent Workflow to execute it. Continue until the
> milestone is complete or BLOCKED.

After that explicit authorization, the initiating Agent on unreleased RC.2 main invokes the
Agent-native MCP facade (`awf-mcp` or `awf mcp`) and calls `start_plan`. The MCP adapter is a thin
stdio entry over the same installed authority; it does not own transport, ACK, replay, or merge
state. `awf plan start` remains the installed debugging and compatibility contract:

```bash
awf plan start \
  --plan docs/plans/my-milestone.md \
  --milestone
```

`--milestone` is the normal product path. After each merge, AWF reads the new upstream main and asks
a fresh Architect for the next TaskCard, `MILESTONE_COMPLETE`, or `BLOCKED`.

The start command returns after the durable Architect start is accepted. The initiating chat or
shell does not need to remain open.

The same product projection is available to an initiating Agent as MCP `get_status` and to an
operator as `awf plan status --run <plan-run-id>`. Both are read-only. The currently exposed
approval/replacement MCP operations fail closed until their exact Plan authority is implemented;
they do not provide a retry or replay path.

MCP lifecycle operations require a separate explicit Human instruction for that exact PlanRun; a
Plan-start authorization never doubles as permission to stop or deinitialize local bindings.

For a deliberately bounded single-card run, the current CLI also supports `--one-card` instead of
`--milestone`.

### 5. Observe

```bash
awf status
```

Status is read-only. It shows the participating roles, current card, last completion, queues,
Preflight result, PR/merge progress, and the first blocker. It does not run diagnostics or advance
the workflow.

When the machine should stop accepting work:

```bash
awf stop
```

Stop first checks that stopping the selected local roles is safe, then stops their managed
listeners.

## How the loop works

AWF runs only one active TaskCard at a time:

1. The Architect reads the committed Plan and exact current main.
2. The Architect creates one complete TaskCard.
3. The Coder implements it in an isolated workspace.
4. Reviewer checks the exact pushed commit and returns `PASS`, `REQUEST_CHANGES`, or `BLOCKED`.
5. The Architect makes the completion decision.
6. AWF verifies CI and performs the trusted merge.
7. AWF reads the new main before asking the Architect what comes next.

There is no pre-generated TaskCard queue and no concurrent milestone scheduler.

## How safety works

AWF stops instead of guessing when it cannot prove the outcome of a model invocation, identity
check, Git/PR operation, or merge.

Key guarantees:

- the committed Plan identity is frozen for the run;
- TaskCards are generated one at a time from current repository truth;
- Reviewer and CI are bound to exact commits;
- model workspaces do not own trusted GitHub credentials or merge authority;
- merge effects are recorded and verified instead of blindly replayed;
- workflow state and completed-card evidence are durable;
- ambiguous or invalid outcomes fail closed.

Agent Bus transports the events and ACKs. AWF remains the authority for workflow state,
authorization, review decisions, and completion.

## Troubleshooting

Start with the passive view:

```bash
awf status --explain
```

Run active diagnostics or inspect listener logs only when needed:

```bash
awf doctor --explain
awf logs
```

Do not manually ACK, requeue, or replay a failed business delivery unless a separately authorized
recovery procedure explicitly requires it.

## Current limitations

This release candidate does not yet provide:

- automatic recovery after an Architect or Coder process crash;
- provider-session restoration or partial workspace takeover;
- automatic correction or same-card retry for invalid Architect output;
- stop-and-resume for an active milestone;
- concurrent milestones or Plan hot updates;
- Runtime v2 Store default migration.

## Advanced and support commands

The normal workflow is intentionally small:

```text
awf init
Agent invokes awf plan start
awf status
awf stop
```

Compatibility, administration, and development commands remain available. Use:

```bash
awf --help
```

The current Plan-start CLI defaults Coder and Reviewer to OpenCode with their tool defaults. When a
run uses another configured Reviewer or an explicit model, the initiating Agent must pass the
matching optional overrides shown by `awf plan start --help`.

For deeper implementation and evidence details, see:

- [Constitution](constitution.md)
- [Current handoff](HANDOFF.md)
- [Runtime v2 semantic contract](docs/runtime-v2-semantic-contract.md)
- [Runtime v2 development plan](docs/plans/runtime-v2-development-plan.md)
- [Phase 5-03 loop closeout](docs/tasks/phase5-03-architect-led-plan-loop-report.md)

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
python -m pytest -q
```

## License

MIT — see [LICENSE](LICENSE).
