# RTS-047 Native Venv Re-entry Repair Closeout

## Result

`PASS`. Native manager definitions and install records preserve the invoked absolute venv
interpreter path while continuing to bind executable bytes, action argv, profile, manager target
and definition identity.

## Evidence

- Focused lifecycle suite: **76 passed, 1 skipped**.
- Full repository suite: **877 passed, 5 skipped**.
- Compileall, Ruff, Ruff format and `git diff --check`: PASS.
- Independent L3 Review at `e35dca5`: PASS, zero findings.
- Exact-head ordinary CI `32547035193`: PASS.
- Exact-head Binary Feasibility `32547035173`: PASS across all cells and aggregates.
- Production net growth: 6 lines; focused test growth: 39 lines; no dependency or representation.

## Real-failure closure

The first RTS-046 macOS identity remains failed because its native definition resolved the venv
symlink to a base interpreter that could not import Agent Workflow. After RTS-047, a completely
fresh second identity entered the installed AWF listener successfully. It then stopped at the next
independent external boundary: the existing Agent Bus listener lacks structured `--on-argv`.

This confirms the executable repair without converting either acceptance scope into Phase 4B PASS.

## Scope

RTS-047 added no lifecycle abstraction, record format, migration, Agent Bus behavior, manager
operation, Agent Host, onboarding, Finding, Runtime Core or production change. Its rollback is a
code revert only; no state rollback exists or is permitted.
