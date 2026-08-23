# Agent Workflow

Agent Workflow turns an approved, committed Plan into a safe serial coding loop:

```text
Human approves Plan
  → Pi Architect creates one TaskCard
  → Coder implements it
  → Reviewer checks the exact commit
  → Pi Architect approves completion
  → CI passes and AWF merges the PR
  → AWF reads the new main
  → Pi creates the next TaskCard, returns BLOCKED,
    or completes the milestone
```

The Human owns the Plan and authorization. Agent Workflow owns the loop, trusted Git/PR operations,
validation, and durable facts. Agent Bus is transport only.

Current release: [`v0.4.0-rc.1`](https://github.com/atongrun/agent-workflow/releases/tag/v0.4.0-rc.1)

## What v0.4.0-rc.1 supports

- One-card execution with `--one-card`.
- Strictly serial multi-card execution with `--milestone`.
- A fresh Pi Architect decision after every merge.
- Windows OpenCode Coder.
- OpenCode, Pi, or Codex Reviewer.
- Existing Fast/Deep Preflight before model authoring and remote dispatch.
- Trusted TaskCard validation, isolated model workspaces, commit, push, PR, CI, and merge.
- Reviewer `PASS`, deterministic `REQUEST_CHANGES`, bounded rework, and `BLOCKED`.
- Durable PlanFact, PlanRun, CompletedCardFact, status, outbox/inbox, and fail-closed replay guards.

It is not a generic multi-agent framework, scheduler, concurrent task queue, or remote supervisor.

## Requirements

- Python 3.11+
- Git
- [GitHub CLI](https://cli.github.com/) authenticated with `gh auth login`
- [Agent Bus v0.3.1](https://github.com/atongrun/agent-bus/releases/tag/v0.3.1)
- The Agent Tools used on this machine, already installed and authenticated

Supported role bindings:

| Role | Agent Tool |
|---|---|
| Architect | Pi |
| Coder | OpenCode |
| Reviewer | OpenCode, Pi, or Codex |

One machine may host any subset of roles. Each RoleBinding still gets its own profile, token,
workspace, listener, and lifecycle identity.

## Install

Install the release wheel directly from GitHub:

```bash
python -m pip install \
  https://github.com/atongrun/agent-workflow/releases/download/v0.4.0-rc.1/agent_workflow-0.4.0rc1-py3-none-any.whl

awf version
```

Expected output:

```text
awf 0.4.0rc1
```

Agent Workflow does not install or configure Agent Bus, GitHub authentication, or model-provider
credentials.

## Configure Agent Bus access

Create the owner-only configuration file at `~/.config/awf/dispatch.env`:

```dotenv
AGENT_BUS_URL=http://your-agent-bus-host:8800
AWF_ARCH_TOKEN=architect-token
AWF_CODER_TOKEN=coder-token
AWF_REVIEWER_TOKEN=reviewer-token
```

Optional executable overrides are `AWF_BUS_BIN`, `AWF_OPENCODE_BIN`, `AWF_CODEX_BIN`, `AWF_PI_BIN`,
and `AWF_GH_BIN`.

On macOS/Linux, make the file owner-only:

```bash
chmod 600 ~/.config/awf/dispatch.env
```

Windows uses an owner-only ACL instead of POSIX file mode.

## 1. Initialize each machine

Run this once in the downstream repository on every machine that hosts a role:

```bash
awf init --repo .
```

Choose the local roles and their Agent Tools/models. Init then:

1. validates Git, GitHub CLI, Agent Bus, and selected tools;
2. creates a separate profile and checkout for each local RoleBinding;
3. installs or reconciles its managed listener;
4. registers the existing Preflight handlers;
5. prints `Ready` only after the selected listeners are running and connected.

Init manages only the current machine. Run it separately on the Architect/Reviewer machine and the
Coder machine when using a cross-machine setup.

## 2. Commit a Plan

The Plan is Human-owned repository truth. Commit it under a tracked path such as:

```text
docs/plans/my-milestone.md
```

The normal path does not require the Human to write TaskCards. Pi creates one TaskCard at a time
from the exact committed Plan and current upstream `main`.

## 3. Start the loop

After explicit Human authorization, the initiating Agent calls one of these commands.

Run exactly one card:

```bash
awf plan start \
  --repo . \
  --plan docs/plans/my-plan.md \
  --one-card
```

Run a serial milestone loop:

```bash
awf plan start \
  --repo . \
  --plan docs/plans/my-milestone.md \
  --milestone
```

Use `--coder-tool`, `--coder-model`, `--reviewer-tool`, and `--reviewer-model` when the PlanRun must
bind explicit execution selections. The Architect selection comes from its configured RoleBinding.

The start command returns after the durable Architect event is accepted. The initiating chat or
shell does not need to stay alive.

## 4. Observe or stop

Status is passive and never runs Preflight, invokes a model, ACKs, requeues, resumes, or merges:

```bash
awf status --repo . --explain
```

It shows local roles, listeners, workspaces, queues, PlanRun, current/last card, recorded Fast/Deep
facts, PR/merge/completion, and the first blocker.

Stop records no-new-work, requires safe queue authority, and then stops only the selected local
listeners:

```bash
awf stop --repo .
```

## Failure behavior

Agent Workflow fails closed. It does not guess after an ambiguous model or merge side effect, and it
does not silently weaken Plan, TaskCard, role, artifact, Git, or PR identity checks.

The release candidate intentionally does not provide:

- automatic recovery after an Architect or Coder process crash;
- provider-session restoration or partial workspace takeover;
- automatic correction or same-card retry for invalid Architect output;
- Human stop/resume of an active milestone;
- concurrent milestones, a TaskCard queue, or Plan hot updates;
- Runtime v2 Store default migration.

Use `awf status`, `awf doctor --explain`, and `awf logs` for diagnosis. Do not manually ACK, requeue,
or replay a failed business delivery unless a separately authorized recovery procedure says to do
so.

## Support and compatibility commands

The normal product journey is:

```text
awf init
awf plan start
awf status
awf stop
```

`doctor`, `logs`, top-level `start`, raw `drain`, `node ...`, `setup`, `run`, `resume`, upgrade,
uninstall, validation, and inspection remain available for support, administration, compatibility,
or repository development. See `awf --help` and the current [handoff](HANDOFF.md).

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
python -m pytest -q
```

Useful project references:

- [Constitution](constitution.md) — normative authority and role boundaries
- [Runtime v2 semantic contract](docs/runtime-v2-semantic-contract.md)
- [Runtime v2 development plan](docs/plans/runtime-v2-development-plan.md)
- [Phase 5-02 closeout](docs/tasks/phase5-02-architect-one-card-closure-report.md)
- [Phase 5-03 closeout](docs/tasks/phase5-03-architect-led-plan-loop-report.md)
- [v0.4.0-rc.1 release notes](docs/releases/v0.4.0-rc.1.md)

## License

MIT — see [LICENSE](LICENSE).
