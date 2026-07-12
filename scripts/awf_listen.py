#!/usr/bin/env python3
"""awf_listen — start a cross-platform Agent Workflow role listener.

Whichever machine runs this becomes that role's worker: it connects to Agent Bus
and runs awf_role.py for each matching event. Replaces awf-listen.sh so the
executor side has no bash/cmd/WSL shell-dialect problems on Windows.

    python awf_listen.py --role coder    --repo /path/to/repo --tool opencode --model M
    python awf_listen.py --role reviewer --repo /path/to/repo --tool codex --base master

Config comes from the environment (source your dispatch.env first, or export):
    AGENT_BUS_URL, AWF_<ROLE>_TOKEN            (required)
    AWF_BUS_BIN                                (agent-bus binary; default: agent-bus)
    AWF_OPENCODE_BIN / AWF_CODEX_BIN           (tool binaries; optional)

control:shutdown is built into `agent-bus listen`; the VPS can stop this listener
with `agent-bus send --to <role> --type control:shutdown`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_ON_TYPE = {"coder": "task:awf-impl", "reviewer": "task:awf-review"}


def die(msg: str):
    print(f"awf_listen: {msg}", file=sys.stderr)
    raise SystemExit(2)


def build_handler(python_exe: str, role_script: str, role: str) -> str:
    """Build the agent-bus --on handler command.

    Path parts are wrapped in DOUBLE quotes: cmd.exe (Windows) and sh (POSIX)
    both honor double quotes, whereas cmd does not understand single quotes.
    The {payload.*} placeholders are substituted + shell-quoted by agent-bus.
    """
    fields = [
        "--branch", "{payload.branch}",
        "--card", "{payload.card}",
        "--commit", "{payload.commit}",
        "--model", "{payload.model}",
        "--tool", "{payload.tool}",
        "--report", "{payload.report}",
    ]
    return f'"{python_exe}" "{role_script}" {role} ' + " ".join(fields)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="awf_listen")
    p.add_argument("--role", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--tool", default="opencode")
    p.add_argument("--model", default="")
    p.add_argument("--on-type", dest="on_type", default="")
    p.add_argument("--base", default="master")
    p.add_argument("--exit-after-idle", dest="idle", type=int, default=None)
    p.add_argument("--no-push", dest="no_push", action="store_true")
    a = p.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    role_script = str(script_dir / "awf_role.py")
    if a.role not in DEFAULT_ON_TYPE and not a.on_type:
        die(f"role '{a.role}' has no default --on-type; pass --on-type")
    on_type = a.on_type or DEFAULT_ON_TYPE[a.role]

    if not Path(a.repo).is_dir():
        die(f"repo not found: {a.repo}")

    url = os.environ.get("AGENT_BUS_URL")
    if not url:
        die("set AGENT_BUS_URL (source your dispatch.env)")
    token_var = f"AWF_{a.role.upper()}_TOKEN"
    token = os.environ.get(token_var)
    if not token:
        die(f"set {token_var} (source your dispatch.env)")
    bus = os.environ.get("AWF_BUS_BIN", "agent-bus")

    # Force UTF-8 for the whole process tree (the agent-bus listener and every handler
    # it spawns inherit this). No-op on macOS/Linux; on Windows it stops child Python
    # from defaulting to the gbk locale codec and crashing on non-ASCII output.
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    # Config the handler needs is passed via the ENVIRONMENT (inherited by the
    # agent-bus listener and thus by each handler process it spawns).
    os.environ["AWF_SCRIPT_DIR"] = str(script_dir)
    os.environ["AWF_REPO_DIR"] = a.repo
    os.environ["AWF_TOOL"] = a.tool
    os.environ["AWF_MODEL"] = a.model
    os.environ["AWF_BASE"] = a.base
    os.environ["AWF_NO_PUSH"] = "1" if a.no_push else "0"
    os.environ["AGENT_BUS_TOKEN"] = token
    os.environ["AGENT_BUS_AGENT"] = a.role

    handler = build_handler(sys.executable, role_script, a.role)

    print(f"[listen] role={a.role} repo={a.repo} tool={a.tool} "
          f"model={a.model or '<default>'}")
    print(f"[listen] on '{on_type}' -> {role_script}")
    print(f"[listen] stop via: agent-bus send --to {a.role} --type control:shutdown")

    listen_argv = [bus, "listen", "--agent", a.role,
                   "--workdir", a.repo, "--handler-timeout", "3600"]
    if a.idle is not None:
        listen_argv += ["--exit-after-idle", str(a.idle)]
    listen_argv += ["--on", on_type, handler]

    if os.name == "nt" and bus.lower().endswith((".cmd", ".bat")):
        listen_argv = ["cmd", "/c", *listen_argv]

    return subprocess.run(listen_argv).returncode


if __name__ == "__main__":
    raise SystemExit(main())
