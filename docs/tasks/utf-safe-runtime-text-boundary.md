# TaskCard: P1-1a UTF-safe Runtime Text Boundary

## Task ID

AWF-USABILITY-P1-1A

## Goal

Make the executor, native lifecycle manager, and node log-reader text boundaries decode bytes as
UTF-8 with deterministic replacement, including under a Windows GBK default locale, without
changing process or Workflow semantics.

## Frozen contract

- `awf_executor.run()` and `awf_executor.start()` use the same UTF-8 plus `replace` defaults when
  text mode is selected. Explicit binary-mode callers remain binary.
- Native service-manager output is decoded as UTF-8 with deterministic replacement rather than
  the host locale. Failure diagnostics retain executable, exit code, and decoding-policy
  provenance without including raw manager output.
- Node log files are read as bytes, normalized at the UTF-8 boundary, and rendered without raising
  when the destination console uses a narrower encoding such as GBK.
- Structured argv, stdin policy, return code, timeout, service lifecycle, status JSON, provider
  selection, model invocation, Agent Bus delivery, ACK, and Feedback behavior are unchanged.
- No dependency is added.

## Working context and parallel boundary

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@c39383e37733d8a0e96b4810ea437be7e2ddd548`
- **Branch**: `codex/utf-safe-runtime-text-boundary`
- **Parallel P0-5**: `codex/implement-rework-transition` owns `scripts/awf_role.py`,
  `scripts/awf_control_plane.py`, its focused tests, and shared current-state/runtime docs.
- This package does not modify any P0-5 production, test, schema, checkpoint, or shared-doc path.

## Scope

- Centralize the existing executor text-mode defaults so run and Popen paths cannot drift.
- Make the native-manager subprocess boundary explicit about UTF-8 replacement.
- Make systemd/file log rendering safe for a narrower console encoding.
- Add exactly two focused regressions using existing test modules and fixtures.

## Out of scope

- P1-1 causal status, `--explain`, Feedback status, status JSON/schema, Agent Bus, ACK, requeue,
  recovery, dispatch, provider/model invocation, service lifecycle, argv changes, P1-2, P1-3, P2,
  Phase B, or Agent Host.
- Any change to `scripts/awf_role.py`, `scripts/awf_control_plane.py`, checkpoint/schema, manifest,
  CLI, status, Feedback, or shared repository-truth/runtime documents.
- Any read, operation, ACK, requeue, recovery, redispatch, or reuse of events 163, 166, 173, or
  any retained business event.

## Verification level and budget

- **Level A/B; exactly two focused tests.**
- One executor test emits invalid UTF-8 bytes and non-GBK Unicode through a representative real
  subprocess, proving deterministic replacement while preserving argv and return code; it also
  checks the matching Popen text options without starting a second real child.
- One node-service test reads invalid UTF-8 and non-GBK Unicode from a log through a GBK console
  fixture, proving deterministic safe rendering, and asserts native-manager decoding options plus
  return code/argv preservation.
- Local Mac verification is limited to compile/static/diff checks. Pytest and Ruff run only in
  GitHub CI.

## Acceptance criteria

- [ ] UTF-8 text-mode run and Popen boundaries both default to `errors="replace"`.
- [ ] Invalid UTF-8 becomes U+FFFD deterministically before narrower-console rendering.
- [ ] A GBK destination never raises on non-GBK Unicode and receives deterministic replacement.
- [ ] Native manager argv, return code, timeout, and lifecycle calls remain unchanged.
- [ ] Failure diagnostics do not include raw native-manager stdout/stderr.
- [ ] Exactly two focused tests and the full GitHub CI matrix pass.
- [ ] An independent reviewer approves the exact PR head before merge.
- [ ] A fresh pre-merge P0-5 file comparison still proves no overlap.

## Required output

- `docs/tasks/utf-safe-runtime-text-boundary-implementation-report.md`
- Minimal code/tests, Lore commit, PR, green CI, exact-head independent review, fresh
  mergeability/parallel-overlap gate, merge, post-merge main/CI proof, and short-branch cleanup.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/utf-safe-runtime-text-boundary.md",
    "docs/tasks/utf-safe-runtime-text-boundary-implementation-report.md",
    "src/agent_workflow/node_service.py",
    "scripts/awf_executor.py",
    "tests/test_node_service.py",
    "tests/test_awf_executor.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_node_service.py", "tests/test_awf_executor.py"],
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."]
  ]
}
-->
