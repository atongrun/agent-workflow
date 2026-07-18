# Phase 0 Follow-ups (Historical)

> **Superseded.** The original review assumed a control-plane runtime, internal ports/adapters, and
> an Agent Host plugin. Those assumptions were removed when Agent Workflow contracted to a portable
> method, Artifact handoff protocol, and stateless validation CLI. Do not use this file for current
> architecture or roadmap decisions.

The durable lessons retained from that review are:

- package/install smoke tests may be added when real distribution use requires them;
- CLI semantic validation should reject invalid Role/Stage/transition references;
- schema strictness and versioning should be tightened incrementally from real evidence.

Current sources:

- [`../../constitution.md`](../../constitution.md)
- [`../../ROADMAP.md`](../../ROADMAP.md)
- [`../adr/0005-high-value-model-capacity-isolation.md`](../adr/0005-high-value-model-capacity-isolation.md)
- [`../product-metrics.md`](../product-metrics.md)

Agent Host, Plugin SDK, Runner/EventBus/Memory/ArtifactStore ports, and a generic Workflow Engine are
not active follow-ups.
