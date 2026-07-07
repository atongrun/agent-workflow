# ADR-0002: Contract-First Design

**Status:** Accepted  
**Date:** 2026-07-07

## Context

Building a runtime engine before stabilizing contracts leads to rework. Schema changes break implementations. Runner integrations become tightly coupled to workflow internals.

## Decision

**Stabilize schemas and protocols first, then build the runtime engine.**

### Phase Ordering

1. Define all JSON Schemas and resource specifications.
2. Define port interfaces (Protocols).
3. Build validation tooling.
4. Only then implement the runtime engine.

### Rules

- Schemas are versioned (`agent-workflow/v1alpha1`).
- All resources pass `awf validate` before being accepted.
- Port interfaces are Python Protocols — no concrete dependency.
- Runner-specific logic does not enter core workflow definitions.

## Consequences

- Phase 0 produces a fully validated contract surface with no runtime engine.
- External systems can implement against stable schemas without waiting for the engine.
- Breaking changes to schemas require a version bump.
- The runtime engine (Phase 1+) can assume valid input.
