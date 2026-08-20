# RTS-033 Isolated Workspace and Trusted Import Implementation Report

## Result

The installed Python Runtime now owns the exact local trust seam from a resolved source repository
to one event-contained no-remote model workspace and from one verified binary delta to the trusted
local index. Production `awf_role.py` retains compatibility entry points but delegates prepare,
Git-control freeze/assert/digest, durable manifest restore, workspace-state validation and delta
import to `agent_workflow.runtime.workspace`.

Current RunLedger/checkpoint/outbox/inbox/RunEvidence remains the sole production authority and
recovery implementation. This candidate does not read/write the RTS-031 Store, persist a second
workspace authority, alter provider replay or rework selection, operate remote Git/GitHub, touch
Agent Bus ordering, migrate state or change a default.

## Exact local trust behavior

- `WorkspaceSpec` freezes resolved source/state paths, exact expected commit, fixed prefix and one
  explicit canonical credential-stripped environment. Sensitive, duplicate, invalid or oversized
  environment input fails before Git.
- Workspace preparation uses structured `git` argv with `shell=False`, `--no-hardlinks` and
  `--no-checkout`; it removes `origin`, reflogs and `FETCH_HEAD`, verifies detached exact HEAD and
  rejects redirected/event-escaping paths.
- The Git-control manifest preserves the current oracle: object payloads remain excluded except
  `objects/info`, the volatile binary index is replaced by semantic entries/tree, and file,
  symlink/reparse, directory and other facts remain distinct. Manifest and control SHA-256 use the
  same canonical mapping and `sha256:` representation as current recovery evidence.
- Control drift is checked from filesystem metadata before any Git call on the model-controlled
  workspace. Only after that match does the semantic-index check run.
- `WorkspaceDelta` binds base tree, verified model tree, patch length and patch SHA-256. Delta
  serialization is binary/full-index and capped at 64 MiB; other Git captures are capped at 4 MiB.
- Trusted import applies only those exact bytes with structured argv and requires the resulting
  trusted tree to equal the verified model tree.

## Changed files

- `docs/tasks/runtime-v2-rts-033-workspace-import.md`
- `src/agent_workflow/runtime/workspace.py`
- `src/agent_workflow/runtime/__init__.py`
- `scripts/awf_role.py`
- `tests/test_runtime_workspace.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_command_boundary.py`
- `tests/test_awf_role.py`
- `tests/test_runtime_v2_rts011_acceptance.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-033-workspace-import.md`

## Scope and budgets

- Installed workspace module: 393/440 nonblank/noncomment lines.
- Focused workspace tests: 363/780 nonblank/noncomment lines.
- Production `scripts/awf_role.py`: net -39 nonblank/noncomment lines against `origin/main`
  (budget at most +80).
- Dependencies: no addition; installed Runtime remains standard-library only.
- Command surface: one fixed private Git runner; public operations accept no arbitrary argv,
  registry, implementation plugin or VCS abstraction.
- Writable-path audit: only frozen TaskCard paths changed; no generated file remains.

## Local verification

Repository-policy-safe local validation passed:

- AST parse for every changed Python module/test;
- direct disposable Git smoke for exact prepare, no-remote workspace, binary delta and trusted tree
  equality;
- installed Runtime plus `awf_role` import smoke with bytecode writes disabled;
- static structured-argv/no-shell/no-remote-command/no-scripts-import scans;
- exact TaskCard scope, dependency and LOC audits;
- `git diff --check`.

Per repository policy, local pytest, Ruff and Rust were not run on this Mac. Independent TaskCard
Gate Review passed the semantic candidate `ff7f77f` with zero findings. L1 CI repairs only corrected
Ruff shape and upgraded legacy tests to real Git/staged-index fixtures; they did not change the
reviewed Runtime behavior. Exact-head ordinary CI `32349631233` and Binary Feasibility
`32349631258` then passed at `75a4630`, including Linux/Windows suites, macOS runtime, all three
installed-wheel jobs, five native cells and five Rust comparison cells.

## Explicit non-claims

This candidate does not adopt/dual-write the selected Store, change authority/recovery formats,
alter rework lineage, Artifact policy or provider invocation ordering, publish/fetch remote Git,
operate GitHub/Bus/lifecycle/Feedback, implement `run/status/stop`, add the launcher, switch a
default, migrate retained/production state, release or authorize destructive cleanup.

<!-- awf-implementation-report
{
  "summary": "Move exact no-remote workspace preparation, compatible Git-control identity and trusted local delta import behind the installed Runtime boundary without changing production authority.",
  "changed_files": [
    "docs/tasks/runtime-v2-rts-033-workspace-import.md",
    "src/agent_workflow/runtime/workspace.py",
    "src/agent_workflow/runtime/__init__.py",
    "scripts/awf_role.py",
    "tests/test_runtime_workspace.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_command_boundary.py",
    "tests/test_awf_role.py",
    "tests/test_runtime_v2_rts011_acceptance.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-033-workspace-import.md"
  ],
  "commands": [
    "Python AST and installed Runtime/role import smoke checks",
    "direct disposable Git prepare/delta/trusted-import smoke",
    "static dependency, command, writable-path and generated-file audit",
    "LOC and line-length checks",
    "git diff --check"
  ],
  "tests": [
    "Local policy-safe static and disposable Git validation PASS",
    "Exact-head ordinary CI 32349631233 PASS at 75a4630",
    "Exact-head Binary Feasibility 32349631258 PASS at 75a4630",
    "Independent TaskCard Gate Review PASS at semantic candidate ff7f77f"
  ],
  "source_revision": "9c2e5f1c6077b1bb7bc2e72d9f0a36d5ec6f13e7"
}
-->
