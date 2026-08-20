# RTS-032 Production Provider Renderer Boundary Closeout

## Result

`PASS` for the independently reversible production provider-rendering seam.

The installed Python Runtime now owns closed pure OpenCode coder/reviewer, Codex reviewer and Pi
reviewer renderers. The trusted role wrapper binds one immutable `InvocationSpec` after the current
authorization/recovery gates, renders once, and passes the exact structured process inputs through
the existing spawn boundary. Production no longer imports or calls `scripts/agent_adapters`.

This change neither adopts nor dual-writes the RTS-031 Store. Current
RunLedger/checkpoint/outbox/inbox/RunEvidence records remain the sole production authority and
recovery path; provider replay, Artifact/Git/PR/Bus/ACK ordering and defaults are unchanged.

## Verification

- Independent TaskCard Gate Review at semantic candidate `9d2cb47`: `PASS`, zero findings.
- L1 repair `1028eae`: two isolation-test fakes accept the already-reviewed `binding=` keyword;
  no Runtime behavior changed.
- Exact-head ordinary CI `32345260471`: Linux/Windows suites, Ruff, macOS runtime and all three
  installed-wheel jobs passed.
- Exact-head Binary Feasibility `32345260487`: five native cells, five Rust shared cells and both
  aggregate jobs passed.
- Final budgets: renderer 119/320 lines; focused tests 268/750; `awf_role.py` net +161/180; no new
  dependency; one closed dispatch and no registry/discovery/plugin framework.

## Exact successor seam

The only successor seam authorized by this closeout is a separately frozen **RTS-033 isolated
workspace and trusted-import boundary**. It may move the existing fresh no-remote workspace
creation, frozen Git-metadata assertions, bounded credential-free Git reads, exact delta
serialization and trusted local import behind a narrow installed Runtime v2 API.

RTS-033 must retain the current authority/recovery representation as sole production truth. It may
not adopt or dual-write the RTS-031 Store, change rework lineage, publish/fetch remote Git or GitHub
state, change Artifact policy, add a generic workspace framework, migrate state or alter defaults.
Exact workspace HEAD/remote/metadata, tree/delta and trusted-import behavior must remain locked on
the same fixtures and the change must stay independently reversible.

## Rollback and non-claims

Reverting the renderer integration restores the retained adapter call seam without changing
production state. Phase 3 is not complete. Store adoption, Workflow transition migration, full
rework lineage, external Git/PR lifecycle, `run/status/stop`, transport, native lifecycle,
distribution, default, release and old-representation deletion remain behind later gates.
