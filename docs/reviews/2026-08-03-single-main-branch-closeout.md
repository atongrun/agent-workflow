# Single-main Branch Closeout

## Decision

`main` is the only long-lived branch. Feature and proof branches are temporary review and delivery
mechanisms; delete them after their purpose reaches a terminal state.

Git tags are reserved for named product releases or explicit project milestones. Do not create tags
for failed attempts, execution events, proof runs, retired branches, or other process evidence.

## Durable Project Truth

Keep information only when it helps future product work:

- accepted behavior in `main`;
- regression protection in tests;
- user-facing or architectural decisions in versioned documentation;
- release points in version tags.

Implementation reports may summarize meaningful results, but the repository does not promise exact
recovery of every intermediate or failed commit. Retired evidence refs may be permanently deleted.

## Worktree Disposition

Clean historical worktrees were detached before their branch refs were deleted. Detached checkouts
may remain on disk, but they do not define repository truth or justify retaining a branch or tag.

The two user-owned untracked files in the primary checkout were outside this closeout and remain
untouched:

- `docs/reviews/2026-08-01-agent-agnostic-architecture-review.md`
- `scripts/awf_supervisor.py`

## Operating Rule

Close a completed change by merging or committing the accepted result to `main`, recording only the
documentation that remains useful, and deleting temporary refs. Create a tag only when publishing a
named release or when the project explicitly declares a durable milestone.
