# ADR-0004: Optional Adapters

**Status:** Accepted  
**Date:** 2026-07-07

## Context

Agent Bus and AI Memory provide valuable capabilities — durable event relay and long-term memory. But not all workflows need them. Making them hard dependencies would:
- Prevent local-only runs.
- Force users to deploy Agent Bus and set up AI Memory before using Agent Workflow.
- Create circular dependencies between projects.

## Decision

**Agent Bus and AI Memory are optional adapters.**

### Rules

1. The core MUST run with only local adapters (`LocalEventBus`, `LocalMemory`, `FilesystemArtifactStore`, `ShellRunner`).
2. Upgrading to production adapters is additive — no core code changes required.
3. No circular dependencies — Agent Workflow never imports from agent-bus or ai-memory.
4. Integration adapters live in `src/agent_workflow/adapters/` as separate modules.
5. If an external project's interface is unstable, the adapter is deferred with a clear TODO explaining what stable interface is needed.

### Local Fallback Behavior

| Adapter | Local Behavior |
|---------|---------------|
| `LocalEventBus` | Logs events to `.awf/events/events.jsonl` |
| `LocalMemory` | Returns empty context; logs candidates to `.awf/memory-candidates/` |
| `FilesystemArtifactStore` | Stores artifacts under `.awf/runs/<id>/artifacts/` |
| `ShellRunner` | No-op in Phase 0; will execute commands in Phase 1 |

### Deferred Adapters

| Adapter | Target | Phase | Blockers |
|---------|--------|-------|----------|
| AgentBusAdapter | agent-bus | 2 | Requires stable agent-bus event schema alignment |
| AIMemoryAdapter | ai-memory | 3 | Requires stable `memory.py recall` output format for context queries |

## Consequences

- Agent Workflow works out of the box with zero external dependencies.
- Production deployments add adapters incrementally.
- No risk of circular dependency or tight coupling.
- Clear migration path: local → integrated.
