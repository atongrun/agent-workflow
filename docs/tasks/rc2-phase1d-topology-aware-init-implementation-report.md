# RC.2 Phase 1D — Topology-Aware Local Init Implementation Report

## Outcome

Normal `awf init` now requires `.awf/project.yaml` before dependency discovery and derives local
role/tool defaults from that committed project truth. The file must belong to the exact worktree,
be tracked in `HEAD`, and have no staged or unstaged difference. Missing, untracked, dirty, malformed,
or symlinked topology fails before local discovery, profile/workspace creation, machine binding, or
listener activation.

`role-specialized` selects Pi Architect, OpenCode Coder, and Codex Reviewer when those tools are
available locally. `--roles` remains an explicit current-machine subset. An explicit init tool that
conflicts with committed topology is rejected; explicit model refs remain the existing Human-owned
selection. Current Phase 1 code does not claim OpenCode Architect: selecting that role from
`uniform-opencode` fails before mutation rather than falling back to Pi.

Legacy `awf init --card` and `awf enroll` branch before the new normal-init gate and retain their
compatibility behavior.

## Verification and review

- Focused CLI/facade/topology suite: `93 passed`.
- Complete local suite: `981 passed, 5 skipped`.
- Ruff check/format and `git diff --check`: PASS.
- Independent L2 review: PASS. The reviewer confirmed ordering, exact role defaults, local subset,
  no silent uniform fallback, explicit override boundary, and compatibility separation.

## Remaining work

Phase 2 must implement the missing provider/role cells before uniform-opencode can initialize an
Architect. Phase 1 still owns exact init/doctor/deinit integration, acceptance closeout, and Windows
zero-console lifecycle in separately bounded cards.
