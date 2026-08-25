#!/usr/bin/env sh
# POSIX compatibility shim. Windows callers use awf_dispatch.py directly.
set -eu

if command -v python3 >/dev/null 2>&1; then
  AWF_PYTHON="${AWF_PYTHON_BIN:-python3}"
else
  AWF_PYTHON="${AWF_PYTHON_BIN:-python}"
fi
exec "$AWF_PYTHON" -m agent_workflow.operations.awf_dispatch "$@"
