# RC.2 Phase 1F — Run-Owned Acceptance Lifecycle Closeout

## Task ID

RC2-P1F-ACCEPTANCE-CLOSEOUT

## Goal

Provide a credential-free, run-owned lifecycle manifest and one exact automatic closeout primitive
for disposable acceptance profiles, preserving all non-lifecycle evidence.

## Scope

- Define a strict local manifest containing only exact profiles, profile digests, native manager
  identities and generated workspaces created for one disposable acceptance run.
- Freeze one immutable closeout record before lifecycle mutation.
- Stop and uninstall only manifest-owned exact profiles; verify each native installation and
  generated workspace is absent before recording closeout success.
- Return `CLEANUP_BLOCKED` without wildcard cleanup when identity, activity, workspace cleanliness
  or absence verification is unknown.
- Add deterministic facade/node lifecycle coverage for PASS, refusal, partial cleanup and evidence
  retention.

## Out of Scope

- Running a real acceptance, Agent Bus/event/ACK operations, PlanRun changes, legacy migration,
  Windows zero-popup implementation or observation, human deinit behavior, and production defaults.

## Working Context

- **Base**: `main@1eec55880400d33510d513da8f26863c78fbff8b`
- **Branch**: `codex/rc2-phase1f-acceptance-closeout`

## Acceptance Criteria

- [ ] Manifest is credential-free, exact-run-owned, and rejects symlinks, malformed/unknown fields
  and noncanonical identities before mutation.
- [ ] Closeout freezes evidence first, then performs only exact manifest-owned lifecycle operations.
- [ ] Unknown/active/dirty/drifted/partially removed identity remains `CLEANUP_BLOCKED` with evidence
  retained; no wildcard process, manager or workspace cleanup is possible.
- [ ] Successful closeout proves no run-owned native installation or generated workspace remains,
  while preserving logs, workflow state, outbox/inbox and failed evidence.

## Verification Commands

```bash
python -m pytest -q tests/test_facade.py tests/test_node.py tests/test_node_service.py
ruff check .
ruff format --check .
git diff --check
```

## Postflight Contract

<!-- awf-postflight
{
  "allowed_paths": [
    "src/agent_workflow/acceptance_lifecycle.py",
    "src/agent_workflow/facade.py",
    "src/agent_workflow/node.py",
    "src/agent_workflow/node_service.py",
    "tests/test_acceptance_lifecycle.py",
    "tests/test_facade.py",
    "tests/test_node.py",
    "tests/test_node_service.py",
    "docs/tasks/rc2-phase1f-acceptance-closeout.md",
    "docs/tasks/rc2-phase1f-acceptance-closeout-implementation-report.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_acceptance_lifecycle.py", "tests/test_facade.py", "tests/test_node.py", "tests/test_node_service.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
