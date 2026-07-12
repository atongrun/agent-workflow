# Agent Workflow — ops menu (listener service supervision, three-OS).
#
# A fixed verb menu so a weak model (or you) can run/stop/inspect the listener
# without remembering launchctl/systemctl/WinSW syntax. Each mutating verb guards
# before it acts (idempotent). Secrets never appear here — they live in the 0600
# ~/.config/awf/dispatch.env that the service wrapper sources.
#
# `just` is NOT auto-installed. Install it once per machine:
#   macOS:    brew install just
#   Linux:    sudo apt install just   (or: cargo install just)
#   Windows:  winget install --id Casey.Just   (or: scoop install just)
#
# Configure the listener for THIS machine by overriding these on the command line,
# e.g.  just role=reviewer repo=/root/agent-bus install-service
# or set them once via environment (AWF_ROLE / AWF_REPO / AWF_TOOL).

role := env_var_or_default("AWF_ROLE", "coder")
repo := env_var_or_default("AWF_REPO", "")
tool := env_var_or_default("AWF_TOOL", "opencode")

scripts_dir := justfile_directory() / "scripts"
service_dir := scripts_dir / "service"
wrapper_sh  := service_dir / "awf-listen-service.sh"
wrapper_cmd := service_dir / "awf-listen-service.cmd"

# Default: run the readiness check.
default: doctor

# --- doctor: is this machine ready + is the service installed? --------------
doctor:
    @echo "== awf doctor (role={{role}}) =="
    @command -v just >/dev/null 2>&1 && echo "[+] just present" || echo "[!] just missing"
    @python3 "{{scripts_dir}}/awf_handoff_check.py" --role "{{role}}" {{ if repo != "" { "--repo " + repo } else { "" } }} || true
    @just _svc-status || true

# --- install-service: render the OS template + load it (idempotent) ---------
[macos]
install-service: _need-repo
    #!/usr/bin/env bash
    set -eu
    label="com.agentworkflow.listener.{{role}}"
    dest="$HOME/Library/LaunchAgents/${label}.plist"
    log="$HOME/Library/Logs/awf-listener-{{role}}.log"
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    sed -e "s|__ROLE__|{{role}}|g" -e "s|__REPO__|{{repo}}|g" \
        -e "s|__TOOL__|{{tool}}|g" -e "s|__PYTHON__|$(command -v python3)|g" \
        -e "s|__WRAPPER__|{{wrapper_sh}}|g" -e "s|__LOG__|${log}|g" \
        "{{service_dir}}/com.agentworkflow.listener.plist.template" > "$dest"
    plutil -lint "$dest" >/dev/null
    # bootout first (ignore error) so re-install is idempotent.
    launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$dest"
    echo "installed + loaded ${label} (log: ${log})"

[linux]
install-service: _need-repo
    #!/usr/bin/env bash
    set -eu
    unit="agent-workflow-listener-{{role}}.service"
    dest="/etc/systemd/system/${unit}"
    sudo sed -e "s|__ROLE__|{{role}}|g" -e "s|__REPO__|{{repo}}|g" \
        -e "s|__TOOL__|{{tool}}|g" -e "s|__PYTHON__|$(command -v python3)|g" \
        -e "s|__USER__|$(id -un)|g" -e "s|__HOME__|$HOME|g" \
        -e "s|__WRAPPER__|{{wrapper_sh}}|g" \
        "{{service_dir}}/agent-workflow-listener.service.template" | sudo tee "$dest" >/dev/null
    sudo systemd-analyze verify "$dest" || true
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$unit"
    echo "installed + started ${unit}"

[windows]
install-service: _need-repo
    @echo "Windows: WinSW is manual (download WinSW.exe once). See scripts/service/README.md."
    @echo "  1) copy scripts/service/agent-workflow-listener.xml next to WinSW.exe (renamed agent-workflow-listener.exe)"
    @echo "  2) fill __ROLE__/__REPO__/__TOOL__/__CMD_WRAPPER__/__GITBASH__ placeholders"
    @echo "  3) agent-workflow-listener.exe install && agent-workflow-listener.exe start"

# --- uninstall-service ------------------------------------------------------
[macos]
uninstall-service:
    -launchctl bootout "gui/$(id -u)/com.agentworkflow.listener.{{role}}" 2>/dev/null
    -rm -f "$HOME/Library/LaunchAgents/com.agentworkflow.listener.{{role}}.plist"
    @echo "uninstalled com.agentworkflow.listener.{{role}}"

[linux]
uninstall-service:
    -sudo systemctl disable --now "agent-workflow-listener-{{role}}.service" 2>/dev/null
    -sudo rm -f "/etc/systemd/system/agent-workflow-listener-{{role}}.service"
    -sudo systemctl daemon-reload
    @echo "uninstalled agent-workflow-listener-{{role}}"

[windows]
uninstall-service:
    @echo "Windows: agent-workflow-listener.exe stop && agent-workflow-listener.exe uninstall"

# --- up / down: start & stop the already-installed service ------------------
[macos]
up:
    launchctl kickstart -k "gui/$(id -u)/com.agentworkflow.listener.{{role}}"
[linux]
up:
    sudo systemctl start "agent-workflow-listener-{{role}}.service"
[windows]
up:
    @echo "Windows: agent-workflow-listener.exe start"

[macos]
down:
    launchctl bootout "gui/$(id -u)/com.agentworkflow.listener.{{role}}" 2>/dev/null || true
[linux]
down:
    sudo systemctl stop "agent-workflow-listener-{{role}}.service"
[windows]
down:
    @echo "Windows: agent-workflow-listener.exe stop"

# --- status -----------------------------------------------------------------
status: _svc-status

[macos]
_svc-status:
    @launchctl print "gui/$(id -u)/com.agentworkflow.listener.{{role}}" 2>/dev/null | grep -E "state =|pid =" || echo "[!] service not loaded"
[linux]
_svc-status:
    @systemctl is-active "agent-workflow-listener-{{role}}.service" 2>/dev/null || echo "[!] service not active"
[windows]
_svc-status:
    @echo "Windows: agent-workflow-listener.exe status"

# --- logs -------------------------------------------------------------------
[macos]
logs:
    tail -n 50 -f "$HOME/Library/Logs/awf-listener-{{role}}.log"
[linux]
logs:
    sudo journalctl -u "agent-workflow-listener-{{role}}.service" -n 50 -f
[windows]
logs:
    @echo "Windows: check the rolling log next to WinSW.exe (agent-workflow-listener.out.log)"

# --- internal: fail early if repo is not set for install --------------------
_need-repo:
    @test -n "{{repo}}" || (echo "ERROR: set repo, e.g. just role={{role}} repo=/path/to/repo install-service" && exit 1)
