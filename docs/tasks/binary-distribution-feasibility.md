# TaskCard: P2 Binary Distribution Feasibility

## Task ID

AWF-USABILITY-P2

## Objective

Measure whether Agent Workflow can be delivered as a low-friction cross-platform artifact without
changing its runtime contracts. Compare a PyInstaller one-folder build, a PEX scie eager build, and
a small native Go launcher paired with an independently versioned Python app. Produce an auditable
Go/No-Go decision only; do not introduce a production binary ABI, installer, release, updater, or
deployment.

## Base and branch

- Repository: `atongrun/agent-workflow`
- Base: `main@f131bb40b1e65e79850f1b9e58aed03da8a9039f`
- Branch: `codex/binary-feasibility`
- Compatible Agent Bus consumer floor:
  `master@6ca8f2812be0286607bbbe3f14cc51783637b0b5`

## Allowed changes

1. `docs/tasks/binary-distribution-feasibility.md`
2. `docs/tasks/binary-distribution-feasibility-report.md`
3. `.github/workflows/binary-feasibility.yml`
4. `experiments/binary-feasibility/README.md`
5. `experiments/binary-feasibility/awf_entry.py`
6. `experiments/binary-feasibility/go.mod`
7. `experiments/binary-feasibility/main.go`
8. `scripts/verify_binary_feasibility.py`
9. `tests/test_binary_feasibility.py`
10. `README.md`
11. `CHANGELOG.md`
12. `ROADMAP.md`
13. `HANDOFF.md`
14. `docs/runtime-node-lifecycle-architecture.md`

Do not modify production Python modules, schemas, packaged operations/templates, Agent Bus,
provider adapters, dispatch, status, lifecycle managers, checkpoint/outbox/recovery, or dependency
metadata.

## Candidate and target matrix

- Candidates:
  - PyInstaller one-folder native build.
  - PEX `--scie eager` native build with its Python interpreter embedded.
  - A dependency-free Go launcher that verifies a sibling release manifest and SHA-256 before
    executing the independently replaceable PEX app.
- Native GitHub-hosted targets:
  - Linux x86_64 and arm64.
  - Windows x86_64.
  - macOS x86_64 and arm64.
- Each target is built on its own native runner. PyInstaller is never represented as a
  cross-compiler. Windows arm64, macOS universal2, old-glibc compatibility, and third-party
  antivirus reputation are recorded as unproved, not inferred.

## Required evidence

- Build each candidate in runner-temporary directories without changing `pyproject.toml` or the
  production wheel.
- From an unrelated cwd, exercise packaged schemas, operations and templates, `awf version`, the
  default no-model `run check` path, and a credential-free Unicode path/log boundary.
- Probe Python re-entry plus the existing native lifecycle definition rendering with a fake
  external `agent-bus` executable. The probe must preserve exact argv, use no shell, invoke no
  model, connect to no remote service, and never install/start/stop a real service. Candidate
  incompatibility is recorded as evidence rather than repaired in production code.
- Exercise a disposable localhost SQLite Agent Bus only in CI with generated test credentials and
  synthetic feasibility event types. Never use a retained or live business event, endpoint, token,
  payload, database, or state root.
- Record artifact byte size, cold/warm startup samples, SHA-256, generated SBOM location, target,
  candidate, tool versions, resource/lifecycle/UTF-8 outcomes, and whether the artifact is signed,
  notarized, or attested.
- Upload only credential-free experiment artifacts and machine-readable evidence. Test tokens,
  SQLite files, event payloads, logs containing payload data, and local absolute paths are excluded.

## Decision gates

- **Go** may be recommended only for a small native launcher plus independently versioned Workflow
  app and Agent Bus when all five target artifacts preserve the required resource, no-model,
  lifecycle-render, exact-argv, and UTF-8 behavior and the checksum/SBOM/update/rollback story is
  automatable.
- **No-Go** the monolithic binary route if freezing changes `sys.executable`, resource lifetime,
  service-manager identity, child launch, exact stop, or the transport-only Bus boundary.
- GitHub provenance/SBOM attestation is not Apple notarization or Windows code signing. Production
  trust claims require separate credentials and explicit authorization after feasibility.
- A failed candidate or target remains an honest feasibility result; CI fails only when evidence is
  missing, malformed, leaks prohibited data, or contradicts the declared result.

## Verification level

**Level C; CI-only cross-platform feasibility.**

- Unit tests cover release-manifest parsing, SHA-256 verification, target normalization, evidence
  redaction/validation, and launcher fail-closed behavior.
- The dedicated feasibility workflow builds and probes every candidate/target combination, then
  aggregates a deterministic decision input. Normal repository CI remains required.
- Local Mac verification is limited to `compileall`, Go source formatting checks that do not build
  or test, static scans, allowed-path review, and `git diff --check`. Local pytest, Ruff, Rust, and
  binary builds are prohibited.

## Out of scope and stop conditions

- No production ABI, package-manager formula, installer, updater, release, signing key, certificate,
  notarization submission, artifact publication outside GitHub CI, live deployment, or production
  service mutation.
- No Phase B, Agent Host, DAG, provider registry, model router, generic invocation-result contract,
  monolithic Agent Bus embedding, or new runtime dependency.
- Never read, ACK, fail, requeue, recover, redispatch, or reuse retained events or payloads,
  including events 163, 166, or 173.
- Stop if feasibility requires weakening fail-closed lifecycle/provenance/delivery-hash/checkpoint/
  outbox/postflight/PR-tuple gates, business/Finding ACK separation, exact stop, or Agent Bus
  transport-only ownership.

## Required output

Minimal experiment code, deterministic report, Lore commits, PR, normal and feasibility CI green,
independent exact-head review, fresh mergeability, merge, post-merge main/CI proof, necessary docs
and shared Memory, and short-branch cleanup. The final report must distinguish measured facts,
unproved production requirements, and the Go/No-Go recommendation.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/binary-distribution-feasibility.md",
    "docs/tasks/binary-distribution-feasibility-report.md",
    ".github/workflows/binary-feasibility.yml",
    "experiments/binary-feasibility/README.md",
    "experiments/binary-feasibility/awf_entry.py",
    "experiments/binary-feasibility/go.mod",
    "experiments/binary-feasibility/main.go",
    "scripts/verify_binary_feasibility.py",
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
