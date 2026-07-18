# ADR-0002: Use-First Contract Design

**Status:** Amended by [ADR-0005](0005-high-value-model-capacity-isolation.md)
**Date:** 2026-07-07
**Last amended:** 2026-07-18

## Context

The initial decision proposed stabilizing a universal schema/port surface before building a runtime
engine. Real use showed that this created abstractions before the product loop was validated.

## Decision

**Use first, abstract second.** Contracts are versioned and validated, but only transition-critical
requirements demonstrated by real project use may enter the stable core.

### Rules

- The current core remains Role, Workflow, and Artifact contracts plus a stateless validation CLI.
- YAML/schema are inspectable internal representation, not the mandatory primary interface.
- Do not predefine ports, adapters, generic retry policy, arbitrary DAG semantics, or a runtime
  engine in anticipation of future integration.
- Add or tighten a contract only when a real TaskCard/Phase exposes the need and the field affects
  handoff safety, convergence, escalation, or completion.
- Validate every accepted resource and add negative tests for rejected contracts.

## Consequences

- Contracts may evolve during the alpha period rather than pretending to be universally frozen.
- Manual Artifact handoff is acceptable for initial product validation.
- Runtime, transport, memory, provider, and UI work remain external/deferred until repeated evidence
  justifies a narrow interface.
