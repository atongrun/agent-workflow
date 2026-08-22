# RTS-047 Native Venv Re-entry Repair ImplementationReport

## Result

Candidate repair complete. Native manager definitions and install records now preserve the absolute
interpreter path that invoked Agent Workflow rather than resolving a POSIX venv symlink to the base
interpreter.

## Implementation

- One internal `_python_executable()` helper normalizes `sys.executable` with `abspath` and does not
  resolve symlinks.
- launchd/systemd reconcile argv and Task Scheduler task-reconcile argv use that exact path.
- Install-record `python`, `python_sha256` and `action_argv` use the same path. Hashing follows the
  path to the executable bytes as before.
- Current-install validation recomputes the same path and digest, so executable absence/byte drift,
  action-argv drift, manager-target drift and definition drift remain fail-closed.
- No record format, lifecycle API, compatibility path or Windows process/incarnation behavior changed.

## Focused regression

One POSIX symlink regression creates a real venv-shaped interpreter symlink and proves:

- launchd, systemd and Task Scheduler definitions contain the invoked shim path and not its resolved
  base target;
- the install record preserves the shim path and exact action argv;
- executable SHA-256 remains bound; and
- current-install validation accepts the exact self-consistent record.

Windows skips only this POSIX-symlink test; its existing venv redirector, installed-profile,
Task Scheduler and exact-stop regressions remain in the focused suite.

## Verification

- Compileall: PASS.
- Focused lifecycle suite: **76 passed, 1 skipped**.
- Full repository suite: **877 passed, 5 skipped**.
- Ruff: PASS.
- Ruff format check: PASS.
- `git diff --check`: PASS.
- Production diff: 12 additions / 6 deletions, net +6; below the 25-line budget.
- Focused test diff: 39 additions; below the 100-line budget.
- No dependency, representation, migration or external operation.

## Scope and next gate

Only `node_service.py`, `test_node_service.py` and frozen TaskCard/evidence files changed. RTS-047
does not itself operate a native manager or claim acceptance. Independent L3 Review returned `PASS`
at `e35dca5`; exact-head CI remains before RTS-046 may resume with a fresh scope. The failed macOS
`-01` scope remains failure evidence forever.
