# RC.2 Managed Architect Binding Repair

## Result

PASS. A fresh uniform-opencode topology exposed that the managed listener invokes `awf_plan` with
its immutable installed profile snapshot while the frozen ArchitectBinding records the authoring
source profile. The former validator rejected this exact durable relationship before model start.

## Repair

The validator now accepts only the registered installed snapshot of the frozen authoring source
with the same digest, then still requires exact workspace, tool and model facts. Unbound snapshot,
source, digest or remaining binding drift is denied.

## Evidence

- Fresh fork-based PlanStart delivery `264` remained terminal failed and was not ACKed, requeued or
  replayed.
- Focused suite: `184 passed, 1 skipped`.
- Candidate full suite: `1019 passed, 5 skipped`.
- Independent L3 lifecycle review: PASS.
- Ruff check, format check and `git diff --check`: PASS.
