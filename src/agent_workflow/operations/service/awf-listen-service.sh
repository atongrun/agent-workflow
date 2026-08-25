#!/usr/bin/env bash
# awf-listen-service.sh — service wrapper that starts an Agent Workflow listener.
#
# Thin POSIX launcher. The Python service entry point validates and loads the
# credential file as data; this wrapper never sources or interprets it.
#
# The service definition provides only the absolute, secret-free profile path:
#   AWF_PROFILE (required)
#   AWF_PYTHON  (optional)  python interpreter (default: python3)
set -eu

PYTHON="${AWF_PYTHON:-python3}"

echo "awf-listen-service: exec native Python service entry point"
exec "$PYTHON" -m agent_workflow.operations.awf_service
