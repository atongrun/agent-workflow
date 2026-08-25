# RC.2 Phase 1B — Tracked Project Topology Implementation Report

## Outcome

The installed application now owns a strict, credential-free `.awf/project.yaml` boundary and the
two official RC.2 topology profiles:

- `uniform-opencode`: OpenCode Architect, Coder, and Reviewer;
- `role-specialized`: Pi Architect, OpenCode Coder, and Codex Reviewer.

`awf project init` creates the canonical file; `awf project check` performs a read-only load and
renders the normalized document. Neither command discovers online agents, reads Agent Bus, creates
machine bindings/profiles/workspaces, starts listeners, or mutates Workflow state.

## Safety boundary

- The YAML document has an exact key set and exact three roles; tools must match the selected
  official profile.
- Logical Agent Bus identities use one narrow credential-free identifier grammar.
- This bounded card accepts only `tool-default` in tracked topology. Explicit tool-native model
  refs remain the existing pre-PlanRun Human/Agent override until provider conformance establishes
  an unambiguous tracked grammar; arbitrary opaque strings cannot masquerade as credentials, hosts,
  or workspace paths.
- Duplicate YAML keys, oversized files, unknown keys, malformed refs, symlinked `.awf` or project
  paths, and replacement of an invalid existing file all fail closed.
- Writes use a same-directory staged file, flush/fsync, and atomic replacement. Existing valid
  project truth requires explicit `--replace`.

## Verification

- Focused topology/CLI/facade/schema suite: `107 passed`.
- Complete local suite: `972 passed, 5 skipped`.
- Ruff check/format and `git diff --check`: PASS.
- Independent L2 review initially returned `REQUEST_CHANGES` for ambiguous model strings and
  duplicate YAML keys; both findings received bounded repairs and adversarial regression coverage.
- Focused independent re-review: `PASS` with both P1 findings closed.

## Exclusions

Platform-local machine binding, `init` integration, lifecycle, deinit, provider expansion, MCP,
PlanRun model freezing, Agent Bus operations, and real-machine acceptance remain later Phase 1/2/3
cards.
