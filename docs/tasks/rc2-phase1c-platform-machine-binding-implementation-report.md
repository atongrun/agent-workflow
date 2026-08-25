# RC.2 Phase 1C — Platform-Local Machine Binding Implementation Report

## Outcome

New normal machine initialization now persists `awf.machine-config.v1` under the platform AWF
configuration home:

```text
projects/<sha256-of-resolved-worktree>/machine.json
```

The directory key is deterministic for one exact resolved worktree and contains no plaintext private
path. The binding itself retains its existing machine-local exact repository, state-root, role,
profile, workspace, tool, and model-selection facts.

`load_machine()` reads the platform binding when present. A repository-local `.awf/machine.json`
remains a read-only compatibility source only when the platform binding is absent. If both exist,
loading fails closed. Normal init refuses legacy state before creating profiles or workspaces, and
`--replace` explicitly refuses to turn this card into an implicit migration.

## Preserved behavior

- Existing `awf.machine-config.v1` schema and exact role/profile/workspace validation are unchanged.
- Profile staging, exact Git workspaces, atomic multi-file commit, replacement backup, and rollback
  use the existing implementation.
- No lifecycle, listener, Agent Bus, Workflow, topology selection, ACK, retry, or recovery behavior
  changed.

## Safety and verification

- Machine binding file, repository `.awf`, platform config-home, `projects`, and repository-key
  directory symlinks fail closed.
- Legacy state prevents new writes and stays byte-identical on refusal.
- Distinct resolved worktrees produce distinct 64-hex keys.
- Focused facade/CLI/PlanLoop suite: `71 passed`.
- Complete local suite: `977 passed, 5 skipped`.
- Ruff check/format and `git diff --check`: PASS.
- Independent L2 review initially found a symlinked config-home bypass; the repair preserves the
  lexical absolute config-home for ancestor checks and adds a regression.
- Focused independent re-review: `PASS`.

## Remaining Phase 1 work

Topology-to-binding selection, local init/doctor/deinit product integration, run-owned acceptance
closeout, and Windows zero-console lifecycle remain separately bounded cards.
