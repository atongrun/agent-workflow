#!/usr/bin/env bash
# awf-listen — run a long-lived Agent Workflow ROLE listener on this machine.
#
# A role (coder, reviewer, ...) is just an agent-bus agent name. Whichever machine runs
# this script becomes that role's worker: it stays connected, and each matching event fires
# the role handler (scripts/roles/<role>.sh), which pulls the branch, runs the tool, and
# announces the next stage. Run it on Windows -> Windows is the executor. Run it on the VPS
# -> the VPS is. Role != machine; the mapping is "where you start this listener".
#
# The card/prompt always travel as FILES via git; the Agent Bus event carries only a
# pointer, which agent-bus substitutes into the handler command as shell-quoted args
# ({payload.branch} etc.) — nothing is inlined unsafely.
#
# control:shutdown is built into `agent-bus listen`: the VPS (Hermes) can stop this
# listener with `agent-bus send --to <role> --type control:shutdown` (optionally
# --payload '{"target":"<role>"}' to hit only this role). No handler needed here.
#
# Usage:
#   scripts/awf-listen.sh \
#     --role   coder | reviewer            (agent-bus agent name; REQUIRED) \
#     --repo   /path/to/repo               (repo this role operates on; REQUIRED) \
#     [--tool  opencode]                   (executor/reviewer CLI adapter; default opencode) \
#     [--model opencode-go/deepseek-v4-flash] \
#     [--executor local]                   (default local; where/how to run — see executors/) \
#     [--on-type <event-type>]             (default: coder=task:awf-impl, reviewer=task:awf-review) \
#     [--base master]                      (reviewer: base branch to diff the PR branch against) \
#     [--exit-after-idle N]                (exit after N idle seconds; default: run forever) \
#     [--no-push]                          (executor skips push — LOCAL-ONLY validation)
#
# Environment (source ~/.config/awf/dispatch.env, gitignored, chmod 600):
#   AGENT_BUS_URL                          (required)
#   AWF_<ROLE>_TOKEN                       (e.g. AWF_CODER_TOKEN / AWF_REVIEWER_TOKEN; required)
#   AWF_BUS_BIN                            (optional agent-bus binary path; default agent-bus)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- defaults ----
ROLE="" REPO="" TOOL="opencode" MODEL="" EXECUTOR="local" ON_TYPE="" IDLE="" NO_PUSH=0 BASE="master"

die() { echo "awf-listen: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE="$2"; shift 2;;
    --repo) REPO="$2"; shift 2;;
    --tool) TOOL="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --executor) EXECUTOR="$2"; shift 2;;
    --on-type) ON_TYPE="$2"; shift 2;;
    --exit-after-idle) IDLE="$2"; shift 2;;
    --base) BASE="$2"; shift 2;;
    --no-push) NO_PUSH=1; shift;;
    *) die "unknown arg: $1";;
  esac
done

[ -n "$ROLE" ] || die "need --role (e.g. coder, reviewer)"
[ -n "$REPO" ] || die "need --repo"
[ -d "$REPO" ] || die "repo not found: $REPO"
ROLE_HANDLER="$SCRIPT_DIR/roles/$ROLE.sh"
[ -f "$ROLE_HANDLER" ] || die "no handler for role '$ROLE' (expected $ROLE_HANDLER)"
[ -f "$SCRIPT_DIR/executors/$EXECUTOR.sh" ] || die "no executor '$EXECUTOR' (expected $SCRIPT_DIR/executors/$EXECUTOR.sh)"

# Default event type per role (coder consumes impl, reviewer consumes review).
if [ -z "$ON_TYPE" ]; then
  case "$ROLE" in
    coder) ON_TYPE="task:awf-impl";;
    reviewer) ON_TYPE="task:awf-review";;
    *) die "role '$ROLE' has no default --on-type; pass --on-type explicitly";;
  esac
fi

# ---- resolve this role's token from the env (never on the CLI) ----
: "${AGENT_BUS_URL:?set AGENT_BUS_URL (source ~/.config/awf/dispatch.env)}"
ROLE_UC="$(printf '%s' "$ROLE" | tr '[:lower:]' '[:upper:]')"
TOKEN_VAR="AWF_${ROLE_UC}_TOKEN"
ROLE_TOKEN="${!TOKEN_VAR:-}"
[ -n "$ROLE_TOKEN" ] || die "set $TOKEN_VAR (source ~/.config/awf/dispatch.env)"
AWF_BUS="${AWF_BUS_BIN:-agent-bus}"

# ---- config the handler needs is passed via EXPORTED ENV, not the command string ----
# (the command string only carries the per-event pointer, which agent-bus shell-quotes)
export AWF_SCRIPT_DIR="$SCRIPT_DIR"
export AWF_REPO_DIR="$REPO"
export AWF_EXECUTOR="$EXECUTOR"
export AWF_PROMPT_FILE="$SCRIPT_DIR/executor-prompt.md"
export AWF_REVIEW_PROMPT_FILE="$SCRIPT_DIR/reviewer-prompt.md"
export AWF_NO_PUSH="$NO_PUSH"
export AWF_BASE="$BASE"
export AGENT_BUS_URL
export AWF_BUS_BIN="$AWF_BUS"
# The role handler also sends follow-on events; give it its own token under the name it expects.
export "AWF_${ROLE_UC}_TOKEN=$ROLE_TOKEN"

# The handler command: role script + pointer fields substituted by agent-bus.
# Order MUST match the role handler's positional args.
#   coder.sh    <branch> <card> <commit> <model> <tool> <report>
#   reviewer.sh <branch> <card> <commit> <report> <tool> <model>
case "$ROLE" in
  coder)
    HANDLER="bash '$ROLE_HANDLER' {payload.branch} {payload.card} {payload.commit} {payload.model} {payload.tool} {payload.report}"
    ;;
  reviewer)
    HANDLER="bash '$ROLE_HANDLER' {payload.branch} {payload.card} {payload.commit} {payload.report} {payload.tool} {payload.model}"
    ;;
  *)
    # generic fallback: pass the common fields
    HANDLER="bash '$ROLE_HANDLER' {payload.branch} {payload.card} {payload.commit}"
    ;;
esac

# Per-listener tool/model overrides for this role's handler (env, not CLI).
export AWF_TOOL="$TOOL"
export AWF_MODEL="$MODEL"

echo "[listen] role=$ROLE repo=$REPO tool=$TOOL model=${MODEL:-<default>} executor=$EXECUTOR"
echo "[listen] on '$ON_TYPE' -> $ROLE_HANDLER"
echo "[listen] persistent listener. Stop via: agent-bus send --to $ROLE --type control:shutdown"

idle_args=()
[ -n "$IDLE" ] && idle_args=(--exit-after-idle "$IDLE")

AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$ROLE_TOKEN" AGENT_BUS_AGENT="$ROLE" \
  "$AWF_BUS" listen --agent "$ROLE" \
    --workdir "$REPO" \
    --handler-timeout 3600 \
    ${idle_args[@]+"${idle_args[@]}"} \
    --on "$ON_TYPE" "$HANDLER"
