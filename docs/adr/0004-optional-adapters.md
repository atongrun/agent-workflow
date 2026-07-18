# ADR-0004: Optional Adapters (Historical)

**Status:** Superseded on 2026-07-11
**Date:** 2026-07-07

## Historical Decision

The initial architecture proposed optional Runner, EventBus, Memory, and ArtifactStore ports with
local and external adapters. That design was removed before becoming the product baseline.

## Current Direction

Agent Workflow is a development method, Artifact handoff protocol, and stateless validation CLI.
It reserves no transport, memory, execution, provider, or Agent Host interfaces in the core.

- Agent Bus remains an external transport system.
- AI Memory remains an external long-term knowledge system.
- Model invocation and process lifecycle remain external runtime responsibilities.
- Repository operations scripts are dogfood surfaces, not adapters promised by the core.

Any future composition must start from observed downstream needs and current external APIs. See
[ADR-0001](0001-project-boundaries.md), [ADR-0002](0002-contract-first-design.md), and
[ADR-0005](0005-high-value-model-capacity-isolation.md).
