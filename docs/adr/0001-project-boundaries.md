# ADR-0001: Project Boundaries

**Status:** Amended by [ADR-0005](0005-high-value-model-capacity-isolation.md)
**Date:** 2026-07-07
**Last amended:** 2026-07-18

## Context

Agent Workflow, Agent Bus, and AI Memory must cooperate without sharing ownership of execution,
transport, long-term knowledge, or Workflow decisions. The original “three-plane control runtime”
framing was removed on 2026-07-11 after the product contracted to a method and handoff protocol.

## Current Decision

| Project/layer | Owns | Explicitly does not own |
|---|---|---|
| Agent Workflow | Development method, Role/Stage authority, Artifact contracts, transition and convergence semantics | Model execution, scheduling, transport, long-term memory, hosted runtime |
| Agent Bus | Endpoint and agent identity, event delivery, ACK, retry, failure propagation | Workflow Stage, Review verdict, task completion, model selection |
| AI Memory | Long-term background, historical decisions, private environment facts, preferences, cross-project knowledge | Versioned task evidence, TaskCard completeness, next-Stage decisions |
| External agent runtime | Model invocation, process lifecycle, sub-agents, and inner loops | Rewriting the versioned method contract implicitly |

Repository Truth stores the auditable Artifact chain. Run Context identifies which Artifact and
Stage are current. AI Memory may inform planning but never replaces either.

## Rules

1. No project imports another as a mandatory runtime dependency of the Agent Workflow core.
2. Agent Bus transports opaque domain payloads and never infers Workflow meaning.
3. An Executor can begin from TaskCard, repository, project `AGENTS.md`, and listed inputs without
   querying AI Memory.
4. A future external runtime may compose the projects, but no Agent Host or Plugin SDK is defined
   by this ADR.
5. Operations scripts in this repository are dogfood surfaces, not implicit core expansion.

## Consequences

- Projects can evolve independently.
- Required task facts remain auditable and recoverable.
- Private/long-term knowledge does not leak into every TaskCard.
- Future runtime integration must respect these boundaries rather than revive the removed control
  plane, ports, or adapters.
