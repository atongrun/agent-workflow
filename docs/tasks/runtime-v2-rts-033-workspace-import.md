# TaskCard: RTS-033 Isolated Workspace and Trusted Import Boundary

## Task ID

runtime-v2-rts-033-workspace-import

## Goal

Move the existing fresh no-remote model-workspace creation, frozen Git-control metadata checks,
credential-free Git plumbing, exact binary-delta serialization and trusted local import behind one
narrow installed Runtime v2 workspace API.

This is an independently reversible provenance seam. The current
RunLedger/checkpoint/outbox/inbox/RunEvidence path remains the sole production authority and
recovery implementation. RTS-033 must not adopt or read/write the RTS-031 Store, add a second
workspace/lineage authority, change provider replay, alter rework lineage, operate remote Git or
GitHub state, migrate state or change a default.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@b61767dc48e0761eaa8e3f95743f1e99de677c92`
- **Task branch**: `codex/runtime-v2-rts-033-workspace-import`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 3 successor seam
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`, sections 4, 5.1, 6 and 9
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Passed prerequisites**: RTS-030 installed Core boundary, RTS-031 disposable Store/journal and
  RTS-032 production provider renderers

Current production behavior lives in `scripts/awf_role.py`: `prepare_model_workspace()`, the
model-Git manifest freeze/assert/digest helpers, `assert_model_workspace_state()` and
`import_model_delta()`. Compatibility wrapper names may remain for focused fixtures and callers,
but their production implementation must delegate to the installed Runtime boundary without a
silent old-body fallback.

## Frozen workspace boundary

### Exact operation inputs

The trusted role wrapper supplies the installed workspace API with only the exact local inputs
needed for the operation:

- resolved source repository and expected dispatched commit;
- resolved event-scoped destination parent and fixed workspace prefix;
- exact credential-stripped child/Git environment;
- resolved trusted local import repository when applying a delta.

The installed API must not discover credentials or configuration from the host environment, read a
Workflow Stage, authorize an invocation, inspect the RunStore/journal, send/ACK transport, or accept
an arbitrary command. Inputs are bounded immutable values; workspace and delta identity values are
canonical and cannot contain an opaque mutable mapping.

### Fresh isolated workspace

The installed API preserves the current operation sequence and postconditions:

1. create one fresh workspace below the exact resolved event directory;
2. clone locally with `--no-hardlinks --no-checkout` using structured argv and no shell;
3. remove `origin`, disable reflogs, detach-checkout the exact dispatched commit, remove reflog and
   `FETCH_HEAD` source metadata, and reject a different HEAD or any remaining remote;
4. freeze Git control metadata before provider start.

The resulting workspace must be a real directory, not a symlink/reparse traversal, and remain
inside the selected event directory. The API may use a disposable temporary directory only for
tests; it must not create a second durable authority or delete a retained workspace on failure.

### Git-control manifest and recovery identity

The Runtime owns one in-process frozen Git-control manifest for each exact prepared workspace. It
preserves the current compatibility semantics:

- object contents are excluded except `objects/info` control data;
- the volatile binary index is excluded and replaced by the exact semantic staged entries/tree;
- regular files bind SHA-256, symlinks bind their target, and directory/type facts remain distinct;
- assertion compares non-index control metadata before invoking Git on the model-controlled
  workspace, then verifies the semantic index;
- current durable model manifest/control SHA-256 values remain byte-for-byte compatible for the
  same fixture and continue feeding existing checkpoint/rework recovery code.

Missing, moved, foreign or drifted metadata denies before Artifact import or trusted Git mutation.
Do not persist this in-memory freeze as a new authority file and do not change the existing durable
recovery representation in this card.

### Exact delta and trusted import

After current Artifact/postflight gates and workspace-state validation, the installed API:

1. stages the isolated workspace delta with credential-free trusted Git plumbing;
2. resolves exact base and model trees and rejects an empty delta;
3. serializes one `--binary --full-index` cached diff with structured argv and binds its exact byte
   length and SHA-256;
4. applies only those bytes to the index of the exact trusted local repository; and
5. requires the resulting trusted tree to equal the verified model tree.

No renderer or provider receives trusted-repository credentials/remotes. No file is copied outside
this exact delta path, no shell string is used, and the Runtime API cannot push/fetch, create/verify
a PR, commit, send a Bus event or mutate Workflow authority.

## Production adoption and ordering

1. Existing delivery integrity, selection, authorization and recovery policy remain before
   workspace preparation/provider launch.
2. Existing launch-intent/checkpoint and RunEvidence ordering remains unchanged.
3. Existing Artifact validation and allowed-path/secret/postflight gates remain before trusted
   import.
4. The trusted wrapper calls the installed workspace API for prepare/assert/digest/import and maps
   one bounded Runtime workspace error to the current fail-closed handler failure.
5. Existing rework restoration and exact lineage selection remain unchanged; they may consume the
   compatible manifest/digest helpers but cannot be redesigned in this card.
6. Existing remote Git/GitHub publication, PR verification, outbox/inbox, handler success and ACK
   paths remain outside this seam and in their current order.

## Frozen writable scope

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
- `.awf/artifacts/review-report-runtime-v2-rts-033-workspace-import.md`

After implementation, exact-head CI and independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-033-workspace-import-implementation-report.md` and update only the Phase
3 gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- RunLedger, RTS-031 Store/journal, checkpoint/outbox/inbox/RunEvidence format or Workflow
  transition changes.
- Provider rendering/spawn, provider ambiguity/replay, Artifact schema/policy or TaskCard scope
  interpretation.
- Rework lineage selection/restoration, durable workspace location, existing checkpoint digest or
  recovery-phase changes.
- Trusted commit/push/fetch, remote ref, fork, GitHub PR/CI/merge or terminal provenance behavior.
- Agent Bus send/receive/ACK, status, lifecycle, exact stop, Feedback or CLI changes.
- Generic VCS/workspace/plugin framework, new dependency, SQLite, Coordinator, Rust/Go production
  Runtime or native launcher.
- Dual write, legacy-state read/convert/delete, production migration, default switch, release,
  retained/live-event operation or destructive cleanup.

## Budgets and stop rules

- New installed workspace module: at most 440 nonblank/noncomment lines.
- New focused workspace tests: at most 780 nonblank/noncomment lines.
- Net new nonblank/noncomment production lines in `scripts/awf_role.py`: at most 80; delegation
  should normally make this value non-positive.
- No new dependency; installed Runtime remains standard-library only.
- One narrow workspace implementation, no command registry, VCS abstraction hierarchy, injected
  plugin framework or alternate implementation.
- One candidate Gate Review and at most two L3 repair/focused re-review rounds.
- If exact compatibility requires dual authority, changing durable manifest/digest bytes, changing
  recovery/rework ordering, operating remote Git/GitHub, or exceeding these budgets, stop with
  `PLAN_CONFLICT`.

## Acceptance criteria

- [ ] Task ID equals branch leaf; every changed path stays within frozen/closeout scope.
- [ ] Installed Runtime owns fresh workspace creation, metadata freeze/assert/digest and exact local
      delta import; production wrappers contain no independent fallback implementation.
- [ ] Workspace path is exact, event-contained and non-symlink/reparse; HEAD equals the dispatched
      commit and no remote/reflog/FETCH_HEAD source metadata remains.
- [ ] Provider-visible workspace has no authenticated remote and receives only the existing
      credential-stripped environment.
- [ ] Git-control assertion detects config/ref/hook/info/symlink/type/index drift before trusted Git
      mutation, including helper/config injection before any model-controlled Git invocation.
- [ ] Same-fixture durable model manifest/control digests remain byte-for-byte compatible with the
      current production oracle and existing rework fixtures.
- [ ] Exact delta identity covers base tree, model tree, patch length and patch SHA-256; imported
      trusted tree must equal the verified model tree.
- [ ] Empty delta, changed HEAD, added remote, metadata drift, redirected workspace/path and
      trusted-tree mismatch fail closed without remote/Bus/provider/Workflow effect.
- [ ] Structured argv/no-shell/static boundary tests prove the module exposes no arbitrary command,
      remote Git/GitHub, Bus, Store/journal, provider or lifecycle capability.
- [ ] Existing implement/review/rework recovery, Artifact validation, publication and no-replay
      tests remain unchanged in outcome and ordering.
- [ ] No Store/journal or legacy authority representation is read/written; no second workspace or
      lineage authority file exists.
- [ ] LOC/dependency/single-implementation budgets pass.
- [ ] Focused tests, full pytest/Ruff and ordinary Linux/Windows/macOS CI pass on candidate head.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; any L3 repair receives focused
      re-review by the same Reviewer.
- [ ] Closeout names one later Phase 3 seam without claiming Phase 3 complete or authorizing Store
      adoption, migration, deletion, default or release.

## Verification

- Local Mac: AST/static checks, direct disposable Git workspace smoke, same-fixture manifest/delta
  identity comparison, LOC/scope audit and `git diff --check` only.
- CI: focused installed workspace tests plus full role/recovery/rework tests, Ruff, installed-wheel
  and ordinary cross-platform jobs.
- Fault fixtures cover workspace parent/redirection, HEAD/remote/control/index drift, empty/change
  serialization, exact patch mutation and trusted-tree mismatch before any disallowed effect.
- Independent Review checks no hidden host discovery/credential path, manifest/digest compatibility,
  fail-closed path containment, exact delta/import, unchanged authority/recovery ordering and no
  old-body fallback.

## Required output

- installed narrow workspace/import API and immutable operation/delta facts;
- production wrapper delegation at only the existing workspace/import seams;
- focused compatibility, path, metadata, delta and side-effect-denial tests;
- ImplementationReport and independent ReviewReport;
- owner closeout naming exactly one later Phase 3 seam.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-033-workspace-import.md",
    "src/agent_workflow/runtime/workspace.py",
    "src/agent_workflow/runtime/__init__.py",
    "scripts/awf_role.py",
    "tests/test_runtime_workspace.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_command_boundary.py",
    "tests/test_awf_role.py",
    "tests/test_runtime_v2_rts011_acceptance.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-033-workspace-import.md",
    ".awf/artifacts/review-report-runtime-v2-rts-033-workspace-import.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "scripts/awf_role.py", "tests/test_runtime_workspace.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_workspace.py", "tests/test_runtime_core_boundary.py", "tests/test_runtime_command_boundary.py", "tests/test_awf_role.py", "tests/test_runtime_v2_rts011_acceptance.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credential, token, private URL, provider/business payload, retained-state content or personal environment fact may enter reports or committed fixtures.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-033-workspace-import.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-033-workspace-import.md"
}
-->
