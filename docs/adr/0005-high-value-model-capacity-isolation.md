# ADR-0005: High-Value Model Capacity Isolation

**Status:** Accepted
**Date:** 2026-07-18

## Context

Agent Workflow is a development method and handoff protocol for AI-assisted software work. The repository already proves a thin validation core, structured artifacts, and dogfooded runner surfaces, but the product question is no longer whether a workflow contract exists. The question is what problem the contract should solve.

The product is not trying to minimize all model usage, avoid high-value models during its own development, bind to one vendor, or become a generic multi-agent engine. Its job is to help downstream projects concentrate high-value model capacity where it matters and keep lower-cost models on the repeatable path.

That distinction only works if the repository keeps three things separate:

- the stable method and artifact contract in git;
- the current run state for one workflow execution;
- long-term background that belongs in AI Memory.

## Decision

Agent Workflow is a **layered development method, structured handoff protocol, and convergence rule set** for AI software development.

Its stable core is:

- Role and Stage semantics;
- Artifact contracts;
- transition and rework rules;
- blocked, escalation, and completion rules;
- forced convergence and deterministic rework behavior;
- the boundary between repository truth, run context, and AI Memory.

It is not:

- a model;
- a generic coding agent;
- a hosted SaaS;
- a long-term memory system;
- a cross-machine transport system;
- a general DAG or workflow engine;
- a runtime that owns execution, scheduling, or inner loops.

## Unified Terms

Use these canonical terms in product-facing docs:

- `high-value model`
- `lower-cost model`

These are the primary terms because they are vendor-neutral, describe the actual tradeoff, and avoid implying that the product is only about expense. `high-value model` covers capability, scarcity, and cost where those matter. `lower-cost model` covers cheaper or more abundant execution capacity without overcommitting to a specific provider, price sheet, or token API.

Avoid product definitions that optimize only for:

- total token reduction;
- fewer model calls in the abstract;
- one provider’s naming scheme;
- a permanent “always use the cheap model” rule.

## Modes

Agent Workflow has two distinct operating modes.

### Infrastructure-development mode

This mode applies when developing Agent Workflow itself, Agent Bus, AI Memory, a future Agent Host, or other foundational infrastructure.

In this mode, using a high-value model is normal and often desirable for:

- architecture design;
- critical implementation;
- security boundaries;
- failure analysis;
- strong review;
- real-environment validation;
- high-risk decisions.

This repo must not claim that its own development should minimize high-value model usage. The infrastructure itself is worth strong model investment.

### Downstream-operation mode

This mode applies when Agent Workflow is used to run another project.

In this mode, high-value models are reserved for:

- initial architecture planning;
- freezing or reopening architecture;
- high-risk change decisions;
- blocked escalation;
- milestone or phase acceptance;
- evidence that the current lower-cost path cannot resolve.

Lower-cost models should handle the routine path:

- task decomposition;
- TaskCard generation;
- implementation;
- testing;
- first-line review;
- deterministic rework;
- artifact cleanup;
- ordinary progress through the workflow.

The product objective is therefore to reduce downstream dependence on scarce high-value capacity, not to minimize all model usage everywhere.

## Repository Truth, Run Context, and AI Memory

The repository must remain the source of truth for versioned, auditable project facts.

| Boundary | Contains | Does not contain |
|---|---|---|
| Repository truth | Code, README, `AGENTS.md`, architecture records, phase plans, TaskCards, reports, decisions, tests, PR evidence | Private machine details, unversioned guesses, hidden session context |
| Run context | Current stage, current TaskCard, current artifact, branch, commit, PR, role, retry state, escalation state | Long-term project history, broad background, personal environment facts |
| AI Memory | Long-term background, historical decisions, private environment info, cross-project knowledge, recovery context, user preferences | The authoritative workflow state, replacement artifacts, or direct stage control |

TaskCards are self-contained execution contexts. A fresh-session executor should be able to start from:

- the TaskCard;
- repository contents;
- the project’s `AGENTS.md`;
- any explicit inputs listed in the card.

If an executor needs a fact to succeed, that fact belongs in the TaskCard or another versioned artifact. AI Memory is an upstream source for planning and compression, not a required runtime dependency for execution.

Planner and architect roles may consult AI Memory, but their job is to compress only the facts needed for the current task into the TaskCard. They should not copy the whole memory history into every handoff.

## Normal Path

The intended downstream loop is:

```text
User goal
→ Architecture / Planning
→ PhasePlan
→ TaskCard
→ Dispatch
→ Execute
→ Test
→ Review
→ Decision
→ Merge or deterministic rework
→ Next TaskCard
```

The normal path should stay on lower-cost models whenever the current evidence is sufficient.

## Upgrade Path

High-value model usage is justified when the lower-cost path cannot produce a reliable decision.

Typical upgrade conditions:

- the goal is genuinely ambiguous;
- the TaskCard cannot be formed under the frozen architecture;
- architecture must be reopened;
- a reviewer returns `BLOCKED`;
- deterministic rework repeats beyond a bounded threshold;
- the change is in a predeclared high-risk area;
- a phase or milestone reaches its acceptance point;
- the project goal changed;
- the evidence is insufficient for a reliable decision.

Do not automatically upgrade for:

- routine test failures;
- unmet acceptance criteria that still fit the current path;
- allowed-path violations;
- missing report fields that deterministic rework can fix;
- ordinary `REQUEST_CHANGES`;
- style preference;
- non-blocking optimization;
- reviewer opinion that is not a deterministic failure.

## Effect on Artifacts and Workflow Design

This decision reinforces the existing artifact chain.

- `TaskCard` becomes the compressed operational boundary for a fresh executor.
- `ImplementationReport`, `TestReport`, `ReviewReport`, `DecisionPacket`, and `Decision` remain the auditable progression record.
- AI Memory remains outside the artifact chain and only informs it indirectly.
- Repository truth stays versioned in git.
- Run context remains ephemeral and should not be confused with long-term project state.

The workflow should continue to favor deterministic rework over escalation when the failure is concrete and local.

## Non-Goals

- Do not turn Agent Workflow into a generic multi-agent framework.
- Do not add a model-selection engine or pricing engine to the core.
- Do not require precise token, price, or quota APIs.
- Do not make Agent Bus or AI Memory part of the core contract.
- Do not encode vendor names in the product definition.
- Do not make the repository depend on a future Agent Host.
- Do not redefine operations scripts as workflow core.

## Risks

- The repo can still drift into vendor-specific language if docs are not kept in sync.
- Run context can be over-expanded until it starts looking like a second memory system.
- TaskCards can become too large if they try to duplicate AI Memory instead of compressing it.
- Metrics can become misleading if they pretend exact token or cost data is available everywhere.
- Downstream usage can regress into “high-value by default” if escalation rules are not kept explicit.

## Follow-Up Verification

Use the product metrics doc to validate the first dogfood runs with observable counts:

- how many TaskCards completed;
- how often high-value models were needed;
- which roles triggered them;
- why the upgrade happened;
- how often deterministic rework closed without escalation.
