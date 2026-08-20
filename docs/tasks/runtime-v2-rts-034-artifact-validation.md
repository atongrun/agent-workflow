# TaskCard: RTS-034 Artifact Validation Boundary

## Task ID

runtime-v2-rts-034-artifact-validation

## Goal

Move the existing TaskCard-bound Artifact identity, ImplementationReport/ReviewReport validation,
allowed-path/denylist/secret policy and postflight-result validation behind one narrow installed
Runtime v2 Artifact API.

This is an independently reversible local validation seam. The current
RunLedger/checkpoint/outbox/inbox/RunEvidence path remains the sole production authority and
recovery implementation. RTS-034 must preserve the exact current validation outcomes and call
ordering before trusted workspace import; it must not adopt the RTS-031 Store, redesign Artifact
policy or rework lineage, operate remote Git/GitHub/Agent Bus state, migrate state or change a
default.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@98818bee41ac92ceccc282f7069d19226e7249c3`
- **Task branch**: `codex/runtime-v2-rts-034-artifact-validation`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 3 successor seam
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`, sections 5.3, 6 and 12
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Passed prerequisites**: RTS-030 installed Core boundary, RTS-032 provider renderers and
  RTS-033 isolated workspace/trusted import boundary

Current production behavior is split between `scripts/awf_artifact_contract.py` and
`scripts/awf_role.py`: TaskCard/report path compilation, postflight contract parsing,
ImplementationReport and ReviewReport parsing/normalization, delta/denylist/secret/diff-result
gates, report trackedness, and exact report bytes/hashes. Compatibility wrapper names may remain
for focused fixtures and callers, but their production implementation must delegate to the
installed Runtime boundary without a silent old-body fallback.

## Frozen Artifact boundary

### Immutable contract and Artifact facts

The installed Runtime owns immutable values for:

- the exact Task ID, frozen TaskCard path, allowed paths and verification argv;
- the exact compiled ImplementationReport and ReviewReport repo-relative paths;
- a validated Artifact fact containing exact repo-relative path, byte length and SHA-256;
- the normalized ReviewReport object and its canonical payload hash where currently required; and
- one immutable postflight validation result for the exact observed workspace delta.

TaskCard parsing remains strict: invalid JSON, unknown postflight keys, empty/duplicate/absolute,
drive-qualified, backslash or parent-traversal paths deny. `{python}` expansion remains bound to the
exact interpreter supplied by the trusted wrapper. Runtime code must not discover host credentials,
configuration, Workflow Stage or mutable authority.

### Report validation

The installed API preserves current report policy and error outcomes:

1. ImplementationReport must exist, be readable UTF-8, non-empty and NUL-free. A present machine
   envelope is unique, duplicate-key-safe and has exactly the existing five fields; legacy prose
   remains compatible.
2. ReviewReport path remains repo-relative, contained, distinct from ImplementationReport and
   limited to the exact compiled owner-bound path.
3. ReviewReport remains non-empty, bounded to the existing 16 KiB normalized payload, contains
   exactly one supported machine object, rejects duplicate/unknown fields, full diff bodies and
   prohibited secret material, and enforces the existing PASS/REQUEST_CHANGES/BLOCKED invariants.
4. Embedded ReviewReport revalidation must reproduce the exact normalized object; tool exit zero
   is never a verdict.
5. Exact raw bytes, byte length and SHA-256 are computed only after validation and remain available
   to the existing checkpoint, terminal and recovery comparisons without changing their format.

No schema expansion, policy relaxation, legacy removal or automatic correction is authorized.

### Postflight observations and result

The trusted wrapper may execute the already-frozen verification argv and collect credential-free
local Git/filesystem observations. The installed Runtime owns the decision over those bounded
observations:

- the delta must be non-empty and every path must be exactly allowed;
- the current denylist applies at every path depth, including environment and generated artifacts;
- secret scanning covers only existing high-confidence detectors over added tracked lines and
  untracked regular-file content, reports labels rather than values and denies unreadable input;
- the exact full `git diff HEAD --check` result must pass; and
- a successful immutable result binds the exact ordered delta paths and observation digest.

Collection uses structured argv, NUL-safe path handling, disabled diff helpers and the existing
credential-stripped Git environment. The installed API cannot accept an arbitrary shell command,
invoke a provider, mutate Workflow authority, write a checkpoint, import a workspace delta,
commit/push/fetch or send/ACK transport.

### Production adoption and ordering

1. Existing delivery integrity, TaskCard selection, invocation authorization and recovery policy
   remain before provider start.
2. The postflight contract is parsed and frozen before provider execution exactly as today.
3. After provider success, report validation, frozen verification commands, report staging,
   workspace-state assertion and installed Artifact postflight validation remain in the existing
   order and all pass before RTS-033 trusted import.
4. ReviewReport import remains the existing exact local workspace operation; installed Artifact
   validation occurs before checkpoint/result routing and before any outgoing intent.
5. Existing `artifact_invalid` bounded recovery, exact report SHA comparison, rework lineage,
   publication, outbox/inbox, handler success and ACK ordering remain unchanged.
6. `scripts/awf_artifact_contract.py` and `scripts/awf_role.py` may expose compatibility wrappers,
   but the moved policy has one installed implementation and no old-body fallback.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-034-artifact-validation.md`
- `src/agent_workflow/runtime/artifact.py`
- `src/agent_workflow/runtime/__init__.py`
- `scripts/awf_artifact_contract.py`
- `scripts/awf_role.py`
- `tests/test_runtime_artifact.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_command_boundary.py`
- `tests/test_phase0_artifact_contract.py`
- `tests/test_awf_role.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-034-artifact-validation.md`
- `.awf/artifacts/review-report-runtime-v2-rts-034-artifact-validation.md`

After implementation, exact-head CI and independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-034-artifact-validation-implementation-report.md` and update only the
Phase 3 gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- RunLedger, RTS-031 Store/journal, checkpoint/outbox/inbox/RunEvidence format or Workflow
  transition changes.
- New Artifact fields, verdicts, secret detectors, denylist policy, size limit, TaskCard syntax or
  correction/retry budget.
- Workspace preparation/delta serialization/trusted import, rework lineage selection/restoration,
  durable workspace location or recovery-phase changes.
- Trusted commit/push/fetch, remote ref, fork, GitHub PR/CI/merge or terminal provenance behavior.
- Agent Bus send/receive/ACK, provider rendering/spawn/replay, status, lifecycle, exact stop,
  Feedback or CLI changes.
- Generic validation/schema/plugin framework, arbitrary command runner, new dependency, SQLite,
  Coordinator, Rust/Go production Runtime or native launcher.
- Dual write, legacy-state read/convert/delete, production migration, default switch, release,
  retained/live-event operation or destructive cleanup.

## Budgets and stop rules

- New installed Artifact module: at most 560 nonblank/noncomment lines.
- New focused Artifact tests: at most 900 nonblank/noncomment lines.
- Combined net nonblank/noncomment production lines in `scripts/awf_artifact_contract.py` and the
  moved sections of `scripts/awf_role.py`: must be negative; delegation must remove old policy
  bodies rather than copy them.
- No new dependency; installed Runtime remains standard-library only.
- One narrow Artifact implementation, no schema registry, validator hierarchy, command framework,
  policy plugin or alternate implementation.
- One candidate Gate Review and at most two L3 repair/focused re-review rounds.
- If exact compatibility requires dual policy, changing report/verdict bytes, weakening ordering,
  changing Artifact/recovery authority or exceeding these budgets, stop with `PLAN_CONFLICT`.

## Acceptance criteria

- [ ] Task ID equals branch leaf; every changed path stays within frozen/closeout scope.
- [ ] Installed Runtime owns TaskCard/report identity, report parsing/normalization, exact Artifact
      facts and postflight validation; production wrappers contain no independent fallback policy.
- [ ] Same TaskCard fixture compiles byte-for-byte compatible allowed paths, verification argv and
      exact ImplementationReport/ReviewReport paths before provider start.
- [ ] ImplementationReport legacy and machine-envelope outcomes remain exact, including malformed,
      duplicate-key, unknown/missing-field, empty, NUL and unreadable failures.
- [ ] ReviewReport normalization, 16 KiB bound, verdict invariants, deterministic evidence,
      diff-body/secret rejection and embedded revalidation remain exact.
- [ ] Validated report fact binds exact repo-relative path, raw byte length and SHA-256; changed
      bytes/path/size/object fail before checkpoint/result reuse or outgoing intent.
- [ ] Delta path scope, nested denylist, tracked/untracked high-confidence secret scan, unreadable
      input and full staged+unstaged diff-check results preserve current fail-closed outcomes.
- [ ] Postflight success binds exact observations and occurs after verification/report staging and
      workspace assertion but before trusted import; no failure reaches import, remote/Bus/provider
      replay or Workflow mutation.
- [ ] Structured argv/no-shell/static boundary tests prove the module exposes no arbitrary command,
      remote Git/GitHub, Agent Bus, provider, Store/journal, lifecycle or workspace-import ability.
- [ ] Existing `artifact_invalid`, implement/review/rework recovery, publication, no-replay and
      handler-success/ACK tests remain unchanged in outcome and ordering.
- [ ] No Store/journal or legacy authority representation is read/written; no second Artifact
      authority file exists.
- [ ] LOC/dependency/single-implementation budgets pass.
- [ ] Focused tests, full pytest/Ruff and ordinary Linux/Windows/macOS CI pass on candidate head.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; any L3 repair receives focused
      re-review by the same Reviewer.
- [ ] Closeout names one later Phase 3 seam without claiming Phase 3 complete or authorizing Store
      adoption, migration, deletion, default or release.

## Verification

- Local Mac: AST/static/import checks, disposable Git Artifact/postflight smoke, same-fixture
  contract/report/result identity comparison, LOC/scope audit and `git diff --check` only.
- CI: focused installed Artifact tests plus full role/recovery/rework tests, Ruff, installed-wheel
  and ordinary cross-platform jobs.
- Fault fixtures cover path/traversal/symlink containment, malformed and duplicate report objects,
  size/hash drift, empty/out-of-scope/denied delta, tracked/untracked secrets, unreadable files and
  diff-check failure before disallowed effects.
- Independent Review checks one policy implementation, exact compatibility, report/path/hash
  identity, fail-closed observation handling, unchanged authority/recovery ordering and no hidden
  host/credential/command/import capability.

## Required output

- installed narrow Artifact API and immutable contract/report/postflight facts;
- production delegation at only the existing Artifact validation seams;
- focused compatibility, schema, path/hash, delta, secret and side-effect-denial tests;
- ImplementationReport and independent ReviewReport;
- owner closeout naming exactly one later Phase 3 seam.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-034-artifact-validation.md",
    "src/agent_workflow/runtime/artifact.py",
    "src/agent_workflow/runtime/__init__.py",
    "scripts/awf_artifact_contract.py",
    "scripts/awf_role.py",
    "tests/test_runtime_artifact.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_command_boundary.py",
    "tests/test_phase0_artifact_contract.py",
    "tests/test_awf_role.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-034-artifact-validation.md",
    ".awf/artifacts/review-report-runtime-v2-rts-034-artifact-validation.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "scripts/awf_artifact_contract.py", "scripts/awf_role.py", "tests/test_runtime_artifact.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_artifact.py", "tests/test_runtime_core_boundary.py", "tests/test_runtime_command_boundary.py", "tests/test_phase0_artifact_contract.py", "tests/test_awf_role.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credential, token, private URL, provider/business payload, retained-state content or personal environment fact may enter reports or committed fixtures.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-034-artifact-validation.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-034-artifact-validation.md"
}
-->
