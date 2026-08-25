# RC.2 Phase 2A Implementation Report

## Result

PASS. This card completes the closed nine-cell provider renderer and initial Architect semantic
assembly boundary. It does not claim real provider smokes, topology acceptance, README support, or
completion of the entire Phase 2/RC.2 scope.

## Provider decisions

| Provider | Reuse | Adapt | Reject |
|---|---|---|---|
| Codex | Existing non-interactive `exec`, bound stdin, and read-only Reviewer renderer. | Read-only Architect and `workspace-write` Coder renderer; common semantic JSON prompt. | Session resume, provider-owned Git/merge, unbounded permissions. |
| Pi | Existing no-session/no-approve/no-extension renderer and read-only tools. | Common semantic Architect prompt and Coder read/edit/write allowlist. | `bash`, provider-owned publication, session continuation. |
| OpenCode | Existing structured `run --dir` invocation and isolated Coder/Reviewer routes. | Architect closed semantic JSON prompt. | Built-in Plan/Build defaults, session-as-truth. |
| r4 candidate | Pure renderer/selection/coder-dispatch and semantic-boundary ideas. | Ported only onto fresh package/lifecycle main. | Old scripts, Plan/lifecycle/recovery changes and wholesale merge. |

## Authority boundary

The trusted parser validates the seven-field Architect payload and injects frozen base, repository,
role selection, artifact paths and postflight contract before the existing create-only TaskCard
persistence boundary. Provider processes retain no TaskCard, Git, PR, merge, checkpoint, outbox,
inbox or ACK authority. Pi Coder has no arbitrary shell tool.

## Verification

- Focused provider/lifecycle/Plan suite: `535 passed, 2 skipped`.
- Candidate full suite: `1011 passed, 5 skipped`.
- Ruff check, format check and `git diff --check`: PASS.
- Independent L2 review: initial two findings repaired; focused re-review PASS.

## Deferred evidence

Fresh real CLI/model smokes for non-topology cells, full Architect milestone/terminal provider
expansion, README support claims and two official topology E2Es remain later explicit RC.2 gates.
