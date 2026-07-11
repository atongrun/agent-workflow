#!/usr/bin/env bash
# Role handler: reviewer — the REVIEW loop of plan -> dispatch -> execute -> review -> decide.
#
# Invoked by awf-listen.sh's --on handler when a task:awf-review event arrives (emitted by
# roles/coder.sh after it executes). Pointer fields are passed as positional args:
#
#   reviewer.sh <branch> <card> <commit> <report> <tool> <model>
#
# It fetches the branch, then runs a review. The reviewer is deliberately pluggable:
#   - If a reviewer tool adapter is configured (AWF_TOOL + reviewer-prompt.md), it runs
#     that CLI to produce a ReviewReport.
#   - Otherwise it does the MINIMAL thing: leave the branch checked out and announce that a
#     human review is needed. Per the method, weak-model execution ALWAYS needs a strong
#     review backstop — a human (you) is a valid reviewer.
#
# Then it announces decision:awf-ready back to the architect role so the decider (you) can
# approve/reject. The reviewer never decides — decider is always the user.
#
# Environment (exported by awf-listen.sh):
#   AWF_SCRIPT_DIR, AWF_REPO_DIR
#   AWF_TOOL         optional reviewer tool adapter (empty => human review)
#   AWF_MODEL        optional model id for the reviewer tool
#   AWF_REVIEW_PROMPT_FILE   optional path to the reviewer prompt (default: scripts/reviewer-prompt.md)
#   AGENT_BUS_URL, AWF_REVIEWER_TOKEN, AWF_BUS_BIN
#
# Contract: exit 0 == success -> the listener ACKs the review event.
set -uo pipefail

BRANCH="${1:?reviewer handler needs <branch>}"
CARD="${2:?reviewer handler needs <card>}"
COMMIT="${3:-}"
REPORT="${4:-}"
# The REVIEWER's tool/model are a property of THIS listener (who reviews and how), NOT of
# the event (which carries the coder's tool). Prefer the listener's exported AWF_TOOL/
# AWF_MODEL; fall back to the event's positional values only if the listener set none.
TOOL="${AWF_TOOL:-${5:-}}"
MODEL="${AWF_MODEL:-${6:-}}"

: "${AWF_SCRIPT_DIR:?reviewer needs AWF_SCRIPT_DIR}"
: "${AWF_REPO_DIR:?reviewer needs AWF_REPO_DIR}"
AWF_REVIEW_PROMPT_FILE="${AWF_REVIEW_PROMPT_FILE:-$AWF_SCRIPT_DIR/reviewer-prompt.md}"
AWF_BASE="${AWF_BASE:-master}"

rdie() { echo "role/reviewer: $*" >&2; exit 1; }

echo "[role/reviewer] review branch=$BRANCH card=$CARD commit=$COMMIT report=${REPORT:-<none>}"

# ---- fetch the branch the coder pushed ----
git -C "$AWF_REPO_DIR" fetch --quiet origin "$BRANCH" 2>/dev/null \
  || echo "[role/reviewer] WARN: fetch failed (branch may be local-only); continuing"
git -C "$AWF_REPO_DIR" checkout -q "$BRANCH" 2>/dev/null \
  || git -C "$AWF_REPO_DIR" checkout -q -B "$BRANCH" "origin/$BRANCH" 2>/dev/null \
  || rdie "cannot checkout branch $BRANCH for review"

VERDICT="needs-human-review"

if [ -n "$TOOL" ] && [ -f "$AWF_SCRIPT_DIR/adapters/$TOOL.sh" ] && [ -f "$AWF_REVIEW_PROMPT_FILE" ]; then
  # ---- pluggable automated review: run the reviewer tool (card + prompt as FILES) ----
  echo "[role/reviewer] running reviewer tool: $TOOL model=${MODEL:-<default>}"
  CARD_FILE="$AWF_REPO_DIR/$CARD"
  [ -f "$CARD_FILE" ] || rdie "card not found for review: $CARD_FILE"
  AWF_REPO_DIR="$AWF_REPO_DIR" \
  AWF_CARD_FILE="$CARD_FILE" \
  AWF_PROMPT_FILE="$AWF_REVIEW_PROMPT_FILE" \
  AWF_MODEL="$MODEL" \
  AWF_MODE=review \
  AWF_BASE="$AWF_BASE" \
    bash "$AWF_SCRIPT_DIR/adapters/$TOOL.sh" \
    && VERDICT="tool-review-complete" \
    || echo "[role/reviewer] WARN: reviewer tool exited non-zero; falling back to human review"
else
  echo "[role/reviewer] no reviewer tool configured — flagging for human review."
  echo "[role/reviewer] branch $BRANCH is checked out in $AWF_REPO_DIR for you to review."
fi

# ---- announce decision-ready back to architect (decider is always the user) ----
if [ -n "${AGENT_BUS_URL:-}" ] && [ -n "${AWF_REVIEWER_TOKEN:-}" ]; then
  AWF_BUS="${AWF_BUS_BIN:-agent-bus}"
  task_id="${BRANCH##*/}"
  payload="$(printf '{"task_id":"%s","branch":"%s","commit":"%s","verdict":"%s","report":"%s"}' \
    "$task_id" "$BRANCH" "$COMMIT" "$VERDICT" "$REPORT")"
  AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$AWF_REVIEWER_TOKEN" AGENT_BUS_AGENT=reviewer \
    "$AWF_BUS" send --from reviewer --to architect --type decision:awf-ready --payload "$payload" \
    && echo "[role/reviewer] announced decision:awf-ready to architect (verdict=$VERDICT)" \
    || echo "[role/reviewer] WARN: failed to announce decision event"
else
  echo "[role/reviewer] no AGENT_BUS_URL/AWF_REVIEWER_TOKEN; skipping decision announcement"
fi

exit 0
