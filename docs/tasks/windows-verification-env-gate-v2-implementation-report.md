# ImplementationReport: Default-locale verification boundary v2

## Baseline and Commits

- Base: `7b1bb290140e4c0db4efe314eed469dde99510ca`.
- Frozen v2 TaskCard: `dcade6e`.
- Final implementation commit: `d4487a29ea14d76b538fb035afeb5e4d464d8a9d`.
- This report is committed separately after the implementation SHA is stable.

## Changed Files

- `scripts/awf_role.py`
- `tests/test_awf_role.py`
- `docs/tasks/windows-verification-env-gate-v2-implementation-report.md`

No path outside the frozen three-path boundary changed after the v2 TaskCard commit.

## Delivered Boundary

- `verification_env()` derives from the existing credential-stripped `model_env()`.
- It removes `PYTHONUTF8` even when the listener or parent forced it to `1`.
- It retains `PYTHONIOENCODING=utf-8` for deterministic console output.
- `run_verifications()` alone uses the new helper.
- OpenCode, Codex, and other model/tool subprocesses retain the existing `model_env()` behavior,
  including token stripping and the Windows UTF-8 guard.
- Tests cover the helper contract, helper selection, and a real Python child process. The real-child
  test starts from a parent with `PYTHONUTF8=1`; the child must observe the variable absent and
  `PYTHONIOENCODING=utf-8`.

## Local Integration Evidence

- Focused boundary tests: `4 passed, 121 deselected`.
- Full suite: `162 passed`.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: `14 files already formatted`.
- Resource validation: `6/6 roles`, `4/4 workflows`, and `3/3 examples`.
- Allowed-path comparison and `git diff --check`: passed.

## Fresh Windows Evidence

A fresh isolated checkout was cloned from the remote v2 branch and verified clean at
`d4487a29ea14d76b538fb035afeb5e4d464d8a9d`. It did not reuse any historical checkout or the
separate UTF-8 closeout preparation checkout.

- External environment proof: `PYTHONUTF8_ABSENT`.
- Interpreter: `Python 3.12.10` on `win32`.
- Focused production-boundary tests: `4 passed, 121 deselected`.
- Ruff check for `scripts/awf_role.py` and `tests/test_awf_role.py`: passed.
- Ruff format check for the same files: `2 files already formatted`.
- Final Windows checkout status: clean and aligned with the remote v2 branch.

The focused run includes the real verification child, not only mocks or captured dictionaries.

## v1 Failure and Correction

The first prerequisite branch required the complete Windows suite before the downstream
portability fixes could merge. Windows correctly exposed the circular dependency: the new
verification-environment tests passed, while known baseline portability tests failed, including the
illegal quoted filename regression and locale-dependent CLI/resource paths.

The v1 TaskCard and branch remain preserved as failure evidence. v2 corrects the acceptance shape:
full integration remains mandatory locally, while Windows proves only this prerequisite's real
process boundary. The downstream portability TaskCard remains responsible for the complete Windows
suite and resource totals after this prerequisite merges.

## Strong Review and Remaining Risks

- Strong review found no credential leak, model-process behavior regression, scope violation, or
  false child-process proof.
- Complete Windows-suite acceptance is intentionally not claimed by this prerequisite.
- The original portability branch remains frozen and cannot be dispatched until v2 is merged and a
  replacement portability TaskCard is created from the new main baseline.
- No Agent Bus event was sent, read, consumed, acknowledged, or requeued. Events `49`, `50`, `51`,
  and `52`, historical evidence branches/checkouts, and the dirty detached postflight worktree were
  not modified or deleted.
- No VPS, listener service, Agent Bus configuration, protocol, storage, authentication, or
  dependency declaration changed.
