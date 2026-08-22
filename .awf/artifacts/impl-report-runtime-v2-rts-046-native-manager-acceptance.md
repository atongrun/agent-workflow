# RTS-046 Native-Manager Acceptance ImplementationReport

## Current status

`REQUEST_CHANGES` after the first real macOS start; acceptance evidence preserved. Phase 4B is not
complete.

No model, business event, provider, Runtime Core, Agent Bus mutation, Finding workflow, remote
manager or Windows session operation occurred.

## Entry audit

- macOS: current candidate installed into a fresh Python 3.12 venv; existing Agent Bus configuration
  passed credential-safe doctor; launchd GUI domain was available; profile was uninstalled/current
  state stopped before mutation.
- Windows: Python 3.12, Git, Agent Bus, AWF config and Task Scheduler were present; the SSH identity
  matched the active console user. No manager mutation was performed because the exact candidate
  failed on macOS first.
- Linux: every reachable audited host had systemd-user running but existing linger was absent or
  unavailable; no host had an existing AWF config. RTS-046 prohibits enabling linger or creating an
  Agent Bus deployment/config, so Linux stopped before install.

## macOS scope and observed failure

- Scope: `rts046-live-20260822-01`
- Fresh source profile: role `architect`, tool `none`, unique empty control route, fresh state/log
  roots and unique LaunchAgent label.
- `awf node doctor --json`: configured/connected true, model not applicable, installed/running false,
  next action `install`.
- `awf node install`: success; deterministic launchd definition and installed record were current.
- `awf node start`: fail-closed after the bounded listener-lease wait. No process record or lease was
  created.
- Factual status reported installation current, lifecycle running false, zero delivery checkpoints,
  no run/model/terminal facts and exact candidate workspace clean. The normal status projection also
  observed a payload-blind pending count of zero; no explicit queue/history/payload command was run.
- Exact listener log repeated one pre-listener error:
  `ModuleNotFoundError: No module named 'agent_workflow'` while the manager invoked the base Python.

## Root cause

The acceptance app was installed in a fresh venv. Native definition and install-record code uses
`Path(sys.executable).resolve()`. On POSIX, the venv interpreter is a symlink, so this resolves to
the Homebrew base Python path. Agent Workflow is installed only in the venv; launchd therefore
cannot import `agent_workflow.cli` and exits before process/incarnation evidence or Bus listener
entry.

This is a local L3 executable-identity/lifecycle defect, not a launchd, Agent Bus, credential,
business-event or product-boundary failure. Bypassing it with source `PYTHONPATH`, installing the app
into the base interpreter or manually editing the manager definition would manufacture acceptance
and was not attempted.

## Safe cleanup and retained evidence

Because no process record or lease existed, normal exact `awf node uninstall` was used. It removed
only the unique LaunchAgent definition, install record and registries. Post-uninstall checks proved:

- definition absent;
- install record absent;
- process record absent;
- listener lease absent;
- desired-state evidence retained; and
- credential-safe listener log retained.

No stronger kill, PID scan, manual record edit or shared configuration deletion occurred.

## Required repair gate

Freeze a bounded RTS-047 repair that preserves the absolute venv interpreter path without resolving
its symlink for native re-entry, while still hashing the executable bytes and binding exact action
argv. It must cover launchd/systemd/Task Scheduler rendering and current install validation, add one
focused venv-symlink regression, and change no record format or external boundary.

After RTS-047 independent Review/CI PASS, RTS-046 must restart with fresh acceptance identities.
Historical failed macOS scope remains failure evidence and cannot contribute to PASS.
