# Agent Bus Boundary (Later External Composition)

> **Status: external and deferred.** Agent Workflow ships no Agent Bus adapter, event port, or
> Workflow Engine. The current `scripts/` integration is an operations dogfood surface, not core.

## Ownership

Agent Bus owns:

- endpoint and agent identity;
- event delivery and replay;
- ACK, retry, and failure propagation;
- durable transport evidence.

Agent Bus does not understand or decide:

- Workflow Stage or allowed transition;
- ReviewReport semantics;
- deterministic rework versus escalation;
- TaskCard, Phase, Milestone, merge, or project completion.

Agent Workflow owns those method semantics as Artifact contracts. An external runner interprets the
current Artifact/Run Context and chooses which Agent Bus event to send. The transport treats that
domain payload as opaque.

## Current Dogfood Evidence

Repository operations scripts have used the real Agent Bus CLI to demonstrate:

- pointer dispatch to a versioned TaskCard;
- role listener → trusted handler → model child process boundaries;
- handler success as an ACK gate;
- coder postflight, commit/push, refreshed remote-SHA proof, and reviewer handoff;
- durable handler lifecycle records outside the checkout;
- a real Windows no-code handler-return followed by success-gated ACK.

This is engineering evidence, not a stable integration protocol. The current Reviewer still maps
tool completion to a placeholder and cannot route a validated semantic `PASS`, deterministic
`REQUEST_CHANGES`, or `BLOCKED`. Merge and next-TaskCard continuation have not been proven in one
uninterrupted cross-machine chain.

## Future Composition Rule

A future external runtime may combine Agent Workflow Artifacts with Agent Bus transport only after
real dogfood demonstrates a repeated need. It should:

1. carry a bounded Artifact or immutable reference plus branch/commit provenance;
2. fail closed when required content cannot reach the next role;
3. keep delivery/ACK status separate from semantic completion;
4. avoid teaching Agent Bus Workflow-specific verdicts or transitions.

No Agent Bus protocol redesign, generic adapter, event taxonomy, or retry policy is authorized by
this boundary note.
