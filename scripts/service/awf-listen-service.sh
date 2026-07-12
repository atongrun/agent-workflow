#!/usr/bin/env bash
# awf-listen-service.sh — service wrapper that starts an Agent Workflow listener.
#
# WHY a wrapper: launchd (.plist) and WinSW (.xml) service definitions cannot
# `source` an env file, and they are world-readable — so baking tokens into them
# would leak credentials. This wrapper keeps the secrets in the 0600 dispatch.env
# (and optional bootstrap.secret): it sources them, then execs the listener. The
# service definition itself holds only NON-secret settings (role/repo/tool/model).
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
# Secrets come ONLY from the sourced files, never from the service definition:
#   ~/.config/awf/dispatch.env      AGENT_BUS_URL, AWF_<ROLE>_TOKEN, AWF_BUS_BIN
#   ~/.config/awf/bootstrap.secret  AGENT_BUS_BOOTSTRAP_SECRET (optional)
set -eu

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$SELF_DIR/.." && pwd)"   # scripts/ (parent of scripts/service/)

: "${AWF_ROLE:?AWF_ROLE is required (coder|reviewer)}"
: "${AWF_REPO:?AWF_REPO is required (absolute path to the repo checkout)}"

DISPATCH_ENV="${AWF_DISPATCH_ENV:-$HOME/.config/awf/dispatch.env}"
if [ ! -f "$DISPATCH_ENV" ]; then
  echo "awf-listen-service: dispatch.env not found: $DISPATCH_ENV" >&2
  echo "  run awf_bootstrap.py first to create it." >&2
  exit 3
fi

# Source credentials. `set -a` exports every var the files define so the listener
# (and the handlers it spawns) inherit them.
set -a
# shellcheck disable=SC1090
. "$DISPATCH_ENV"
# bootstrap.secret is optional (only executor bootstrap needs it, not the listener).
if [ -f "$HOME/.config/awf/bootstrap.secret" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.config/awf/bootstrap.secret"
fi
set +a

PYTHON="${AWF_PYTHON:-python3}"
LISTEN="$SCRIPTS_DIR/awf_listen.py"

# Build argv (non-secret settings only; secrets are already in the environment).
set -- --role "$AWF_ROLE" --repo "$AWF_REPO"
[ -n "${AWF_TOOL:-}" ]  && set -- "$@" --tool "$AWF_TOOL"
[ -n "${AWF_MODEL:-}" ] && set -- "$@" --model "$AWF_MODEL"
[ -n "${AWF_BASE:-}" ]  && set -- "$@" --base "$AWF_BASE"
[ "${AWF_NO_PUSH:-0}" = "1" ] && set -- "$@" --no-push

echo "awf-listen-service: exec $PYTHON $LISTEN role=$AWF_ROLE repo=$AWF_REPO"
exec "$PYTHON" "$LISTEN" "$@"
