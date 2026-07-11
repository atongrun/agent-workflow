#!/usr/bin/env bash
# Executor adapter: OpenCode.
#
# awf-dispatch calls an adapter with a FIXED interface so the dispatcher stays
# tool-agnostic. To support another CLI (claude, codex, aider, ...), copy this file
# to adapters/<tool>.sh and translate the same inputs into that CLI's invocation.
#
# Interface (all passed as environment variables by awf-dispatch's handler):
#   AWF_REPO_DIR    absolute path to the repository the executor works in
#   AWF_CARD_FILE   absolute path to the TaskCard markdown file (self-contained)
#   AWF_PROMPT_FILE absolute path to the fixed implementer prompt (executor-prompt.md)
#   AWF_MODEL       optional model id (e.g. opencode-go/deepseek-v4-flash); may be empty
#
# Optional:
#   AWF_OPENCODE_BIN  path/name of the OpenCode binary. Defaults to `opencode` (on PATH).
#                     On Windows (git-bash) set it to the .cmd, e.g. /d/npm-global/opencode.cmd.
#
# Contract: exit 0 == success (the agent-bus listener ACKs only on exit 0).
# The prompt and card are passed as FILES, never inlined into the command string.
set -uo pipefail

: "${AWF_REPO_DIR:?adapter needs AWF_REPO_DIR}"
: "${AWF_CARD_FILE:?adapter needs AWF_CARD_FILE}"
: "${AWF_PROMPT_FILE:?adapter needs AWF_PROMPT_FILE}"
AWF_MODEL="${AWF_MODEL:-}"
OPENCODE_BIN="${AWF_OPENCODE_BIN:-opencode}"

# OpenCode: --dir sets the working directory (no `cd` needed), -f attaches the card file,
# and the message is the fixed prompt (read from file, so no shell-escaping of task text).
model_args=()
[ -n "$AWF_MODEL" ] && model_args=(-m "$AWF_MODEL")

exec "$OPENCODE_BIN" run \
  --dir "$AWF_REPO_DIR" \
  -f "$AWF_CARD_FILE" \
  ${model_args[@]+"${model_args[@]}"} \
  "$(cat "$AWF_PROMPT_FILE")"
