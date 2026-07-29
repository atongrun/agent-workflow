#!/usr/bin/env bash
# awf-listen-service.sh — service wrapper that starts an Agent Workflow listener.
#
# Thin POSIX launcher. The Python service entry point validates and loads the
# credential file as data; this wrapper never sources or interprets it.
#
# The service definition provides these via the environment (all non-secret):
#   AWF_ROLE    (required)  coder | reviewer
#   AWF_REPO    (required)  absolute path to the target repo checkout
#   AWF_TOOL    (optional)  opencode | codex | ...   (default: opencode)
#   AWF_MODEL   (optional)  model id passed to the tool
#   AWF_BASE    (optional)  base branch for reviewer diffs (default: master)
#   AWF_NO_PUSH (optional)  set to 1 to skip pushing (dry runs)
#   AWF_DISPATCH_ENV (optional)  path to dispatch.env (default: ~/.config/awf/dispatch.env)
#   AWF_PYTHON  (optional)  python interpreter (default: python3)
#
# Secrets come only from the strict config loader, never from the service definition:
#   ~/.config/awf/dispatch.env      AGENT_BUS_URL, AWF_<ROLE>_TOKEN, AWF_BUS_BIN
#   ~/.config/awf/bootstrap.secret  AGENT_BUS_BOOTSTRAP_SECRET (optional)
set -eu

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$SELF_DIR/.." && pwd)"   # scripts/ (parent of scripts/service/)

PYTHON="${AWF_PYTHON:-python3}"
SERVICE="$SCRIPTS_DIR/awf_service.py"

echo "awf-listen-service: exec native Python service entry point"
exec "$PYTHON" "$SERVICE"
