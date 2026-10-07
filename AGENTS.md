# AWF development and review principles

Apply this order to new implementation and review decisions:

1. Reuse Pi native capabilities first, including Pi Durable where appropriate.
2. Use Pi extensions and Skills for application behavior missing from native Pi.
3. Implement a custom service in Go only for a demonstrated remaining service need.
4. Use another approach only when the first three cannot meet the requirement;
   record the reason.

Before adding runtime machinery, inspect the relevant published Pi API/source and
record its version, existing capability, exact gap and the smallest adapter.
Do not copy Pi session/context/tool/task scheduling/checkpoint/recovery into Go
for language uniformity. Written code, passing CI and unlaunched candidate state
are not reasons to retain duplicate runtime capabilities or migration layers.

Pi owns agent behavior and durability. Go owns the necessary public service and
machine/process lifecycle boundaries. Keep existing user data and unrelated Dash
features. An application's stable request/fingerprint/model/result reference is
not another authoritative agent execution ledger.

Review every new custom responsibility against this order and require a stated
native gap. Distinguish source review, synthetic tests and actual native
acceptance. See [architecture principles](docs/architecture-principles.md).
