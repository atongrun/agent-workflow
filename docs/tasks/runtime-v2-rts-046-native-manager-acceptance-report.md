# RTS-046 Fresh Native-Manager Acceptance Report

## Outcome

`EXTERNAL_BLOCKED / evidence preserved`.

Windows logout/login is separately `BLOCKED_BY_OWNER_AUTHORIZATION`. Phase 4B remains open and
Phase 5 did not start.

Two fresh macOS scopes reached successive fail-closed boundaries. No Linux or Windows manager was
mutated because read-only entry checks proved their required external prerequisites absent.

## Acceptance scope

| Scope | Environment | Result | Durable meaning |
|---|---|---|---|
| `rts046-live-20260822-01` | macOS arm64, Python 3.12, fresh installed venv, unique launchd profile/state/log/label | failed before listener entry | exposed venv symlink resolution defect; never PASS |
| RTS-047 repair | local/CI five-target evidence | PASS | preserves invoked venv interpreter path; does not itself prove manager acceptance |
| `rts046-live-20260822-02` | macOS arm64, new venv/profile/state/log/label | failed at Agent Bus listener capability | confirms executable repair; never PASS |
| Linux entry audit | multiple existing Linux user hosts | blocked before install | no existing linger plus no existing AWF/Bus config on suitable hosts |
| Windows entry audit | existing Windows interactive-console user | blocked before Task Scheduler mutation | Agent Bus lacks structured `--on-argv`; logout/login owner window absent |

## Environment and identity rules

- Candidate: exact RTS-047 reviewed/CI-green installed application descended from RTS-046.
- Every macOS scope used a fresh venv, source profile, installed snapshot/registry, state root, log,
  empty control route and deterministic LaunchAgent label.
- Profiles used `role=architect`, `tool=none`; no provider/model was applicable.
- Existing Agent Bus configuration was referenced only as an independent dependency. No Bus install,
  upgrade, endpoint/token change or event operation occurred.
- Repository worktree remained clean at the exact acceptance head.

Private paths, endpoints, usernames and credentials are deliberately omitted. Repository evidence
retains only opaque identity digests and boolean/payload-blind observations where needed.

## Commands exercised

### macOS `-01`

```text
fresh venv install
awf node doctor --json
awf node install
awf node start
awf node status --json
awf node logs
awf node uninstall
exact definition/install/process/lease absence checks
```

Doctor passed configuration, workspace and Agent Bus health with model not applicable. Start timed
out before a listener lease. Logs proved the native definition invoked the resolved base Python,
which could not import the venv-installed application. Normal uninstall succeeded; definition,
install record, process record and lease were absent afterward, while desired/log evidence remained.

### RTS-047 validation

```text
compileall
focused node/node_service/facade pytest
full pytest
ruff check
ruff format --check
git diff --check
ordinary cross-platform CI
five-target Binary Feasibility
independent L3 review
```

All passed. The failed `-01` scope was not retried or reused.

### macOS `-02`

```text
new venv install
awf node doctor
awf node install
awf node start
awf node status
awf node logs
awf node uninstall
exact definition/install/process/lease absence checks
```

The listener entered installed AWF, proving RTS-047. Agent Bus then rejected `--on-argv` before a
stable listener incarnation. Status remained installed/current but running false, with no
run/checkpoint/model/terminal facts. Its normal read-only projection observed pending count zero;
no direct queue/history/payload command occurred. The exact disposable definition/install/process/
lease state was absent after normal uninstall, and the log was retained.

### Linux and Windows entry checks

Linux commands were limited to OS/Python/Git presence, systemd-user health, existing linger and
existing config/client presence. Windows commands were limited to OS/Python/Git, existing config,
Task Scheduler service, console-user equality and Agent Bus listener-help capability. No manager
install/start/stop/restart/uninstall command ran on either host.

## Observed blockers

### External Agent Bus compatibility

The existing macOS and Windows Agent Bus clients do not accept the structured `--on-argv` listener
contract required by current Agent Workflow. Falling back to legacy `--on`, shell text or manual
handler wiring would weaken the structured execution boundary and is prohibited. Agent Workflow
does not own Agent Bus installation or upgrade.

### Linux prerequisites

No audited suitable Linux user host already had both linger enabled and an AWF/Agent Bus
configuration. Enabling linger changes host login/service policy, and deploying/configuring Agent
Bus is outside RTS-046. The systemd acceptance therefore correctly stopped before installation.

### Windows owner window

The Windows identity matched the current interactive-console user and Task Scheduler was available,
but the Bus compatibility blocker prevented safe listener start. Independently, no owner-authorized
logout/login window was supplied. Logout/login was not simulated, inferred or triggered.

## Safety and cleanup

- No model, provider, business handler, TaskCard run, business event, ACK, retry, requeue, recovery or
  dispatch occurred.
- No Agent Bus, OS security, login policy, linger, Runtime Core, Finding, Agent Host or onboarding
  setting changed.
- No manual process signal, process-name scan, record edit, PYTHONPATH or base-interpreter install
  was used.
- Both macOS definitions/install records/registries were removed through normal exact uninstall.
- Failed-scope logs and desired-state evidence remain retained in disposable local roots.
- Linux and Windows created no acceptance manager/state resources.

## Limitations and legal next action

RTS-046 does not prove real launchd steady running/restart/stop, any systemd-user sequence, Task
Scheduler post-SSH/restart/exact-stop, or Windows logout/login. Phase 4B cannot close.

The only legal continuation is a new fresh acceptance identity after all external prerequisites are
provided:

1. independently versioned Agent Bus clients with `--on-argv` on macOS and Windows;
2. an already-lingering Linux user host with existing AWF/Bus configuration; and
3. an explicitly scheduled Windows logout/login authorization window.

Do not alter Runtime/lifecycle identity, deploy Agent Bus from AWF, or start Phase 5 to clear these
blocks.
