#!/usr/bin/env sh
# POSIX compatibility shim. Windows callers use awf_dispatch.py directly.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
  AWF_PYTHON="${AWF_PYTHON_BIN:-python3}"
else
  AWF_PYTHON="${AWF_PYTHON_BIN:-python}"
fi
exec "$AWF_PYTHON" "$SCRIPT_DIR/awf_dispatch.py" "$@"
