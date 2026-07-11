#!/usr/bin/env bash
# awf-dispatch — lightweight, safe task dispatcher for Agent Workflow.
#
# Hands a self-contained TaskCard to an executor (a coding CLI) over Agent Bus.
# Design goals (learned from real dogfood):
#   - The card/prompt travel as FILES, never inlined into a shell string (an em-dash once
#     corrupted an SSE event and crash-looped the listener). Fill only what changes.
#   - The executor CLI is pluggable via scripts/adapters/<tool>.sh (tool-agnostic core).
#   - The card is shared via git (committed to a PR branch), so any executor can pull it;
#     the Agent Bus event carries only a pointer (branch + card path), not the card body.
#
# This version: executor = local; tool adapters pluggable (opencode shipped).
# Windows/SSH executor is a planned follow-up.
#
# Usage:
#   scripts/awf-dispatch.sh \
#     --repo   /path/to/target-repo \
#     --card   relative/path/to/taskcard.md   (relative to --repo) \
#     --branch awf/<task-id> \
#     [--tool  opencode]           (default: opencode) \
#     [--model opencode-go/deepseek-v4-flash] \
#     [--executor local]           (default: local; windows: TODO) \
#     [--no-push]                  (skip git push; local-only validation)
#
# Required environment (for the Agent Bus leg):
#   AGENT_BUS_URL, AWF_ARCH_TOKEN, AWF_CODER_TOKEN   (tokens read from env, never CLI args)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROMPT_FILE="$SCRIPT_DIR/executor-prompt.md"

# ---- defaults ----
REPO="" CARD="" BRANCH="" TOOL="opencode" MODEL="" EXECUTOR="local" DO_PUSH=1
EVENT_TYPE="task:awf-impl"

die() { echo "awf-dispatch: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --card) CARD="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --tool) TOOL="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --executor) EXECUTOR="$2"; shift 2;;
    --no-push) DO_PUSH=0; shift;;
    *) die "unknown arg: $1";;
  esac
done

[ -n "$REPO" ] || die "need --repo"
[ -n "$CARD" ] || die "need --card (relative to repo)"
[ -n "$BRANCH" ] || die "need --branch"
[ -d "$REPO" ] || die "repo not found: $REPO"
[ -f "$REPO/$CARD" ] || die "card not found: $REPO/$CARD"
ADAPTER="$SCRIPT_DIR/adapters/$TOOL.sh"
[ -f "$ADAPTER" ] || die "no adapter for tool '$TOOL' (expected $ADAPTER)"
[ "$EXECUTOR" = "local" ] || die "executor '$EXECUTOR' not supported yet (only local)"

# ---- 1. Put the card on a PR branch and push (card travels via git, not the event) ----
echo "[dispatch] repo=$REPO card=$CARD branch=$BRANCH tool=$TOOL model=${MODEL:-<default>}"
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "repo is not a git work tree"

cur_branch="$(git -C "$REPO" branch --show-current)"
if [ "$cur_branch" != "$BRANCH" ]; then
  git -C "$REPO" checkout -B "$BRANCH" >/dev/null 2>&1 || die "cannot checkout branch $BRANCH"
fi
git -C "$REPO" add -- "$CARD" || die "git add failed"
if ! git -C "$REPO" diff --cached --quiet; then
  git -C "$REPO" commit -q -m "chore(awf): dispatch TaskCard $CARD" || die "commit failed"
fi
COMMIT="$(git -C "$REPO" rev-parse HEAD)"
if [ "$DO_PUSH" -eq 1 ]; then
  git -C "$REPO" push -u origin "$BRANCH" >/dev/null 2>&1 || echo "[dispatch] WARN: push failed (continuing; executor is local and reads the card directly)"
fi
echo "[dispatch] card committed at $COMMIT on $BRANCH"

# ---- 2. Send the Agent Bus event (pointer only) ----
: "${AGENT_BUS_URL:?set AGENT_BUS_URL}"
: "${AWF_ARCH_TOKEN:?set AWF_ARCH_TOKEN}"
: "${AWF_CODER_TOKEN:?set AWF_CODER_TOKEN}"
AWF_BUS="${AWF_BUS_BIN:-agent-bus}"
task_id="${BRANCH##*/}"
payload="$(printf '{"task_id":"%s","branch":"%s","card":"%s","commit":"%s","tool":"%s"}' \
  "$task_id" "$BRANCH" "$CARD" "$COMMIT" "$TOOL")"
AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$AWF_ARCH_TOKEN" AGENT_BUS_AGENT=architect \
  "$AWF_BUS" send --from architect --to coder --type "$EVENT_TYPE" --payload "$payload" \
  || die "agent-bus send failed"
echo "[dispatch] event sent (type=$EVENT_TYPE)"

# ---- 3. Start the local coder listener; its handler runs the tool adapter ----
# The handler exports the adapter interface as env vars and execs the adapter. The card and
# prompt are passed as file paths (never inlined). Exit 0 from the adapter => listener ACKs.
DONE_MARKER="$REPO/.awf/artifacts/.awf-done-$task_id"
REPORT_HINT="$REPO/.awf/artifacts/impl-report-$task_id.md"
rm -f "$DONE_MARKER"

# The adapter runs OpenCode etc. We wrap it so the executor also writes the done-marker.
HANDLER="AWF_REPO_DIR='$REPO' AWF_CARD_FILE='$REPO/$CARD' AWF_PROMPT_FILE='$PROMPT_FILE' AWF_MODEL='$MODEL' AWF_REPORT_FILE='$REPORT_HINT' bash '$ADAPTER'; rc=\$?; touch '$DONE_MARKER'; exit \$rc"

echo "[dispatch] starting local listener; executor=$TOOL. Waiting for completion marker:"
echo "           $DONE_MARKER"
AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$AWF_CODER_TOKEN" AGENT_BUS_AGENT=coder \
  "$AWF_BUS" listen --agent coder --once --handler-timeout 3600 \
  --on "$EVENT_TYPE" "$HANDLER"

echo "[dispatch] listener returned. Check $REPORT_HINT and git diff in $REPO."
