# Runtime command execution architecture

## Decision

All local production command execution crosses `scripts/awf_executor.py`.
Pure renderers under `scripts/agent_adapters/` own provider-specific argv,
prompt, stdin, file-attachment, model-flag, read-only, and output-path syntax.
The trusted Workflow lifecycle in `scripts/awf_role.py` continues to select the
provider, read and validate Workflow inputs, prepare the model environment,
start and track execution, and enforce checkpoint, postflight, outbox, and ACK
ordering. It passes each rendered invocation to `scripts/awf_executor.py`, the
only operating-system process boundary.

Workflow business modules and provider renderers do not import `subprocess`,
select a shell, join argv into a command string, or use `shell=True`.

PowerShell, Git Bash, and zsh are supported launch environments, not business
command interpreters. Runtime detection affects executable-path normalization
and failure diagnostics only. Ordinary commands always reach the operating
system as argv with `shell=False`.

## Audit finding

Before this boundary existed, command policy was split across:

- `awf_role.spawn()` and several direct Git/GitHub/Agent Bus calls;
- native dispatch's private Git runner and Agent Bus sender;
- listener, bootstrap, configuration, and handoff-check subprocess calls;
- the copied model Git guard.

Those paths disagreed about closed stdin, UTF-8, timeouts, `.cmd` handling,
capture, and error messages. Removing Git Bash from dispatch fixed a hot path,
but did not prevent later business code from reintroducing a different process
policy.

## Executor contract

`detect_runtime()` classifies:

- Windows launched from PowerShell;
- Windows launched from Git Bash/MSYS;
- native Windows;
- macOS launched from zsh;
- other POSIX environments.

`normalize_command()`:

- accepts a non-empty sequence of strings or path-like values, never a command
  string;
- preserves argument boundaries, whitespace, Unicode, and shell metacharacters;
- converts only a legacy Git Bash executable path such as `/c/tools/x.exe` to
  a native Windows executable path;
- rejects NUL and empty arguments;
- rejects Windows `.cmd`/`.bat` wrappers unless the caller explicitly opts into
  the centralized compatibility policy.

`run()` and `start()`:

- always use `shell=False`;
- close stdin by default;
- standardize UTF-8 text mode;
- preserve the caller's explicit environment policy;
- convert missing executables, permission failures, spawn errors, and timeouts
  into `ExecutionFailure`;
- expose bounded, redacted `FailureDiagnostic` data.

Long-running model execution retains its existing PID, cwd, duration,
interruption, kill, reap, and exit evidence in `awf_role.spawn()`. That function
remains trusted Workflow execution glue over the shared executor rather than a
second process boundary. The provider renderers are pure: they do not read
files, select providers, start processes, write evidence, validate artifacts,
or decide Workflow stages and transitions.

## Windows wrapper policy

Native executables are preferred. Dispatch continues to reject `.cmd` and
`.bat` Agent Bus binaries because dispatch payload bytes must not cross
`cmd.exe`.

Some npm-installed Windows tools expose a `.cmd` shim plus a matching `.ps1`
launcher. Those callers must declare `allow_shell_wrapper=True`; only the
executor may replace the `.cmd` path with its existing `.ps1` companion and
invoke it through PowerShell `-File`, preserving structured argument boundaries.
Arbitrary `.bat` files and `.cmd` files without that safe companion fail closed.
Agent Workflow never passes business argv to `cmd.exe /c`.

## Failure diagnostics

Safe diagnostics contain:

- failure kind;
- detected runtime;
- redacted executable/argv data;
- resolved cwd;
- exit code or timeout;
- bounded stdout/stderr when captured.

Token-, secret-, password-, authorization-, and API-key-shaped environment
fields are redacted. Callers can also supply exact secret values that must be
removed from argv and output diagnostics. Raw `OSError` and
`TimeoutExpired` text is never forwarded.

## Enforcement and test matrix

`tests/test_runtime_command_boundary.py` parses all production Python modules
and fails if any module other than the executor imports `subprocess`, starts a
process directly, or enables `shell=True`.

`tests/test_awf_executor.py` simulates PowerShell, Git Bash, native Windows,
macOS zsh, and generic POSIX detection. It also covers:

- Git Bash executable-path conversion;
- native argv preservation for spaces, Unicode, and metacharacters;
- explicit Windows batch-wrapper policy;
- closed stdin and `shell=False`;
- missing executable, non-zero exit, timeout, bounded output, and secret
  redaction.

CI runs the full suite on Ubuntu and Windows PowerShell, reruns executor and
boundary tests from Windows Git Bash, and runs the focused runtime suite from
macOS zsh.

## Remaining external shell boundary

Agent Bus currently accepts listener handlers as one `--on TYPE COMMAND`
template. `awf_listen.build_handler()` therefore still serializes an audited
handler template for Agent Bus to interpret. Agent Workflow does not execute
that string locally; the local Agent Bus process itself is launched through the
unified executor.

Eliminating this final external template requires an Agent Bus argv/JSON handler
contract. Until that upstream contract exists, the template remains a narrow
compatibility boundary and payload placeholder quoting remains owned by Agent
Bus.
