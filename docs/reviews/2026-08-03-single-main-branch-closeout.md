# Single-main Branch Closeout

## Decision

`main` is the only long-lived branch. Feature and proof branches are temporary transport for
review and execution; they must be deleted after their PR, evidence, or recovery purpose reaches a
terminal state. Historical evidence belongs in versioned reports plus `archive/*` tags, not in a
permanent branch list.

This policy was confirmed on 2026-08-03. It does not rewrite `main`, delete archive tags, or merge
historical proof work into product history.

## Retirement Ledger

Each non-main tip that is not already reachable from `main` has one recovery tag. A tag preserves
the exact commit graph while keeping the branch namespace small.

| Retired purpose | Final tip | Recovery tag |
| --- | --- | --- |
| Semantic loop v1 | `9c31f48` | `archive/retired-branch/semantic-loop-20260726-v1` |
| Semantic loop v2 | `b4982e3` | `archive/retired-branch/semantic-loop-20260726-v2` |
| Semantic loop v3 | `029216b` | `archive/retired-branch/semantic-loop-20260726-v3` |
| Semantic loop v4 | `339158e` | `archive/retired-branch/semantic-loop-20260726-v4` |
| Semantic loop v5 accepted execution | `451cc60` | `archive/retired-branch/semantic-loop-20260726-v5` |
| PR 27 control-plane proof | `d3db883` | `archive/retired-branch/pr27-control-plane-proof` |
| PR 27 disposable proof input | `f211448` | `archive/retired-branch/pr27-disposable-proof-input` |
| Fork PR Bus proof B | `0044c22` | `archive/retired-branch/fork-pr-bus-live-b` |
| Fork PR Bus proof C | `eab7468` | `archive/retired-branch/fork-pr-bus-live-c` |
| Fork PR live proof A | `fa4138a` | `archive/retired-branch/fork-pr-live-a` |
| Dogfood control-plane handoff | `faf97bf` | `archive/retired-branch/dogfood-control-plane-handoff` |
| Durable phase checkpoint recovery | `8019db2` | `archive/retired-branch/durable-phase-checkpoint-recovery` |
| Codex review stdin compatibility | `fb2eaa8` | `archive/retired-branch/fix-codex-review-stdin-compat` |
| Legacy recovery manifest | `3d0b633` | `archive/retired-branch/p0-recovery-legacy-manifest` |
| Private Bus proxy bypass | `b35ec61` | `archive/retired-branch/private-bus-proxy-bypass` |
| Windows ACL path safety | `d2f32ee` | `archive/retired-branch/windows-acl-check-path-safe` |

The accepted semantic-loop result remains described by
[`live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md`](../tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md).
PR 27 and the fork proof sequence remain described in `HANDOFF.md` and their task reports. Tips
already reachable from `main` need no additional recovery tag.

## Worktree Disposition

Clean branch worktrees are detached at their existing commits before branch deletion. Stale
worktree registrations are pruned without deleting their directories. Detached historical
checkouts may remain on disk, but they do not own branch refs or define repository truth.

The two user-owned untracked files in the primary checkout are outside this closeout and remain
untouched:

- `docs/reviews/2026-08-01-agent-agnostic-architecture-review.md`
- `scripts/awf_supervisor.py`

## Recovery

Recreate a short-lived branch only when an audit needs the exact historical tree:

```bash
git switch -c audit/<name> archive/retired-branch/<name>
```

Delete that audit branch after use. Archive tags and the documents above are the durable record.
