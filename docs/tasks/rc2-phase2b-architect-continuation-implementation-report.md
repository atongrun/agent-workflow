# RC.2 Phase 2B Implementation Report

## Result

PASS. Architect binding selection now governs initial, milestone-next and terminal-decision provider
invocations without changing Workflow authority. Task-producing paths use the common semantic JSON
payload and trusted assembly; terminal decisions retain their closed Decision format.

## Boundary

- Pi, OpenCode and Codex are selected only from the frozen `ArchitectBinding` and resolve their own
  bound executable.
- A milestone next-card JSON payload is strictly parsed and receives trusted base/repository/role/
  artifact facts before the existing TaskCard persistence and dispatch boundary.
- `MILESTONE_COMPLETE`, `BLOCKED`, terminal decision parsing, no-replay status, latest-main
  observation, CompletedCardFact and dispatch/ACK/Git authority remain unchanged.

## Verification

- Focused suite: `490 passed, 2 skipped`.
- Candidate full suite: `1017 passed, 5 skipped`.
- Ruff check, format check and `git diff --check`: PASS.
- Independent L2 review: initial renderer/payload mismatch repaired; focused re-review PASS.

## Deferred gates

Real provider smokes, official topology E2Es, MCP/status, support claims and release work remain
later RC.2 gates. No provider session resume or generic provider registry was introduced.
