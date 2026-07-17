# Listener services (three-OS)

These are candidate operations templates for running the Agent Workflow listener under a native
service manager. The wrappers, launchd/systemd templates, WinSW definition, and `just` menu are
implemented, but their three-OS installation, reboot, crash-recovery, and unattended-listener
behavior has **not** been accepted end to end. Treat the commands below as an operations surface to
validate, not as proof that supervision already survives real failures on every OS.

This surface is outside the thin `awf` validation core. It supervises dogfood runner/listener
scripts that use external Agent Bus transport and model CLIs; it does not make those concerns part
of the core method contract.

## What's here

| File | OS | Role |
|------|----|----|
| `awf-listen-service.sh` | macOS / Linux | wrapper: sources `dispatch.env`, execs `awf_listen.py` |
| `awf-listen-service.cmd` | Windows | shim: runs the `.sh` via git-bash |
| `com.agentworkflow.listener.plist.template` | macOS | launchd service template |
| `agent-workflow-listener.service.template` | Linux | systemd service template |
| `agent-workflow-listener.xml` | Windows | WinSW service definition |

**No secrets live in any of these.** Tokens stay in `~/.config/awf/dispatch.env` (0600);
the wrapper sources it. Service definitions carry only role/repo/tool.

## Prerequisites

- `dispatch.env` in place — run `python scripts/awf_bootstrap.py` first.
- `just` (the ops menu). Install once:
  - macOS: `brew install just`
  - Linux: `sudo apt install just` or `cargo install just`
  - Windows: `winget install --id Casey.Just` or `scoop install just`

## Use (macOS / Linux)

From the repo root:

```bash
just role=reviewer repo=/path/to/agent-bus doctor            # readiness + is it installed?
just role=reviewer repo=/path/to/agent-bus install-service   # render template + load
just role=reviewer status
just role=reviewer logs
just role=reviewer down          # stop
just role=reviewer up            # start
just role=reviewer uninstall-service
```

`install-service` fills the template placeholders, validates it (`plutil -lint` /
`systemd-analyze verify`), and loads it. Re-running is idempotent (it boots out /
reloads first). systemd installs system-level under `/etc/systemd/system/`; launchd
installs a user LaunchAgent under `~/Library/LaunchAgents/`.

## Use (Windows — WinSW, manual once)

WinSW is a tiny (<1 MB) single-exe supervisor; unlike NSSM it's maintained and has
reliable crash detection.

1. Download `WinSW.exe` (x64) from https://github.com/winsw/winsw/releases.
2. Put it in `scripts/service/` and rename it `agent-workflow-listener.exe`
   (WinSW pairs `<name>.exe` with `<name>.xml`).
3. Edit `agent-workflow-listener.xml`, filling the `__PLACEHOLDERS__`:
   `__ROLE__`, `__REPO__`, `__TOOL__`, `__CMD_WRAPPER__` (absolute path to
   `awf-listen-service.cmd`), `__GITBASH__` (e.g. `C:\Program Files\Git\bin\bash.exe`).
4. From an admin shell:
   ```
   agent-workflow-listener.exe install
   agent-workflow-listener.exe start
   agent-workflow-listener.exe status
   ```
   Logs roll next to the exe (`agent-workflow-listener.out.log`).

## Stopping: service vs. graceful

- `just down` / `winsw stop` — stop the service now.
- `agent-bus send --to <role> --type control:shutdown` — ask the listener to finish
  its current handler and exit gracefully. With `Restart=on-failure` / WinSW
  `onfailure restart`, a *clean* exit does **not** trigger a restart, so a graceful
  shutdown stays down until you `up` again.
