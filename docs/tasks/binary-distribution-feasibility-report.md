# P2 Binary Distribution Feasibility Report

## Status

Complete. Dedicated native CI run `31884490534` produced all 15 candidate/target records and the
deterministic `awf.binary-feasibility-summary.v1` artifact. Normal CI run `31884490536` passed all
six jobs on the same head.

This report is a feasibility record, not a production packaging decision or release promise. The
summary SHA-256 is `a1b8269f5119112813c15cc55af6a76c84bed5090a54cfc10fc4345fd5393f9a`.
Individual evidence files retain the per-target artifact SHA-256 values without committing
generated binaries or runner paths to the repository.

## Frozen question

Can Agent Workflow reduce fresh-machine installation friction without changing the existing
installed-Python resource, interpreter re-entry, native lifecycle, structured Agent Bus argv, and
fail-closed ownership contracts?

The comparison is deliberately limited to:

1. PyInstaller one-folder.
2. PEX scie eager.
3. A small Go launcher that verifies and executes an independently replaceable PEX app.

## Implementation

- `awf_entry.py` adds a CI-private probe before delegating ordinary arguments to the unchanged
  production CLI. It checks real resource directories, Python `-m` and script re-entry, exact argv
  through a fake external CLI, UTF-8 log round-trip, and native definition rendering. It does not
  install/start/stop a service, connect remotely, or invoke a model.
- `experiments/binary-feasibility/verify.py` builds all three candidates natively, measures
  size/checksum/file count and cold/warm startup, exercises an unrelated-cwd no-model `run check`, generates a
  CycloneDX SBOM, records absent signing/notarization/attestation honestly, and rejects incomplete
  or target-drifted evidence.
- The Go prototype accepts only a basename sibling selected by `awf.binary-release.v1`, verifies
  its SHA-256 before execution, forwards argv without a shell, and preserves the child exit code.
- The CI matrix uses native Linux x86_64/arm64, Windows x86_64, and macOS x86_64/arm64 runners. A
  pinned, disposable localhost SQLite Agent Bus peer separately proves the transport companion;
  its generated test state is destroyed and never uploaded.

## Architectural risk under measurement

The current production contract intentionally records and re-enters `sys.executable` to run
`agent_workflow.cli`, `agent_workflow.node_service`, and packaged operation scripts. A wrapper that
can print `awf version` but cannot behave as a real Python interpreter is not lifecycle-compatible.
P2 will record that as No-Go and will not repair it by changing production modules.

PyInstaller is not treated as a cross-compiler. GitHub provenance/SBOM support is not treated as
Apple notarization or Windows code signing. Windows arm64, universal2, old-glibc support, antivirus
reputation, production upgrade policy, and credentialed signing remain unproved.

## Native results

Every cell built and emitted valid evidence. A green feasibility workflow means the matrix is
complete and internally consistent; it does not mean a candidate passed the runtime gates.

| Candidate | Artifact range | Startup range, cold / warm median | Passed target gates |
| --- | ---: | ---: | ---: |
| PyInstaller one-folder | 23.24-57.33 MiB, 159-169 files | 152-401 ms / 115-393 ms | 0/5 |
| PEX scie eager | 27.61-108.75 MiB, 1-2 files | 2,062-6,362 ms / 224-756 ms | 0/5 |
| Go launcher + PEX app | 30.53-111.74 MiB, 3 files | 233-795 ms / 255-880 ms | 0/5 |

Measured gate detail:

- All five PyInstaller builds preserved packaged resources, rendered the correct native lifecycle
  definition, and ran `awf version`. None preserved Python module/script re-entry, exact fake-CLI
  argv, or UTF-8 log round-trip. The unrelated-cwd no-model check passed on four targets and failed
  on Windows.
- PEX and the Go launcher preserved resources, exact argv, UTF-8, lifecycle rendering, version,
  and the no-model check on both Linux architectures and both macOS architectures. Neither
  preserved Python module/script re-entry on any target. Their Windows executables returned
  non-zero before the private runtime probe and no-model check could pass.
- The Go launcher rejected a deliberately incorrect app checksum on all five targets. Its sibling
  manifest update/rollback probe passed on the four targets where the PEX child ran and failed
  closed on Windows. It never used a shell and retained the child exit code.
- Each native job separately passed the pinned disposable localhost SQLite Agent Bus smoke. The
  evidence declares real service mutation, remote business events, and model invocation false.
- Tooling was Python 3.12.10 or 3.12.13, PyInstaller 6.22.0, PEX 2.100.4, and Go 1.23.12. Each
  target generated a CycloneDX 1.5 SBOM and content SHA-256.

## Decision

**No-Go for a production binary ABI.** The deterministic decision input is
`NO_GO_PRODUCTION_BINARY`: the launcher route failed the frozen all-five-target gate, and every
candidate changed the installed-Python interpreter re-entry contract. The Go checksum boundary is
promising as a future distribution primitive, but it is not sufficient to change the decision.

The experiment therefore creates no production ABI, installer, updater, release format, or
deployment commitment. It makes no signing, notarization, attestation, Windows antivirus
reputation, Windows arm64, macOS universal2, or old-glibc claim. Reconsideration requires a new
TaskCard and a design that preserves the existing interpreter/lifecycle boundary rather than
weakening it.

## Local verification

- Python `compileall` for the experiment entry, collector, and focused tests.
- `git diff --check` and allowed-path/static review.
- No local pytest, Ruff, Go build/test, Rust, service mutation, Agent Bus connection, or event
  operation.
