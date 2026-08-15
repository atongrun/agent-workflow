# P2 Binary Distribution Feasibility Report

## Status

Implementation complete; native CI measurements pending.

This report is a feasibility record, not a production packaging decision or release promise. The
exact candidate/target results will be filled from the dedicated GitHub Actions summary artifact
before exact-head review and merge.

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
  size/checksum/file
  count and cold/warm startup, exercises an unrelated-cwd no-model `run check`, generates a
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

Pending dedicated CI evidence.

## Decision

Pending the complete 15-cell native matrix. The decision rule is frozen in the TaskCard: recommend
the launcher plus independently versioned app only if every target preserves all required runtime
probes and the checksum/SBOM/update/rollback surface is automatable; otherwise No-Go a production
binary ABI while retaining the measured research artifacts.

## Local verification

- Python `compileall` for the experiment entry, collector, and focused tests.
- `git diff --check` and allowed-path/static review.
- No local pytest, Ruff, Go build/test, Rust, service mutation, Agent Bus connection, or event
  operation.
