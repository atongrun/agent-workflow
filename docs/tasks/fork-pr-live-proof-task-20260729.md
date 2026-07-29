# TaskCard: Fork/PR trusted-runner live proof

## Goal

Create the two bounded proof artifacts below. Do not access Git, remotes, credentials, or the
network. The trusted runner owns commit, fork push, fresh remote-SHA verification, and PR
publication.

## Allowed changes

- `docs/tasks/fork-pr-live-proof-marker-20260729.md`
- `docs/tasks/fork-pr-live-proof-implementation-report-20260729.md`

## Acceptance

- The marker states that the artifact was produced in an isolated model workspace.
- The ImplementationReport records the bounded artifact paths and deterministic verification.
- No other repository path changes.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/fork-pr-live-proof-marker-20260729.md",
    "docs/tasks/fork-pr-live-proof-implementation-report-20260729.md"
  ],
  "verification_commands": [
    [
      "{python}",
      "-c",
      "from pathlib import Path; a=Path('docs/tasks/fork-pr-live-proof-marker-20260729.md').read_text(encoding='utf-8'); b=Path('docs/tasks/fork-pr-live-proof-implementation-report-20260729.md').read_text(encoding='utf-8'); assert 'isolated model workspace' in a; assert 'deterministic verification: pass' in b"
    ],
    ["git", "diff", "HEAD", "--check"]
  ]
}
-->
