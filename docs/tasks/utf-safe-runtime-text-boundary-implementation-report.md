# Implementation Report: P1-1a UTF-safe Runtime Text Boundary

## Result

The runtime text boundary now treats UTF-8 plus deterministic replacement as one explicit policy
across executor text-mode `run`/`Popen`, native lifecycle-manager capture, and node log reading.
A narrow console renderer prevents non-GBK Unicode or U+FFFD from raising when stdout uses GBK.

## Changed files

1. `docs/tasks/utf-safe-runtime-text-boundary.md`
2. `docs/tasks/utf-safe-runtime-text-boundary-implementation-report.md`
3. `scripts/awf_executor.py`
4. `src/agent_workflow/node_service.py`
5. `tests/test_awf_executor.py`
6. `tests/test_node_service.py`

No P0-5 production, test, checkpoint/schema, or shared current-state/runtime-document path changed.

## Simplifications and behavior

- Reused one executor encoding/error constant pair instead of leaving run and Popen defaults able
  to drift.
- Kept explicit binary-mode executor callers binary; no caller or argv was changed.
- Replaced locale-derived native-manager decoding with explicit UTF-8/`replace` while retaining
  executable, return code, and decoding-policy provenance in failures.
- Removed raw native-manager output from exception text so an arbitrary manager payload is not
  copied into diagnostics.
- Read listener logs as bytes, decode once at the UTF-8 boundary, and safely project normalized
  text onto the active console encoding. Systemd journal rendering uses the same writer.

## Focused regressions

- Executor: a real subprocess emits valid non-GBK Unicode followed by invalid UTF-8. The test
  asserts exact U+FFFD replacement, argv and return code, then verifies identical Popen text-mode
  options without starting another process.
- Node service: a fake native manager proves structured argv, return code, timeout and explicit
  decode policy; a byte log containing non-GBK Unicode and invalid UTF-8 is rendered through a
  strict GBK console with deterministic `?` replacement and no exception.

Exactly two focused test functions were added.

## Verification

Local Mac checks completed:

- `python3 -m py_compile scripts/awf_executor.py src/agent_workflow/node_service.py tests/test_awf_executor.py tests/test_node_service.py`
- `git diff --check`
- exact changed-path comparison against frozen TaskCard commit `1a2ffbc`
- manual inspection that no P0-5 path is present

Per the frozen contract, Pytest and Ruff were not run on the Mac. Full GitHub CI and independent
exact-head review are pending at report creation.

## Remaining risks

- Narrow-console output intentionally replaces characters that the destination encoding cannot
  represent. It prevents crashes but cannot make a GBK-only consumer display emoji losslessly.
- Manager stdout/stderr contents are no longer copied into failure exceptions. Operators retain
  executable/exit/decode provenance; deeper raw manager diagnostics must be inspected at their
  native source under the existing credential-safety rules.
- The package does not implement P1-1 causal status or independent Feedback state; those remain in
  the primary P1-1 lane after P0-5.
