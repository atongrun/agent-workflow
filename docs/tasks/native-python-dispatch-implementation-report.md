# Native Python Dispatch Implementation Report

## Status

Implementation-complete on the feature branch. Clean Linux and Windows exact-head CI remain merge
gates.

## Why

The former production dispatcher mixed 229 lines of Bash, embedded Python, Git publication,
delivery hashing, proxy environment handling, and Agent Bus invocation. A clean Windows runner
demonstrated that generic `bash` resolution could select the WSL launcher instead of Git Bash even
when the Workflow logic itself was correct.

## Result

- `scripts/awf_dispatch.py` is the production entry point on macOS, Linux, and Windows.
- `scripts/awf_delivery.py` owns canonical JSON, payload hashing, and delivery IDs shared by
  dispatch and role handlers.
- `scripts/awf-dispatch.sh` is a small POSIX-only compatibility shim.
- Windows dispatch no longer requires Git Bash, WSL, `cygpath`, or shell path translation.
- Windows dispatch requires `AWF_BUS_BIN` to resolve to a native executable; `.cmd` and `.bat`
  wrappers are rejected so model- or task-controlled payload bytes never cross `cmd.exe /c`.
- Configuration remains strict data loaded by `awf_config.py`; explicit environment values still
  win.

## Preserved Contracts

- TaskCards are committed before publication.
- Push failure prevents Agent Bus delivery.
- V3 dispatch validates canonical credential-free upstream/fork remotes and identical fetch/push
  bindings.
- Fresh remote head and base SHAs bind the provenance payload.
- Canonical payload JSON, SHA-256, delivery ID, and source event ID retain their existing formats.
- `--dry-run`, `--no-push`, default report paths, role/model hints, and `NO_PROXY` behavior remain
  compatible.
- Tokens remain in the child environment and never enter logs or command arguments.
- Agent Bus inherits no interactive stdin.

## Compatibility

Existing macOS/Linux callers may continue using `scripts/awf-dispatch.sh`; it delegates immediately
to the Python implementation. Windows callers use:

```text
python scripts/awf_dispatch.py ...
```

Historical implementation reports retain references to the former shell implementation because
those references describe evidence collected at that time.
