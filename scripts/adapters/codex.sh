#!/usr/bin/env bash
# Executor/reviewer adapter: Codex CLI.
#
# awf-listen.sh calls a tool adapter with a FIXED interface so the roles stay tool-agnostic.
# Codex is used here primarily as the REVIEWER tool (the reviewer role runs `codex review`),
# but it can also run as an executor via `codex exec`. Which mode is selected by AWF_MODE.
#
# Interface (environment variables passed by the role handler):
#   AWF_REPO_DIR    absolute path to the repository to work in            (required)
#   AWF_PROMPT_FILE absolute path to the role prompt (review or exec)     (required)
#   AWF_CARD_FILE   absolute path to the TaskCard markdown file           (optional)
#   AWF_MODEL       optional model id (may be empty)
#   AWF_MODE        "review" (default for reviewer) or "exec"             (default: review)
#   AWF_BASE        base branch to diff against in review mode            (default: master)
#
# Contract: exit 0 == success (the agent-bus listener ACKs only on exit 0).
# The prompt/card are passed as FILES / stdin, never inlined into the command string.
set -uo pipefail

: "${AWF_REPO_DIR:?codex adapter needs AWF_REPO_DIR}"
: "${AWF_PROMPT_FILE:?codex adapter needs AWF_PROMPT_FILE}"
AWF_CARD_FILE="${AWF_CARD_FILE:-}"
AWF_MODEL="${AWF_MODEL:-}"
AWF_MODE="${AWF_MODE:-review}"
AWF_BASE="${AWF_BASE:-master}"

model_args=()
# `codex review` takes model via -c model=...; `codex exec` takes -m. Normalize per mode below.

# The review/exec instructions are the role prompt; if a card is present, append it so the
# reviewer sees the acceptance criteria. Both travel via STDIN (never inlined as an arg).
build_stdin() {
  cat "$AWF_PROMPT_FILE"
  if [ -n "$AWF_CARD_FILE" ] && [ -f "$AWF_CARD_FILE" ]; then
    printf '\n\n--- TaskCard (acceptance criteria to verify against) ---\n\n'
    cat "$AWF_CARD_FILE"
  fi
}

case "$AWF_MODE" in
  review)
    # Review the whole PR branch vs its base. Read-only: a reviewer must not edit code.
    [ -n "$AWF_MODEL" ] && model_args=(-c "model=$AWF_MODEL")
    build_stdin | codex review \
      -C "$AWF_REPO_DIR" \
      --base "$AWF_BASE" \
      ${model_args[@]+"${model_args[@]}"} \
      -
    ;;
  exec)
    # Non-interactive execution. Workspace-write sandbox so it can edit within the repo.
    [ -n "$AWF_MODEL" ] && model_args=(-m "$AWF_MODEL")
    build_stdin | codex exec \
      -C "$AWF_REPO_DIR" \
      -s workspace-write \
      ${model_args[@]+"${model_args[@]}"} \
      -
    ;;
  *)
    echo "codex adapter: unknown AWF_MODE '$AWF_MODE' (want review|exec)" >&2
    exit 2
    ;;
esac
