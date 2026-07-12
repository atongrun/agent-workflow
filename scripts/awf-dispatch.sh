#!/usr/bin/env bash
# awf-dispatch — lightweight, safe task dispatcher for Agent Workflow.
#
# Puts a self-contained TaskCard on a PR branch and announces it on Agent Bus as a
# POINTER event. It does NOT execute anything: a long-running role listener
# (scripts/awf_listen.py) running somewhere — possibly on another machine — picks up
# the event and runs the executor. This "dispatch = announce, listener = execute"
# split is what makes execution pluggable across roles and machines.
#
# Design goals (learned from real dogfood):
#   - The card travels as a FILE via git (committed to a PR branch), never inlined into
#     a shell string or an event payload (an em-dash once corrupted an SSE event and
#     crash-looped the listener; a 200-line card also does not fit a payload).
#   - The Agent Bus event carries only a POINTER: {branch, card, commit, tool, model}.
#     The listener's handler reads those via agent-bus template placeholders.
#   - Tokens are read from the environment (sourced from a gitignored file), never CLI args.
#
# Usage:
#   scripts/awf-dispatch.sh \
#     --repo   /path/to/target-repo \
#     --card   relative/path/to/taskcard.md   (relative to --repo) \
#     --branch awf/<task-id> \
#     [--to    coder]              (recipient role; default: coder) \
#     [--tool  opencode]           (executor CLI hint for the listener; default: opencode) \
#     [--model opencode-go/deepseek-v4-flash] \
#     [--report .awf/artifacts/NN-implementation-report.md]  (impl-report path hint) \
#     [--type  task:awf-impl]      (event type; default: task:awf-impl) \
#     [--no-push]                  (skip git push — LOCAL-ONLY; cross-machine needs push) \
#     [--dry-run]                  (print the event that WOULD be sent, send nothing)
#
# Required environment for the Agent Bus leg (source ~/.config/awf/dispatch.env):
#   AGENT_BUS_URL, AWF_ARCH_TOKEN         (tokens read from env, never CLI args)
#   Optional: AWF_BUS_BIN                 (path to the agent-bus binary; default: agent-bus)
set -uo pipefail

# ---- defaults ----
REPO="" CARD="" BRANCH="" TO="coder" TOOL="opencode" MODEL="" REPORT="" DO_PUSH=1 DRY_RUN=0
EVENT_TYPE="task:awf-impl"

die() { echo "awf-dispatch: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --card) CARD="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --to) TO="$2"; shift 2;;
    --tool) TOOL="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --report) REPORT="$2"; shift 2;;
    --type) EVENT_TYPE="$2"; shift 2;;
    --no-push) DO_PUSH=0; shift;;
    --dry-run) DRY_RUN=1; shift;;
    *) die "unknown arg: $1";;
  esac
done

[ -n "$REPO" ] || die "need --repo"
[ -n "$CARD" ] || die "need --card (relative to repo)"
[ -n "$BRANCH" ] || die "need --branch"
[ -d "$REPO" ] || die "repo not found: $REPO"
[ -f "$REPO/$CARD" ] || die "card not found: $REPO/$CARD"

# ---- 1. Put the card on a PR branch and push (the card travels via git, not the event) ----
echo "[dispatch] repo=$REPO card=$CARD branch=$BRANCH to=$TO tool=$TOOL model=${MODEL:-<default>}"
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
  # Cross-machine executors can ONLY get the card by pulling this branch from origin.
  git -C "$REPO" push -u origin "$BRANCH" >/dev/null 2>&1 \
    || echo "[dispatch] WARN: push failed. A remote executor will not see the card until this branch is pushed."
else
  echo "[dispatch] --no-push: LOCAL-ONLY. A remote (e.g. Windows) executor cannot pull this card."
fi
echo "[dispatch] card committed at $COMMIT on $BRANCH"

# ---- 2. Send the Agent Bus event (pointer only) ----
task_id="${BRANCH##*/}"
# report path hint: default to a conventional per-task artifact path if not given.
[ -n "$REPORT" ] || REPORT=".awf/artifacts/impl-report-$task_id.md"
payload="$(printf '{"task_id":"%s","branch":"%s","card":"%s","commit":"%s","tool":"%s","model":"%s","report":"%s"}' \
  "$task_id" "$BRANCH" "$CARD" "$COMMIT" "$TOOL" "$MODEL" "$REPORT")"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dispatch] --dry-run: would send event"
  echo "           type=$EVENT_TYPE  from=architect  to=$TO"
  echo "           payload=$payload"
  echo "[dispatch] (dry-run) nothing sent."
  exit 0
fi

: "${AGENT_BUS_URL:?set AGENT_BUS_URL (source ~/.config/awf/dispatch.env)}"
: "${AWF_ARCH_TOKEN:?set AWF_ARCH_TOKEN (source ~/.config/awf/dispatch.env)}"
AWF_BUS="${AWF_BUS_BIN:-agent-bus}"
AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$AWF_ARCH_TOKEN" AGENT_BUS_AGENT=architect \
  "$AWF_BUS" send --from architect --to "$TO" --type "$EVENT_TYPE" --payload "$payload" \
  || die "agent-bus send failed"
echo "[dispatch] event sent (type=$EVENT_TYPE to=$TO). A '$TO' listener will pick it up and execute."
