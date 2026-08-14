# ImplementationReport: P0-4a Read-only Run Contract Compiler

## Outcome

Implemented a local-only `awf plan check` surface that compiles one owner RunManifest, separate
internal authority manifest, frozen TaskCard/report allowlist, canonical state-root, repository,
and exact coder/reviewer node-profile identities into `awf.run-contract-report.v1`. Normal
`setup`, `run`, and `dispatch` behavior is unchanged for the later P0-4b switch.

## Production changes

- `src/agent_workflow/manifest.py` now owns deterministic run-contract compilation, explicit v1-v3
  route compatibility, cross-input agreement checks, compiler provenance, and canonical bindings.
- `src/agent_workflow/cli.py` exposes `awf plan check` with unambiguous `--run-manifest` and
  `--authority-manifest` inputs. It prefers the exact P0-3 installed profile binding and falls back
  to an uninstalled authoring profile only when no installed binding exists.
- `scripts/awf_artifact_contract.py` retains the existing stage-level ImplementationReport API and
  adds a run-level linter for the immutable TaskCard plus the sole ImplementationReport and
  ReviewReport paths in one non-empty, unique, repository-relative allowlist.
- `scripts/awf_control_plane.py` reports both the required and received format identifiers when an
  authority-manifest class is wrong.

The read-only path performs no RunLedger initialization, Git command, process start, Agent Bus
connection, event send, ACK, requeue, recovery, redispatch, or retained-event access.

## Proportional verification

- New focused behavior is limited to three test functions: exact manifest-class rejection before
  compilation, table-driven cross-binding drift, and explicit v1/v2/v3 compatibility.
- The existing Phase 0 artifact-contract test now also exercises the ReviewReport/run binding.
- The existing installed-wheel unrelated-cwd verifier constructs a credential-free temporary run
  and executes the compiled CLI on Ubuntu, Windows, and macOS CI.
- Local Mac checks: changed-file `compileall` and `git diff --check`. Pytest, Ruff, and platform
  runtime suites are intentionally delegated to GitHub CI under the frozen verification policy.

## Compatibility and rollback

- Existing `awf.run-manifest.v1`, `awf.authority-manifest.v1`, node-profile v1, stage artifact API,
  and v1-v3 route formats remain intact.
- P0-4a adds a command but does not make it a prerequisite for setup/run/dispatch. Rollback is a
  clean revert of this package without migrating owner state or remote data.
- P0-4b must not claim compatibility from an arbitrary report: it must bind and consume the exact
  compiler output only after this package is merged and its fixtures remain green.

## Evidence

- Base: `main@06e71c46118bc8b584cc94667fa6f39fc1f93b2d`
- Branch: `codex/run-intent-compiler`
- Local static checks: passed.
- Exact PR head, GitHub CI run, independent review, merge commit, and post-merge main CI are filled
  by the auditable Git/PR history for this package; no live business delivery is part of evidence.
