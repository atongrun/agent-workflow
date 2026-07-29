# TaskCard: Agent Bus fork/PR live proof

## Goal

Create two bounded proof artifacts in the isolated model workspace. The trusted runner owns all
Git and PR publication.

## Allowed changes

- `docs/tasks/fork-pr-bus-proof-marker-20260729.md`
- `docs/tasks/fork-pr-bus-proof-implementation-report-20260729.md`

## Acceptance

- The marker states `fresh Agent Bus proof subprocess`.
- The ImplementationReport states `deterministic verification: pass`.
- No other path changes.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/fork-pr-bus-proof-marker-20260729.md",
    "docs/tasks/fork-pr-bus-proof-implementation-report-20260729.md"
  ],
  "verification_commands": [
    [
      "{python}",
      "-c",
      "from pathlib import Path; a=Path('docs/tasks/fork-pr-bus-proof-marker-20260729.md').read_text(encoding='utf-8'); b=Path('docs/tasks/fork-pr-bus-proof-implementation-report-20260729.md').read_text(encoding='utf-8'); assert 'fresh Agent Bus proof subprocess' in a; assert 'deterministic verification: pass' in b"
    ],
    ["git", "diff", "HEAD", "--check"]
  ]
}
-->
