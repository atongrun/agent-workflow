# TaskCard: P2b Binary Release Readiness

## Task ID

AWF-BINARY-READINESS-P2B

## Objective

Turn the completed 15-cell feasibility evidence into a deterministic, auditable production-release
readiness decision. Decide whether repairing one of the three measured freezer candidates is the
shortest legal path or whether a fourth distribution shape is required. Keep every P2 runtime,
resource, Python re-entry, lifecycle, argv, UTF-8, no-model, checksum, SBOM, update/rollback, and
five-target gate intact.

This package is readiness work only. It creates no production distribution ABI, installer,
updater, signature, notarization submission, release artifact, GitHub Release, deployment, service
mutation, or event operation.

## Working context

- Repository: `atongrun/agent-workflow`
- Base: `main@e0d0761f4038862f99a7641531fbf2a5f0b0167c`
- Branch: `codex/binary-release-readiness`
- Evidence source: credential-free `awf.binary-feasibility.v1` artifacts from post-merge Binary
  Feasibility run `32044472821`.
- Existing decision: `NO_GO_PRODUCTION_BINARY`.

## Required behavior

1. Read the complete 3-candidate by 5-target evidence set and reject missing, duplicate,
   target-drifted, or malformed records through the existing feasibility validator.
2. Emit one deterministic `awf.binary-release-readiness.v1` artifact that records:
   - exact evidence digest and measured failure counts;
   - whether an existing candidate is a narrow repair target;
   - the recommended next candidate contract without adopting a production ABI;
   - exactly four technical release blockers;
   - one separate owner/live-publish authorization boundary;
   - explicitly deferred target and installer extensions.
3. Recommend no existing candidate repair when the installed-Python interpreter re-entry contract
   fails in all 15 cells. The next experiment may recommend a native launcher plus a relocatable
   real CPython runtime and installed AWF application, with Agent Bus independently distributed.
4. Preserve `NO_GO_PRODUCTION_BINARY` and `production_abi_created=false` until a separately
   authorized production contract passes all frozen gates.

## Release blocker taxonomy

The assessor must keep these four technical blockers distinct:

1. `functional_runtime_bundle`: no five-target candidate currently preserves every frozen runtime
   gate, including real Python interpreter re-entry.
2. `production_distribution_contract`: launcher/runtime/app/Agent Bus compatibility, state
   ownership, and artifact naming are not a production ABI and require an owner decision.
3. `supply_chain_trust`: production checksums/manifest, SBOM, provenance/attestation, macOS signing
   and notarization, Windows Authenticode/timestamp and launch/reputation evidence are not complete.
4. `release_lifecycle_acceptance`: immutable install, upgrade, rollback, compatibility checks and a
   signed five-target release-candidate acceptance have not been implemented or proven.

Live publication is a fifth, non-technical boundary: creating release assets or a GitHub Release
requires explicit authorization after all four technical blockers close.

## Allowed changes

1. `docs/tasks/binary-release-readiness.md`
2. `docs/tasks/binary-release-readiness-report.md`
3. `experiments/binary-feasibility/verify.py`
4. `tests/test_binary_feasibility.py`
5. `README.md`
6. `CHANGELOG.md`
7. `ROADMAP.md`
8. `HANDOFF.md`
9. `docs/runtime-node-lifecycle-architecture.md`

Do not modify production Python modules, schemas, packaged operations/templates, Agent Bus,
provider adapters, lifecycle managers, dispatch, status, checkpoint/outbox/recovery, dependency
metadata, or release workflows.

## Verification level and budget

**Level B evidence-contract change; two focused tests.**

- One test proves the complete synthetic matrix yields the exact blocker taxonomy and recommended
  fourth-candidate contract without creating an ABI.
- One test proves a missing cell remains fail closed.
- Existing normal CI and Binary Feasibility remain the cross-platform regression evidence.
- Local Mac verification is limited to `compileall`, deterministic assessment of the downloaded
  credential-free evidence, allowed-path review, and `git diff --check`. Do not run pytest, Ruff,
  Rust, or Go build/test locally.

## Out of scope and stop conditions

- No new runtime/build dependency or third-party redistribution commitment.
- No production ABI, installer, updater, signature/notarization credential, release artifact,
  GitHub Release, deployment, or service mutation.
- Never read, ACK, fail, requeue, recover, redispatch, or reuse events 163, 166, 173, any retained
  or production business delivery, or any business payload.
- Do not weaken fail-closed provenance, delivery hash, checkpoint, outbox, postflight, PR tuple,
  exact-stop, business/Finding ACK separation, or Agent Bus transport-only ownership.
- Stop after no-release readiness closes if the next action requires adopting the recommended
  production distribution contract or publishing a live artifact.

## Required output

TaskCard, deterministic assessor and report, minimal Lore commits, PR, green CI, independent
exact-head Pi review using `opencode-go` / `glm-5.2`, fresh mergeability, merge, post-merge main/CI,
short-branch cleanup, and a pointer-only shared Memory update.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/binary-release-readiness.md",
    "docs/tasks/binary-release-readiness-report.md",
    "experiments/binary-feasibility/verify.py",
    "tests/test_binary_feasibility.py",
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "HANDOFF.md",
    "docs/runtime-node-lifecycle-architecture.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_binary_feasibility.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
