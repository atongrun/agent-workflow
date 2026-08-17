# P2b Binary Release Readiness Report

## Status

The credential-free post-merge evidence from Binary Feasibility run `32044472821` was downloaded
and assessed with the repository's existing validator. The deterministic
`awf.binary-release-readiness.v1` output has evidence SHA-256
`1d89ffb46c570125c84cfef090305b73ff96a12ed9fc27e307d4c7b7ff84c335`.

The decision remains `NO_GO_PRODUCTION_BINARY`. This package creates no production ABI, artifact,
installer, updater, signature, notarization submission, release, deployment, service mutation, or
event operation.

## Existing candidate decision

Repairing one of the three measured candidates is not the shortest legal path.

- Python module and operation-script re-entry failed in all 15 candidate/target cells.
- PyInstaller otherwise preserved resources and lifecycle rendering on all targets, but it also
  failed exact argv and UTF-8 round-trip in all five cells and no-model execution on Windows.
- PEX scie eager and the Go-launcher/PEX-app route preserved resources, lifecycle rendering, argv,
  UTF-8 and no-model behavior on the four Linux/macOS targets, but both failed before the Windows
  runtime probe and neither exposed a real re-enterable Python interpreter on any target.
- The Go launcher proved checksum rejection on 5/5 targets and app-manifest swap on 4/5. Those are
  useful distribution primitives, not evidence that the PEX child satisfies the runtime contract.

The shared 15/15 interpreter failure is a contract-shape mismatch, not a narrow platform or
packager defect. Removing interpreter re-entry, replacing real resource directories, or special
casing the native lifecycle would weaken frozen production behavior and remains prohibited.

## Shortest legal next candidate

The recommended next experiment is:

```text
small native launcher
  -> relocatable real CPython runtime
  -> Agent Workflow installed in that runtime
  -> unchanged sys.executable module/script re-entry

Agent Bus remains an independently versioned service/distribution.
```

This is a recommendation, not an adopted production contract. A separate owner decision is
required before selecting a redistributable Python supplier, freezing launcher/runtime/app
compatibility, adding dependencies, or naming production artifacts.

## Exact remaining count

There are **four technical release blockers**:

1. `functional_runtime_bundle`: build one five-target candidate that preserves every frozen
   resource, real-Python re-entry, lifecycle, exact-argv, UTF-8, no-model, checksum, SBOM and
   update/rollback gate.
2. `production_distribution_contract`: explicitly adopt launcher/runtime/app/independent-Bus
   compatibility, artifact identity and state ownership as a production ABI.
3. `supply_chain_trust`: automate production checksum manifest, SBOM, provenance/attestation,
   macOS Developer ID signing/notarization/stapling, Windows Authenticode/timestamp and normal
   launch/reputation evidence.
4. `release_lifecycle_acceptance`: implement immutable install/version selection, compatibility
   precheck, upgrade, program rollback without state rollback, and a signed five-target release
   candidate acceptance.

There is **one additional authorization boundary** after those blockers close: publishing release
assets or creating a live GitHub Release. It is not counted as a technical defect and is never
performed implicitly.

Four extensions are explicitly deferred unless their support is claimed: Windows arm64, macOS
universal2, older-glibc/musl breadth, and package-manager or automatic-updater integration. They do
not block an initial five-target archive release.

## Verification

- Existing feasibility validation is reused for every input record; missing, duplicate, malformed
  or target-drifted matrices fail closed.
- The assessor reproduces 15 cells, 15 Python re-entry failures, two Windows PEX-family runtime
  failures, zero passing candidates and four successful Go manifest swaps.
- Local Mac verification: `compileall`, deterministic assessment of the downloaded evidence,
  `git diff --check`, and allowed-path inspection only.
- Pytest, Ruff and cross-platform regression evidence are delegated to GitHub CI under the local
  machine policy.

## Remaining risks

- A relocatable CPython source, redistribution/license inventory and dependency-lock strategy have
  not been selected.
- Runtime-tree integrity may require an install-time signed manifest rather than hashing a large
  directory on every CLI start; that belongs to the production distribution contract.
- Windows antivirus reputation cannot be inferred from an unsigned CI artifact.
- Program rollback must remain separate from Workflow/Bus state and database migration semantics.
