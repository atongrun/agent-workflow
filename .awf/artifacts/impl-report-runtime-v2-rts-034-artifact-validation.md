# RTS-034 ImplementationReport

## Outcome

Candidate implementation moves TaskCard/report identity, exact raw Artifact facts,
ImplementationReport and ReviewReport validation, allowed-path/denylist/secret policy, and the final
postflight decision behind the installed `agent_workflow.runtime.artifact` API.

The operations scripts retain only compatibility views, structured local Git/filesystem observation
collection, frozen verification command execution, and handler error mapping. The old Artifact
contract and report/postflight policy bodies were removed; there is no alternate fallback, Store
adoption, remote operation, recovery representation change, migration, default switch or release.

## Boundaries and ordering

- Immutable Runtime values bind owner report paths, TaskCard paths/argv, exact Artifact path/size/raw
  SHA-256, normalized ReviewReport payload and postflight observation digest.
- Existing delivery authorization and provider recovery remain before Artifact handling.
- Existing verification, report staging and workspace assertion remain before postflight validation;
  every Artifact gate still passes before trusted import or outgoing intent.
- Existing `artifact_invalid`, report-SHA recovery, rework lineage, publication, handler-success and
  ACK ordering are unchanged.
- The installed module has no process, shell, provider, Store/journal, transport, remote Git/GitHub,
  lifecycle or workspace-import capability.

## Budget and validation

- Installed Artifact module: 559 nonblank/noncomment lines (budget 560).
- Focused Artifact tests: 247 nonblank/noncomment lines (budget 900).
- `scripts/awf_artifact_contract.py` and `scripts/awf_role.py` have a combined strongly negative
  production delta; moved policy bodies were deleted.
- No dependency was added.
- Local Mac validation: compileall, AST/export/effect-boundary checks, line-length/static audit,
  direct disposable TaskCard/report/postflight compatibility smoke, changed-path audit and
  `git diff --check` passed. Per repository policy, pytest/Ruff/cross-platform validation is assigned
  to candidate CI.

<!-- awf-implementation-report
{
  "summary": "Move existing Artifact validation policy behind one narrow installed Runtime API without changing authority, recovery, import, transport, migration, default or release boundaries.",
  "changed_files": [
    "src/agent_workflow/runtime/artifact.py",
    "src/agent_workflow/runtime/__init__.py",
    "scripts/awf_artifact_contract.py",
    "scripts/awf_role.py",
    "tests/test_runtime_artifact.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_command_boundary.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-034-artifact-validation.md"
  ],
  "commands": [
    "python3 -m compileall -q src/agent_workflow/runtime scripts/awf_artifact_contract.py scripts/awf_role.py tests/test_runtime_artifact.py tests/test_runtime_core_boundary.py tests/test_runtime_command_boundary.py",
    "direct disposable Runtime Artifact compatibility smoke",
    "AST exact export and no-effect boundary audit",
    "git diff --check"
  ],
  "tests": [
    "TaskCard and report path identity",
    "ImplementationReport bytes, size, SHA-256 and machine envelope",
    "ReviewReport normalization, verdict evidence, bound and embedded revalidation",
    "allowed-path and nested denylist",
    "tracked/untracked secret observation and unreadable input",
    "deterministic postflight result and diff-check failure",
    "repo-contained distinct Artifact paths",
    "compatibility wrapper and no-effect boundaries"
  ],
  "source_revision": "a5b350515deda5f2c15810b2f8c5193c3982d077"
}
-->
