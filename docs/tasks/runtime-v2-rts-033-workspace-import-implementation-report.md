# RTS-033 Isolated Workspace and Trusted Import Boundary Closeout

## Result

`PASS` for the independently reversible isolated-workspace and trusted local import seam.

The installed Python Runtime now owns exact event-contained no-remote workspace preparation,
Git-control freeze/assert/digest and durable restore, bounded exact binary-delta serialization and
trusted local index import. Production `awf_role.py` keeps compatibility entry points but contains
no independent implementation fallback for these operations.

Current RunLedger/checkpoint/outbox/inbox/RunEvidence remains the sole production authority and
recovery path. RTS-031 Store adoption, dual write, rework-lineage redesign, remote publication,
migration and defaults remain unchanged.

## Verification

- Independent TaskCard Gate Review at semantic candidate `ff7f77f`: `PASS`, zero findings.
- L1/test-fixture repairs through `75a4630`: Ruff-only shape, real local Git recovery fixture and
  production-faithful staged-index commit ordering; no Runtime behavior changed.
- Exact-head ordinary CI `32349631233`: Ruff, Linux/Windows suites, macOS runtime and all three
  installed-wheel jobs passed.
- Exact-head Binary Feasibility `32349631258`: five native cells, five Rust comparison cells and
  both aggregate jobs passed.
- Final budgets: workspace module 393/440 lines; focused workspace tests 363/780;
  `awf_role.py` net -39 lines against the TaskCard base; no new dependency or authority file.

## Exact successor seam

The only successor seam authorized by this closeout is a separately frozen **RTS-034 Artifact
validation boundary**. It may move the existing TaskCard-bound Artifact path, report-shape,
size/hash, allowed-path, secret and postflight-result validation behind one narrow installed
Runtime API while preserving byte-for-byte accepted/rejected outcomes and current ordering before
trusted import.

RTS-034 must keep current production authority/recovery as sole truth. It may not adopt or
dual-write the RTS-031 Store, change TaskCard/Artifact policy, alter rework lineage, commit/push or
operate remote Git/GitHub, send/ACK Bus events, migrate state, change defaults or introduce a
generic validation/plugin framework.

## Rollback and non-claims

Reverting the installed workspace integration restores the retained wrapper bodies without
changing production state representation. Phase 3 is not complete. Store adoption, Workflow
transition migration, full rework lineage, remote Git/PR lifecycle, `run/status/stop`, transport,
native lifecycle, distribution, default, release and old-representation deletion remain behind
later gates.
