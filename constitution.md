# Development Constitution

This file is the single source of truth for **how** a project is developed under
Agent Workflow. It is a portable set of rules — a development method and handoff
protocol — that any AI coding agent (Claude Code, Codex, OpenCode, Hermes, …) can
follow. It does **not** describe how any agent plans, calls sub-agents, executes,
or reviews internally; that is each runner's own concern.

Agent Workflow only defines: **what to do, who is responsible, what the inputs and
outputs are, and when to stop.** It never executes, schedules, or orchestrates.

---

## 1. Project Mode

Every project declares one mode before work begins:

- **Greenfield** — a new project. Start from goal → architecture → phase plan → tasks.
- **Brownfield** — an existing project. Start from a verified baseline (see §3). This
  is the default and the primary target.

## 2. Starting a New Project (Greenfield)

1. Capture the goal and hard constraints.
2. Run architecture convergence (§4) to freeze only what the first milestone needs.
3. Produce a coarse phase plan; detail only the current phase (§5).
4. Emit the first `TaskCard` and enter the execution loop (§6).

## 3. Starting from an Existing Project (Brownfield)

Before any architecture work, record a short baseline:

- capabilities already implemented **and actually verified**;
- current constraints and accepted boundaries;
- unfinished work and the next explicit milestone;
- current blockers and available test evidence.

Default path:

`Current Baseline → Next Milestone → Incremental Plan → Current TaskCard → Execute and Verify`

Existing working behavior **is** the baseline. Do not restart from whole-system
architecture or propose broad refactors just because a cleaner design exists.
Historical debt, general optimization, and future extensions go to `Later` and
cannot block the current task.

## 4. Architecture Convergence

- **Single-architect mode**: one architect plus a separate, limited self-challenge pass.
- **Dual-architect mode**: one primary architect and one goal-bounded challenger. The
  primary owns convergence.
- **Round limit**: by round **three**, architecture must be one of `frozen`,
  `frozen_with_known_risk`, or `waiting_human`. No unbounded architecture debate.
- Reopen a frozen decision only when: the current architecture blocks the milestone,
  the core path cannot run, or the project goal changed.

## 5. Progressive Planning

- Keep future phases **coarse**. Detail only the current phase.
- When all current-phase exit criteria have evidence, emit a phase-advance packet and
  only then detail the next phase.
- A `TaskCard` is the smallest executable unit: background, goal, scope, out-of-scope,
  acceptance criteria, risks.

## 6. What May Be Delegated to an Executor

A task may be handed to an execution model when it has:

- an unambiguous, bounded scope (explicit out-of-scope);
- concrete acceptance criteria;
- the inputs it needs already available.

Ambiguous goals, unresolved architecture, or missing required context must **not** be
delegated — they escalate (§7).

### 6a. Self-contained handoff

A `TaskCard` is the **complete** handoff package. An executor — a coding agent such as
OpenCode, possibly on another machine, in a fresh session with no chat history — must be
able to complete the task **from the card alone**. If the executor would need something
that lives only in the planner's conversation, that thing belongs in the card.

The card carries the task's own working context (repository path, entry points, relevant
files, what must not regress) and points to the **project's own `AGENTS.md`** for stack,
conventions, and real commands. Keep the two separate: this method (roles, workflow,
handoff rules) is portable across projects; a project's `AGENTS.md` holds that project's
facts. The card is where they meet — its acceptance and verification commands are the
project's real commands.

### 6b. Consistency gate before delegation

A card is not ready to delegate until it passes a self-check (the planner runs it; it is a
checklist, not a tool). At minimum:

- the goal is a single concrete deliverable;
- scope and out-of-scope are explicit and non-overlapping;
- every acceptance criterion is verifiable by a command or observable check;
- verification commands are the project's real commands;
- the card lets a fresh-session executor start without the planner's chat history;
- the task advances the current milestone — no unrelated refactors.

See `templates/artifacts/task-card.md` for the structure and the embedded self-check.

## 7. Rework vs. Escalation

**Rework at the execution end** is allowed only for **deterministic failures**:

- compile or test failure;
- a failed acceptance criterion;
- missing required evidence;
- a clear TaskCard violation.

**Escalate (do not silently rework)** when:

- the goal is fundamentally ambiguous after reasonable clarification;
- required context is unavailable and blocks progress;
- there is an architecture tradeoff or scope dispute;
- a decision conflicts with a frozen architecture record.

Architecture tradeoffs, scope disputes, and non-blocking improvements go into the
`DecisionPacket`. **Optional improvements never block task or phase completion.**

## 8. Reviewer Authority (Boundary)

First-line review may **only** return deterministic failures (the §7 list). It may
**not**:

- rewrite or merge code;
- approve its own implementation;
- block on style preferences, scope opinions, or non-blocking improvements.

Non-deterministic concerns are recorded as findings in the `ReviewReport` and carried
into the `DecisionPacket` for the decider — they are advisory, not blocking.

## 9. Required Artifacts per Stage

Each stage must produce a structured artifact. Agents hand off via these artifacts,
**not** free-form chat. Templates live in `templates/artifacts/`.

| Stage | Role | Required Artifact |
|-------|------|-------------------|
| plan | planner | `TaskCard` |
| implement | implementer | `ImplementationReport` |
| test | tester | `TestReport` |
| review | reviewer | `ReviewReport` |
| summarize | summarizer | `DecisionPacket` (compressed; excludes full diffs by default) |
| decide | arbiter | `Decision` (`approve` / `request_changes` / `reject` / `escalate`) |

## 10. Handoff Across Clients, Models, and Machines

- The artifact chain — not chat history — is the portable state. Any client can read
  the last artifact and produce the next.
- Roles bind to **no** model or runner. The same workflow runs under any tool.
- A tool may be swapped at any stage boundary; the contract does not change.
- Cross-machine transport and shared long-term memory are **external, optional**
  concerns (see `docs/later/`). The method here runs with only local files.

## 11. Privacy Discipline (Artifacts Are Version-Controlled)

Artifacts (TaskCards, reports, reviews, decisions) are committed to git and may be pushed
to shared/remote repos. They must therefore contain **no private or secret values**:

- **Never** put in an artifact: auth tokens/secrets, real server IPs/hostnames, SSH aliases,
  or absolute personal paths (e.g. a home directory or a specific drive path).
- **Instead** use placeholders and env vars: `$AGENT_BUS_URL`, `<coder-token>`,
  `<repo>` / repo-relative paths. Verification commands read secrets from the environment.
- Private concrete values (real IPs, tokens, machine paths, host layout) live **only in
  private long-term memory** (the operator's AI Memory), never in a committed artifact.
- The reviewer checks for leaked secrets/PII as part of every review, the same way it checks
  scope. A leaked secret is a deterministic failure (rework).
