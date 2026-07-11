#!/usr/bin/env bash
# Executor: local — run the executor tool on THIS machine.
#
# An executor answers "on which machine, and how, do we prepare the repo and run the
# tool". It is orthogonal to the tool adapter (scripts/adapters/<tool>.sh), which only
# knows how to invoke one CLI. The role handler (scripts/roles/<role>.sh) calls an
# executor; the executor calls the tool adapter.
#
# In the pure-B design the listener runs ON the executing machine, so "local" == that
# machine (e.g. run awf-listen.sh on Windows and its executor is Windows-local). There is
# deliberately no ssh executor: cross-machine is achieved by WHERE the listener runs, not
# by ssh-ing out of a handler (which would risk inlining the card into a remote command).
#
# Responsibilities:
#   1. fetch + checkout the PR branch (the card travels via git)
#   2. run the tool adapter (which does the actual code edit + writes the impl report)
#   3. commit any changes and push them back to the same branch (so the reviewer can pull)
#
# Interface (environment variables set by the role handler):
#   AWF_SCRIPT_DIR   absolute path to scripts/ (to locate adapters/)
#   AWF_REPO_DIR     absolute path to the repo the executor works in
#   AWF_BRANCH       PR branch to fetch/checkout
#   AWF_CARD         card path relative to the repo (used to build AWF_CARD_FILE)
#   AWF_TOOL         tool adapter name (e.g. opencode)
#   AWF_MODEL        optional model id (may be empty)
#   AWF_PROMPT_FILE  absolute path to the fixed executor prompt
#   AWF_NO_PUSH      optional; "1" to skip the final push (local-only validation)
#
# Contract: exit 0 == success. The caller ACKs the Agent Bus event only on exit 0.
set -uo pipefail

: "${AWF_SCRIPT_DIR:?executor needs AWF_SCRIPT_DIR}"
: "${AWF_REPO_DIR:?executor needs AWF_REPO_DIR}"
: "${AWF_BRANCH:?executor needs AWF_BRANCH}"
: "${AWF_CARD:?executor needs AWF_CARD}"
: "${AWF_PROMPT_FILE:?executor needs AWF_PROMPT_FILE}"
AWF_TOOL="${AWF_TOOL:-opencode}"
AWF_MODEL="${AWF_MODEL:-}"
AWF_NO_PUSH="${AWF_NO_PUSH:-0}"

xdie() { echo "executor/local: $*" >&2; exit 1; }

ADAPTER="$AWF_SCRIPT_DIR/adapters/$AWF_TOOL.sh"
[ -f "$ADAPTER" ] || xdie "no adapter for tool '$AWF_TOOL' (expected $ADAPTER)"
[ -d "$AWF_REPO_DIR" ] || xdie "repo not found: $AWF_REPO_DIR"
git -C "$AWF_REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || xdie "not a git work tree: $AWF_REPO_DIR"

# ---- 1. get the card via git (fetch + checkout the branch the dispatcher pushed) ----
echo "[executor/local] fetch + checkout $AWF_BRANCH in $AWF_REPO_DIR"
git -C "$AWF_REPO_DIR" fetch --quiet origin "$AWF_BRANCH" 2>/dev/null \
  || echo "[executor/local] WARN: fetch failed (branch may be local-only); continuing"
git -C "$AWF_REPO_DIR" checkout -q "$AWF_BRANCH" 2>/dev/null \
  || git -C "$AWF_REPO_DIR" checkout -q -B "$AWF_BRANCH" "origin/$AWF_BRANCH" 2>/dev/null \
  || xdie "cannot checkout branch $AWF_BRANCH"

CARD_FILE="$AWF_REPO_DIR/$AWF_CARD"
[ -f "$CARD_FILE" ] || xdie "card not found after checkout: $CARD_FILE"

# ---- 2. run the tool adapter (card + prompt passed as FILES, never inlined) ----
echo "[executor/local] running tool adapter: $AWF_TOOL model=${AWF_MODEL:-<default>}"
AWF_REPO_DIR="$AWF_REPO_DIR" \
AWF_CARD_FILE="$CARD_FILE" \
AWF_PROMPT_FILE="$AWF_PROMPT_FILE" \
AWF_MODEL="$AWF_MODEL" \
  bash "$ADAPTER"
rc=$?
[ "$rc" -eq 0 ] || xdie "tool adapter exited $rc"

# ---- 3. commit + push the executor's changes back to the same branch ----
git -C "$AWF_REPO_DIR" add -A || xdie "git add failed"
if git -C "$AWF_REPO_DIR" diff --cached --quiet; then
  echo "[executor/local] no changes produced by the tool (nothing to commit)"
else
  git -C "$AWF_REPO_DIR" commit -q -m "feat(awf): executor output for $AWF_BRANCH [$AWF_TOOL]" \
    || xdie "commit failed"
  echo "[executor/local] committed executor output on $AWF_BRANCH"
fi

if [ "$AWF_NO_PUSH" = "1" ]; then
  echo "[executor/local] AWF_NO_PUSH=1: skipping push (local-only validation)"
else
  git -C "$AWF_REPO_DIR" push -u origin "$AWF_BRANCH" >/dev/null 2>&1 \
    || xdie "push failed (reviewer will not see the changes)"
  echo "[executor/local] pushed $AWF_BRANCH to origin"
fi

exit 0
