# RTS-046 Native-Manager Acceptance ImplementationReport

## Final status

`EXTERNAL_BLOCKED / evidence preserved`, with Windows login evidence additionally
`BLOCKED_BY_OWNER_AUTHORIZATION`. Phase 4B is not complete.

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

## Bounded repair and fresh continuation

RTS-047 preserved the absolute venv interpreter path without resolving its symlink, retained
executable hashing/exact action argv, covered all three renderer formats, passed independent L3
Review, full local tests and exact-head cross-platform CI.

Historical failed macOS scope remains failure evidence and cannot contribute to PASS.

## Fresh scope `rts046-live-20260822-02`

A new venv, profile, route, state/log roots, installed snapshot and LaunchAgent identity were created
after RTS-047 PASS. Doctor again proved configured/connected with no model and no installed/running
state. Install and start reached the installed AWF listener, confirming native venv re-entry.

The listener then exited before creating durable process/lease acceptance because the independently
installed Agent Bus CLI rejected structured `--on-argv` as unsupported and offered only legacy
`--on`. Fallback was forbidden: legacy shell handler syntax would weaken the accepted structured argv
boundary. Factual status showed installed current, running false, no run/checkpoint/model/terminal
facts, clean exact candidate and a payload-blind pending count of zero. No explicit queue/history or
payload command was run.

Normal exact uninstall removed only the unique `-02` definition, install record and registries.
Definition/install/process/lease absence passed; the credential-safe listener log remains retained.

## Windows pre-mutation result

Read-only entry checks proved Python 3.12, Git, AWF config, Agent Bus, running Task Scheduler and an
SSH identity equal to the active interactive-console user. A direct capability check then proved the
installed Agent Bus supports `--ack-on-receive` but not `--on-argv`. No Task Scheduler definition,
profile, state, process, lease or event was created. Windows post-SSH/restart/stop therefore did not
begin, and logout/login remains `BLOCKED_BY_OWNER_AUTHORIZATION`.

## Linux pre-mutation result

Multiple reachable existing Linux user hosts were audited without modification. Suitable Python
hosts had systemd-user running, but none had existing linger enabled and none had an existing AWF
configuration/Agent Bus client binding. One configured host was unavailable. The frozen TaskCard
forbids enabling linger or deploying/configuring Agent Bus, so no checkout, profile, service,
process, lease or event was created.

## Failure classification and next action

- macOS/Windows: external Agent Bus version/capability mismatch at the structured listener boundary;
- Linux: external prerequisite absent (existing linger and AWF/Bus configuration);
- Windows login: explicit owner-authorization window absent.

Agent Workflow does not replace or auto-deploy Agent Bus. The legal next action is external/operator
prerequisite alignment: provide an independently versioned Agent Bus client supporting `--on-argv`
on macOS/Windows, an already-lingering/configured Linux user host, and a scheduled Windows
logout/login window. Only then may RTS-046 continue under another fresh identity. No Phase 5 work is
authorized.
