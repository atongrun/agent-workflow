# ADR-0001: Project Boundaries

**Status:** Accepted  
**Date:** 2026-07-07

## Context

The agent infrastructure consists of three projects: Agent Workflow, Agent Bus, and AI Memory. Without clear boundaries, concerns will leak across projects, creating coupling and fragility.

## Decision

Each project owns exactly one plane:

| Project | Plane | Owns |
|---------|-------|------|
| Agent Workflow | Control | Roles, stages, state, policy, handoff artifacts |
| Agent Bus | Transport | Event delivery, durability, remote notification |
| AI Memory | Memory | Context retrieval, memory lifecycle, knowledge storage |
| Runner Adapters | Execution | Stage execution via local/remote agents |

### Rules

1. Agent Workflow **owns** workflow state. Agent Bus transports it; does not interpret it.
2. Agent Workflow **defines** event types. Agent Bus routes them; does not decide next stages.
3. Agent Workflow **produces** memory write candidates. AI Memory decides what to persist.
4. Runner adapters are swappable — no runner-specific logic in the workflow core.
5. No circular imports or runtime dependencies between the three projects.

## Consequences

- Each project can evolve independently.
- Agent Workflow core must work with only local adapters.
- Integration adapters are optional upgrades.
- Cross-project integration is documented via contracts, not implementation details.
