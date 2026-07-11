#!/usr/bin/env bash
# Role handler: coder — the EXECUTE loop of plan -> dispatch -> execute -> review -> decide.
#
# Invoked by awf-listen.sh's --on handler when a task:awf-impl event arrives. The event's
# pointer fields are passed as positional args (agent-bus substitutes {payload.x} and
# shell-quotes each value, so nothing is inlined unsafely):
#
#   coder.sh <branch> <card> <commit> <model> <tool> <report>
#
# It runs the executor (which pulls the branch, runs the tool, commits + pushes), then
# announces the result to the reviewer role as a task:awf-review pointer event.
#
# Environment (exported by awf-listen.sh):
#   AWF_SCRIPT_DIR   scripts/ dir
#   AWF_REPO_DIR     repo this coder operates on
#   AWF_EXECUTOR     executor name (default: local)
#   AWF_PROMPT_FILE  fixed executor prompt path
#   AGENT_BUS_URL, AWF_CODER_TOKEN   (for sending the follow-on review event)
#   AWF_BUS_BIN      optional agent-bus binary path (default: agent-bus)
#   AWF_NO_PUSH      optional "1" for local-only validation (skips push + follow-on event send is still attempted)
#
# Contract: exit 0 == success -> the listener ACKs the impl event.
set -uo pipefail

BRANCH="${1:?coder handler needs <branch>}"
CARD="${2:?coder handler needs <card>}"
COMMIT="${3:-}"
REPORT="${6:-}"
# The CODER's tool/model belong to THIS listener (what this worker runs), not the event.
# Prefer the listener's exported AWF_TOOL/AWF_MODEL; fall back to the event's values.
MODEL="${AWF_MODEL:-${4:-}}"
TOOL="${AWF_TOOL:-${5:-opencode}}"

: "${AWF_SCRIPT_DIR:?coder needs AWF_SCRIPT_DIR}"
: "${AWF_REPO_DIR:?coder needs AWF_REPO_DIR}"
: "${AWF_PROMPT_FILE:?coder needs AWF_PROMPT_FILE}"
AWF_EXECUTOR="${AWF_EXECUTOR:-local}"

hdie() { echo "role/coder: $*" >&2; exit 1; }

EXECUTOR="$AWF_SCRIPT_DIR/executors/$AWF_EXECUTOR.sh"
[ -f "$EXECUTOR" ] || hdie "no executor '$AWF_EXECUTOR' (expected $EXECUTOR)"

echo "[role/coder] task on branch=$BRANCH card=$CARD tool=$TOOL model=${MODEL:-<default>}"

# ---- run the executor (fetch/checkout -> tool -> commit -> push) ----
AWF_SCRIPT_DIR="$AWF_SCRIPT_DIR" \
AWF_REPO_DIR="$AWF_REPO_DIR" \
AWF_BRANCH="$BRANCH" \
AWF_CARD="$CARD" \
AWF_TOOL="$TOOL" \
AWF_MODEL="$MODEL" \
AWF_PROMPT_FILE="$AWF_PROMPT_FILE" \
AWF_NO_PUSH="${AWF_NO_PUSH:-0}" \
  bash "$EXECUTOR"
rc=$?
[ "$rc" -eq 0 ] || hdie "executor failed (rc=$rc); not announcing review"

NEW_COMMIT="$(git -C "$AWF_REPO_DIR" rev-parse HEAD 2>/dev/null || echo "$COMMIT")"

# ---- announce to the reviewer role (pointer event; the card/report travel via git) ----
if [ -n "${AGENT_BUS_URL:-}" ] && [ -n "${AWF_CODER_TOKEN:-}" ]; then
  AWF_BUS="${AWF_BUS_BIN:-agent-bus}"
  task_id="${BRANCH##*/}"
  payload="$(printf '{"task_id":"%s","branch":"%s","card":"%s","commit":"%s","report":"%s","tool":"%s","model":"%s"}' \
    "$task_id" "$BRANCH" "$CARD" "$NEW_COMMIT" "$REPORT" "$TOOL" "$MODEL")"
  AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$AWF_CODER_TOKEN" AGENT_BUS_AGENT=coder \
    "$AWF_BUS" send --from coder --to reviewer --type task:awf-review --payload "$payload" \
    && echo "[role/coder] announced task:awf-review to reviewer (commit=$NEW_COMMIT)" \
    || echo "[role/coder] WARN: failed to announce review event (execution still succeeded)"
else
  echo "[role/coder] no AGENT_BUS_URL/AWF_CODER_TOKEN; skipping review announcement"
fi

exit 0
