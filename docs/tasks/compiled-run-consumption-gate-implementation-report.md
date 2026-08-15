# ImplementationReport: P0-4b Compiled Run Consumption Gate

## Outcome

Normal setup/run now uses the P0-4a compiler as a pre-mutation gate. Setup persists one complete
credential-free owner RunManifest plus an owner-only compiled report. Run reloads and recompiles
the current graph, requires exact report equality, and binds the compiled SHA into the context
packet before Git HEAD lookup or RunLedger initialization.

## Production changes

- The v1 RunManifest accepts paired `state_root` and exact `profiles.coder` / `profiles.reviewer`
  references. Existing manifests remain parseable, but run refuses an uncompiled legacy document
  with an explicit setup migration.
- Compiled reports use the existing owner-only cross-platform atomic writer/ACL verifier and reject
  unknown fields, wrong formats, incompatible status, or checksum drift.
- Setup uses class-specific `--run-manifest`, `--run-contract`, and `--authority-manifest` names,
  validates the complete graph before either owner file is written, and keeps secrets in
  `dispatch.env`.
- Run loads the exact persisted authority reference, recompiles TaskCard/report allowlist,
  repository/provenance, state-root, and durable role profiles, then compares the full report.
  Drift stops before subprocess or ledger construction.
- `awf.context-packet.v1` carries an optional `run_contract_sha256`; new compiled runs populate it,
  and RunLedger initialization treats it as immutable. Historical packets without the field remain
  recoverable and are never silently promoted to compiled identity.
- The lower-level native dispatch surface and every Agent Bus/business handler gate remain
  unchanged.

## Proportional verification

- The existing run unit now proves exact compiled SHA propagation into the packet.
- One new zero-side-effect regression proves compiled drift refuses before Git or RunLedger.
- One new compatibility regression proves generic setup/run `--manifest` receives the precise
  `--run-manifest` migration.
- Existing manifest and control-plane tests now cover owner-only compiled report round-trip,
  checksum validation, packet recovery, and immutable contract binding.
- The existing installed-wheel unrelated-cwd smoke now executes setup -> plan check -> local run on
  Ubuntu, Windows, and macOS using temporary credential-free fixtures and a local Git repository;
  it does not connect to Agent Bus or invoke a model.
- Local Mac checks are limited to changed-file `compileall` and `git diff --check`; GitHub CI owns
  Pytest, Ruff, and platform verification.

## Compatibility and rollback

- RunManifest format stays `awf.run-manifest.v1`; the new paired inputs are credential-free and
  optional for parsing. Operational run requires them and names the one legal setup migration.
- Existing context packets remain valid because `run_contract_sha256` is optional; no old ledger is
  mutated or inferred into the new identity.
- Rollback is a clean package revert before any live business run. No transport data, credentials,
  retained payloads, ACKs, or remote state are part of this change.

## Evidence

- Base: `main@bd582e1a9c6c3eafa5e55b094356e503042970ea`
- Branch: `codex/compiled-run-gate`
- Local static checks: changed-file `compileall` and `git diff --check` passed.
- Exact PR head, CI, independent review, merge, and post-merge main CI remain auditable in the
  package PR; no live business delivery is used as substitute evidence.
