#!/usr/bin/env python3
"""awf_bootstrap — one-shot credential/config bootstrap for Agent Workflow.

Fetches this machine's Agent Bus role tokens from the *source of truth* and
assembles `~/.config/awf/dispatch.env` (owner-only, never committed). It removes
the "every time I switch machine / hand off, I ssh in and hand-write
dispatch.env" pain without ever recording a token in git or memory.

Two transports (`--via`):
  - curl (default): each role's token comes from the Agent Bus
    `POST /bootstrap/token` endpoint. The machine presents a low-privilege
    bootstrap secret (AGENT_BUS_BOOTSTRAP_SECRET) and gets its role token back.
    A plain HTTP request over Tailscale — no VPS SSH access needed. This is the
    standard secret-bootstrapping pattern (Vault / cloud metadata).
  - ssh (fallback): reads the whole AGENT_BUS_AGENT_TOKENS line from the VPS
    `/etc/agent-bus/.env`. Kept for machines/situations where the endpoint is
    not configured yet, but binds this machine to VPS SSH access.

    export AGENT_BUS_BOOTSTRAP_SECRET=...          # required for --via curl
    python awf_bootstrap.py                         # all roles, via curl
    python awf_bootstrap.py --roles coder           # executor machine: just coder
    python awf_bootstrap.py --via ssh               # fallback: pull over ssh
    python awf_bootstrap.py --print                 # show the file WITHOUT secrets
    python awf_bootstrap.py --dry-run               # plan only: no fetch, no write
    python awf_bootstrap.py --force                 # overwrite an existing file (backs up)

Hard rules (do not weaken):
  - Token VALUES are never printed to the terminal, the chat, or any log, and
    never written to git. They flow: bus stdout -> this process -> dispatch.env
    (owner-only). They never pass through argv.
  - The bootstrap secret is likewise never in argv: curl reads it from a 0600
    config file (`curl -K`), and it is read from the environment, not a flag.
  - The core Agent Workflow package holds no credentials/transport; this is an
    ops helper under scripts/, not an `awf` CLI subcommand.

Why Python (not bash): bootstrap is the *first* thing run on a fresh machine —
exactly where Windows' cmd/WSL/git-bash shell dialects bite hardest. Python runs
identically on macOS and Windows, matching awf_role.py / awf_listen.py.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from awf_config import (
    ConfigError,
    _parse_icacls_aces,
    native_executable,
    serialize_config,
    validate_config_path,
)

try:
    from awf_executor import ExecutionFailure
    from awf_executor import run as run_command
except ModuleNotFoundError:  # package import in tests
    from .awf_executor import ExecutionFailure
    from .awf_executor import run as run_command

# Map the VPS role name -> the env var awf_dispatch/awf_listen/awf_role expect.
# NOTE the architect -> ARCH abbreviation, matching the existing dispatch.env.
ROLE_TO_TOKEN_VAR = {
    "architect": "AWF_ARCH_TOKEN",
    "coder": "AWF_CODER_TOKEN",
    "reviewer": "AWF_REVIEWER_TOKEN",
}

DEFAULT_SOURCE_HOST = ""
DEFAULT_SOURCE_PATH = "/etc/agent-bus/.env"

PLATFORM_DEFAULTS = {
    "darwin": {
        "agent_bus_repo": "",
        "bus_bin_rel": ".venv/bin/agent-bus",
        "opencode_bin": "",
    },
    "win": {
        "agent_bus_repo": "",
        "bus_bin_rel": ".venv/Scripts/agent-bus.exe",
        "opencode_bin": "",
    },
}


def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


def die(msg: str, code: int = 2):
    print(f"awf_bootstrap: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def platform_key() -> str:
    return "win" if os.name == "nt" else "darwin"


# ---------------------------------------------------------------------------
# token retrieval (values never printed / never through argv)
# ---------------------------------------------------------------------------


def fetch_tokens_line(host: str, path: str) -> str:
    """Fetch the raw `AGENT_BUS_AGENT_TOKENS=...` value from the VPS over ssh.

    Only the token line's value is returned (via stdout, captured here); it is
    never echoed. We grep on the VPS side and strip the `KEY=` prefix so only
    the `role=tok,role=tok` payload crosses the wire.
    """
    # sed extracts the value after the first '='; single VPS-side command.
    remote = f"grep -m1 '^AGENT_BUS_AGENT_TOKENS=' {path} | sed 's/^AGENT_BUS_AGENT_TOKENS=//'"
    try:
        proc = run_command(
            ["ssh", host, remote],
            text=True,
            capture_output=True,
            timeout=30,
        )
    except ExecutionFailure as exc:
        if exc.diagnostic.kind == "timeout":
            die("ssh token source timed out")
        if exc.diagnostic.kind == "not-found":
            die("ssh not found on PATH")
        die("could not read the SSH token source")
    if proc.returncode != 0:
        die(f"could not read the SSH token source (ssh exit {proc.returncode})")
    value = proc.stdout.strip()
    if not value or "=" not in value:
        die("no AGENT_BUS_AGENT_TOKENS found in the SSH token source")
    return value


def fetch_tokens_curl(url: str, secret: str, roles: list) -> dict:
    """Fetch each role's token from the Agent Bus `POST /bootstrap/token` endpoint.

    One request per role: body {"agent": <role>} + header X-Bootstrap-Secret,
    returns {"agent": <role>, "token": <role-token>}. Unlike the ssh path (which
    reads the whole AGENT_BUS_AGENT_TOKENS line at once), the endpoint hands back
    one token at a time, so we loop the requested roles.

    Security: the bootstrap secret is passed to curl via a 0600 CONFIG FILE
    (`curl -K`), never on the command line (argv is world-readable via `ps`). The
    returned token arrives on stdout and flows only into dispatch.env; it is never
    echoed. curl runs as a real argv (shell=False) — no shell re-parse.
    """
    endpoint = url.rstrip("/") + "/bootstrap/token"
    out: dict = {}
    for role in roles:
        # Body is a tiny fixed JSON object; the role name is a known-safe literal
        # from ROLE_TO_TOKEN_VAR, so this is not attacker-influenced.
        body = '{"agent": "%s"}' % role
        fd, cfg_path = tempfile.mkstemp(suffix=".curlcfg")
        try:
            # The file will contain the bootstrap secret. os.chmod is not an
            # owner-only ACL operation on Windows, so use the shared platform
            # lockdown before writing any sensitive bytes.
            curl_config = (
                f'url = "{endpoint}"\n'
                'request = "POST"\n'
                'header = "Content-Type: application/json"\n'
                f'header = "X-Bootstrap-Secret: {secret}"\n'
                f'data = "{body.replace(chr(34), chr(92) + chr(34))}"\n'
                "silent\n"
                "show-error\n"
            )
            _lock_and_write_open_fd(fd, Path(cfg_path), curl_config.encode("utf-8"))
            try:
                proc = run_command(
                    ["curl", "-K", cfg_path, "-w", "\n%{http_code}"],
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
            except ExecutionFailure as exc:
                if exc.diagnostic.kind == "timeout":
                    die("curl to the bootstrap endpoint timed out")
                if exc.diagnostic.kind == "not-found":
                    die("curl not found on PATH")
                die("curl to the bootstrap endpoint could not be started")
        finally:
            try:
                os.unlink(cfg_path)
            except OSError:
                pass

        # Last line is the HTTP status (from -w); everything before is the body.
        raw = proc.stdout.rsplit("\n", 1)
        body_text = raw[0] if len(raw) == 2 else proc.stdout
        status = raw[1].strip() if len(raw) == 2 else ""
        if proc.returncode != 0:
            die(f"curl request for role '{role}' failed (exit {proc.returncode})")
        if status == "401":
            die("bootstrap secret rejected (401) — check AGENT_BUS_BOOTSTRAP_SECRET")
        if status == "404":
            die(
                f"endpoint returned 404 for role '{role}': either the bus has no "
                "AGENT_BUS_BOOTSTRAP_SECRET configured (feature disabled) or that role "
                "is not in AGENT_BUS_AGENT_TOKENS"
            )
        if status != "200":
            die(f"unexpected HTTP {status or '?'} fetching role '{role}'")
        tok = _extract_json_token(body_text)
        if not tok:
            die(f"200 OK but no token in response for role '{role}'")
        out[role] = tok
    return out


def _extract_json_token(body_text: str) -> str:
    """Pull the `token` field out of a {"agent":..,"token":..} JSON body.

    Uses json.loads; the value is returned but never logged."""
    try:
        obj = json.loads(body_text)
    except (json.JSONDecodeError, ValueError):
        return ""
    tok = obj.get("token") if isinstance(obj, dict) else None
    return str(tok).strip() if tok else ""


def parse_tokens(line: str) -> dict:
    """Parse `architect=A,coder=B,reviewer=C` -> {role: token}. Values not logged."""
    out: dict = {}
    for part in line.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        role, tok = part.split("=", 1)
        out[role.strip()] = tok.strip()
    if not out:
        die("token line parsed to zero roles (unexpected format on VPS)")
    return out


# ---------------------------------------------------------------------------
# cross-platform binary path resolution: probe first, default fallback
# ---------------------------------------------------------------------------


def posix_to_native(path: str) -> str:
    """Translate legacy Git-Bash paths while migrating to native Windows paths."""
    return native_executable(path)


def probe_is_file(path: str) -> bool:
    return Path(posix_to_native(path)).is_file()


def resolve_bus_bin(cli_val: str, agent_bus_repo: str) -> tuple:
    """Return (path, note). Probe order: --bus-bin > env > repo venv > PATH > default.

    New Windows files store native paths. Legacy Git-Bash paths remain probeable."""
    env_val = os.environ.get("AWF_BUS_BIN", "")
    if cli_val:
        return cli_val, "from --bus-bin"
    if env_val:
        return env_val, "from existing AWF_BUS_BIN env"
    defaults = PLATFORM_DEFAULTS[platform_key()]
    # Forward slashes are accepted by native Windows Python and remain portable data.
    candidate = agent_bus_repo.rstrip("/") + "/" + defaults["bus_bin_rel"] if agent_bus_repo else ""
    if candidate and probe_is_file(candidate):
        return candidate, "probed agent-bus repo venv"
    on_path = shutil.which("agent-bus")
    if on_path:
        return on_path, "found on PATH"
    return "agent-bus", "default command name (not yet verified)"


def resolve_opencode_bin(cli_val: str) -> tuple:
    """Return (path, note) or ('', reason) if none needed/found."""
    env_val = os.environ.get("AWF_OPENCODE_BIN", "")
    if cli_val:
        return cli_val, "from --opencode-bin"
    if env_val:
        return env_val, "from existing AWF_OPENCODE_BIN env"
    default = PLATFORM_DEFAULTS[platform_key()]["opencode_bin"]
    # On Windows the executor needs the explicit .cmd (it lives outside PATH in
    # the known setup); prefer the verified default over a possibly-wrong PATH hit.
    if default and probe_is_file(default):
        return default, "probed platform default path"
    on_path = shutil.which("opencode")
    if on_path:
        return "", "opencode on PATH (no AWF_OPENCODE_BIN needed)"
    if default:
        return default, "DEFAULT (not verified - please check this path)"
    return "", "opencode not found; set --opencode-bin if the tool machine needs it"


# ---------------------------------------------------------------------------
# assemble + write dispatch.env (0600)
# ---------------------------------------------------------------------------


def build_env_lines(url, tokens, roles, bus_bin, opencode_bin, via="curl") -> list:
    """Build the dispatch.env lines. Token values are included ONLY here (the
    file we write with 0600); this list is never logged."""
    src = (
        "the Agent Bus POST /bootstrap/token endpoint"
        if via == "curl"
        else "the VPS /etc/agent-bus/.env AGENT_BUS_AGENT_TOKENS source of truth"
    )
    comments = [
        "# Agent Workflow dispatch/listen credentials.",
        f"# Generated by scripts/awf_bootstrap.py (via {via}) from",
        f"# {src}. Do NOT commit. chmod 600.",
    ]
    values = {"AGENT_BUS_URL": url}
    for role in roles:
        var = ROLE_TO_TOKEN_VAR[role]
        tok = tokens.get(role)
        if not tok:
            die(f"role '{role}' requested but no token for it on the VPS")
        values[var] = tok
    if bus_bin:
        values["AWF_BUS_BIN"] = bus_bin
    if opencode_bin:
        values["AWF_OPENCODE_BIN"] = opencode_bin
    try:
        body = serialize_config(values).splitlines()
    except ConfigError as exc:
        die(f"refusing to write invalid operations configuration: {exc}")
    return [*comments, *body, ""]


def redact_lines(lines: list) -> list:
    """Return a printable copy with token values masked (for --print)."""
    out = []
    token_vars = set(ROLE_TO_TOKEN_VAR.values())
    for ln in lines:
        masked = ln
        for var in token_vars:
            prefix = "export " if ln.startswith("export ") else ""
            if ln.startswith(f"{prefix}{var}="):
                masked = f"{prefix}{var}=****(redacted)"
                break
        out.append(masked)
    return out


def lock_permissions(path: Path) -> str:
    """Restrict `path` to the current user only. Returns a short note on the
    mechanism used.

    POSIX: chmod 0600. Windows: os.chmod only toggles the read-only bit and
    CANNOT produce owner-only access, so we use icacls to strip inherited ACEs
    and grant Full control to just the current user. Without this, a Windows
    dispatch.env stays group/Administrators-readable (a real credential leak)."""
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
            return "chmod 600"
        except OSError as e:
            die(f"could not restrict configuration permissions: {e}")
    # Windows: lock via ACL.
    identity = run_command(["whoami"], capture_output=True, text=True)
    principal = identity.stdout.strip() if identity.returncode == 0 else ""
    if not principal:
        die("could not determine the current Windows principal for ACL lockdown")
    proc = run_command(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        die("could not restrict the Windows configuration ACL")
    acl = run_command(["icacls", str(path)], capture_output=True, text=True)
    if acl.returncode != 0:
        die("could not verify the Windows configuration ACL")
    aces = _parse_icacls_aces(path, acl.stdout)
    if not aces:
        die("could not parse the Windows configuration ACL")
    for other, _permissions in aces:
        if other.casefold() == principal.casefold():
            continue
        for removal in ("/remove:g", "/remove:d"):
            removed = run_command(
                ["icacls", str(path), removal, other],
                capture_output=True,
                text=True,
            )
            if removed.returncode != 0:
                die("could not remove an extra Windows configuration principal")
    try:
        validate_config_path(
            path,
            platform="windows",
            expected_uid=None,
            runner=run_command,
        )
    except ConfigError:
        die("could not establish an owner-only Windows configuration ACL")
    return "icacls: owner-only"


def _lock_and_write_open_fd(fd: int, path: Path, content: bytes) -> str:
    """Lock a mkstemp path, then write through its still-open descriptor."""
    try:
        note = lock_permissions(path)
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return note


def _atomic_owner_only_write(target: Path, content: bytes, *, prefix: str) -> str:
    """Create, lock, then populate a same-directory temp before atomic replace."""
    fd, temporary_name = tempfile.mkstemp(prefix=prefix, dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        note = _lock_and_write_open_fd(fd, temporary, content)
        os.replace(temporary, target)
        return note
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_env_file(dest: Path, lines: list, force: bool) -> None:
    if not dest.is_absolute():
        die("configuration destination must be an absolute path")
    if dest.exists() and not force:
        die("destination already exists; pass --force to overwrite (a .bak is kept)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and force:
        try:
            validate_config_path(
                dest,
                platform="windows" if os.name == "nt" else "posix",
                expected_uid=None,
                runner=run_command,
            )
        except ConfigError as exc:
            die(f"existing configuration path is unsafe: {exc}")
        backup = dest.with_suffix(dest.suffix + ".bak")
        if backup.exists() or backup.is_symlink():
            die("refusing to replace an existing configuration backup")
        _atomic_owner_only_write(backup, dest.read_bytes(), prefix=".dispatch-backup-")
        log(f"backed up existing file -> {backup.name}")
    note = _atomic_owner_only_write(
        dest,
        "\n".join(lines).encode("utf-8"),
        prefix=".dispatch-",
    )
    log(f"permissions: {note}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    # Windows consoles default to gbk/cp936; a non-ASCII byte in a path or error
    # would crash a log line. Degrade to a replacement char instead.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    p = argparse.ArgumentParser(
        prog="awf_bootstrap",
        description="Assemble ~/.config/awf/dispatch.env from the VPS token source of truth.",
    )
    p.add_argument(
        "--via",
        choices=("curl", "ssh"),
        default="curl",
        help="token transport: curl (POST /bootstrap/token, default) or ssh (VPS .env fallback)",
    )
    p.add_argument(
        "--source-host",
        default=os.environ.get("AWF_BOOTSTRAP_SOURCE_HOST", DEFAULT_SOURCE_HOST),
        help="[--via ssh] ssh alias of the token source (or AWF_BOOTSTRAP_SOURCE_HOST)",
    )
    p.add_argument(
        "--source-path",
        default=DEFAULT_SOURCE_PATH,
        help=f"path to the source .env on the host (default: {DEFAULT_SOURCE_PATH})",
    )
    p.add_argument("--url", default="", help="AGENT_BUS_URL (default: existing environment value)")
    p.add_argument(
        "--roles",
        default="architect,coder,reviewer",
        help="comma-separated roles to install tokens for (default: all)",
    )
    p.add_argument(
        "--agent-bus-repo",
        default="",
        help="agent-bus repo dir (used to probe the venv agent-bus binary)",
    )
    p.add_argument("--bus-bin", default="", help="explicit AWF_BUS_BIN (overrides probing)")
    p.add_argument("--opencode-bin", default="", help="explicit AWF_OPENCODE_BIN")
    p.add_argument(
        "--dest", default="", help="dispatch.env path (default: ~/.config/awf/dispatch.env)"
    )
    p.add_argument("--force", action="store_true", help="overwrite an existing dispatch.env")
    p.add_argument(
        "--print",
        dest="do_print",
        action="store_true",
        help="print the assembled file WITH TOKENS REDACTED; do not write",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="show the plan; do NOT ssh and do NOT write"
    )
    a = p.parse_args(argv)

    roles = [r.strip() for r in a.roles.split(",") if r.strip()]
    for r in roles:
        if r not in ROLE_TO_TOKEN_VAR:
            die(f"unknown role '{r}' (known: {', '.join(ROLE_TO_TOKEN_VAR)})")

    dest = Path(a.dest) if a.dest else Path.home() / ".config/awf/dispatch.env"
    url = a.url or os.environ.get("AGENT_BUS_URL", "")
    if not url:
        die("AGENT_BUS_URL must be supplied through --url or the environment")
    if a.via == "ssh" and not a.source_host:
        die("--via ssh requires --source-host or AWF_BOOTSTRAP_SOURCE_HOST")

    defaults = PLATFORM_DEFAULTS[platform_key()]
    agent_bus_repo = a.agent_bus_repo or defaults["agent_bus_repo"]
    bus_bin, bus_note = resolve_bus_bin(a.bus_bin, agent_bus_repo)
    opencode_bin, oc_note = resolve_opencode_bin(a.opencode_bin)

    # For --via curl the bootstrap secret must be in the environment (never a flag).
    boot_secret = os.environ.get("AGENT_BUS_BOOTSTRAP_SECRET", "").strip()

    log(f"platform={platform_key()} destination=withheld via={a.via}")
    if a.via == "ssh":
        log(f"source=ssh (location withheld) roles={','.join(roles)}")
    else:
        log(f"source=bootstrap endpoint (location withheld) roles={','.join(roles)}")
    log("AGENT_BUS_URL=configured (value withheld)")
    log(f"AWF_BUS_BIN={'configured' if bus_bin else 'unset'} ({bus_note})")
    log(f"AWF_OPENCODE_BIN={'configured' if opencode_bin else 'unset'} ({oc_note})")
    if "not yet verified" in bus_note:
        log("WARN: AWF_BUS_BIN is an unverified default - confirm the path or pass --bus-bin")
    if "not yet verified" in oc_note:
        log("WARN: AWF_OPENCODE_BIN is an unverified default - confirm or pass --opencode-bin")

    if a.via == "curl" and not boot_secret:
        die(
            "--via curl needs AGENT_BUS_BOOTSTRAP_SECRET in the environment "
            "(export it; it is never taken as a flag). Or use --via ssh."
        )

    if a.dry_run:
        how = "curl POST /bootstrap/token" if a.via == "curl" else "ssh token source"
        log(f"--dry-run: would fetch tokens via {how} and write dispatch.env. Nothing done.")
        return 0

    # Refuse an existing file BEFORE the network round-trip (only when actually writing).
    if not a.do_print and dest.exists() and not a.force:
        die("destination already exists; pass --force to overwrite (a .bak is kept)")

    if a.via == "curl":
        log(f"fetching {len(roles)} token(s) via curl (values are never printed)...")
        tokens = fetch_tokens_curl(url, boot_secret, roles)
    else:
        log("fetching tokens over ssh (source and values withheld)...")
        tokens = parse_tokens(fetch_tokens_line(a.source_host, a.source_path))
    missing = [r for r in roles if r not in tokens]
    if missing:
        src = "endpoint" if a.via == "curl" else "VPS token line"
        die(f"{src} has no entry for: {', '.join(missing)}")
    log(f"got tokens for roles: {', '.join(sorted(tokens))} (values withheld)")

    lines = build_env_lines(url, tokens, roles, bus_bin, opencode_bin, via=a.via)

    if a.do_print:
        log("--print: assembled dispatch.env (tokens redacted), NOT written:")
        print("\n".join(redact_lines(lines)))
        return 0

    write_env_file(dest, lines, a.force)
    log(f"wrote owner-only configuration. {len(roles)} role token(s) installed.")
    log("next: `awf-handoff-check` to verify this machine can dispatch/execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
