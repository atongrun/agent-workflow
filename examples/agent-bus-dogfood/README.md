# Agent Bus Brownfield Dogfood

This example records an **infrastructure engineering** scenario, not the first downstream
capacity-isolation proof. Agent Bus is supporting infrastructure, so high-value models may be used
freely where reliability, safety, or real-environment diagnosis requires them.

## Goal

Continue Agent Bus with the bounded non-mutating diagnostic slice in [`goal.md`](goal.md), starting
from a freshly verified version of [`baseline.md`](baseline.md). Do not redesign Agent Bus.

## Proposed Artifact Chain

```text
verified baseline → ArchitectureRecord → PhasePlan → TaskCard
→ ImplementationReport → TestReport → ReviewReport → DecisionPacket → Decision
```

The current `awf` CLI does not implement `init`, `status`, `next`, or `submit`. Manual file-based
handoff is acceptable; documentation of those commands elsewhere is a proposed interface, not
proof that a controller exists.

The TaskCard must remain bounded to the CLI implementation, focused CLI tests, and CLI
documentation. It forbids server/schema changes, new dependencies, event mutation, and unrelated
cleanup.

## What Existing Operations Dogfood Already Proved

Separate real runs using `scripts/` and Agent Bus proved exact checkout, trusted executor/postflight
boundaries, commit/push plus remote-SHA proof, durable handler evidence, and a Windows handler-
return/ACK gate. Those scripts are an operations surface outside the `awf` core.

They did not prove the full chain above. Reviewer tool completion is still a placeholder rather
than a validated semantic verdict, so safe review routing, merge, and next-TaskCard continuation
remain open.

## Acceptance Evidence for This Example

- the baseline is regenerated from the selected Agent Bus checkout;
- the complete baseline-to-decision Artifact chain exists;
- architecture uses no more than three rounds;
- diagnostic tests cover missing configuration, network failure, unhealthy service, unauthorized
  token, and success without real credentials;
- ordinary deterministic rework stays local and optional advice does not block;
- model invocations record role and reason, but infrastructure-mode success is not judged by
  reducing high-value-model calls;
- no generic adapter, Agent Host, or complex runtime is introduced.

After this engineering example, product value still requires the downstream multi-TaskCard gate in
[`../../docs/product-metrics.md`](../../docs/product-metrics.md).
