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

Reviewer providers are intentionally narrow: Codex, OpenCode, and Pi. Pi is
reviewer-only. Its adapter invokes `pi --print --mode text` with read-only tools
(`read,grep,find,ls`), no session, and no project-local approval, extensions,
skills, prompt-template, or context autoloading. Because that tool set cannot write files, the trusted runner
captures stdout and atomically persists it as the exact ReviewReport path only
after Pi exits with status 0; the existing ReviewReport parser and routing gate
still validate size, schema, secrets, and verdict before ACK-sensitive work.
The trusted runner also supplies a credential-free base-to-HEAD diff capped at
64 KiB so Pi can inspect the committed change without a command tool. The
prompt, diff, template, and TaskCard travel through a runner-owned `@file`
attachment outside the model workspace, keeping Windows argv short and keeping
the sole importable workspace delta equal to the ReviewReport. If that context
or the ImplementationReport is insufficient, the Pi prompt requires `BLOCKED`,
not a speculative `PASS`.
Pi provider authentication and model catalogs remain owned by Pi's external
configuration directory. `model_env()` preserves explicit
`PI_CODING_AGENT_DIR`/`PI_CODING_AGENT_SESSION_DIR` pointers outside the
trusted repository; `--no-session` prevents review-session persistence, but Pi
may still take its own settings lock. The listener service identity must have a
usable Pi configuration directory, and Fast Preflight must probe that actual
CLI identity before dispatch.

For metadata-complete v1-v3 coder/reviewer deliveries, the lifecycle first reconstructs and hashes
the payload, validates its delivery identity, and then requires the effective listener-local
`tool`/`model` selection to match that hashed selection. This compatibility gate runs before the
control-plane pre-invocation decision, recovery/outbox replay, model launch, outbox preparation, or
inbox completion. Direct local entry points without delivery metadata keep their existing
environment-override behavior.

When coder and reviewer use different providers, the owner RunManifest and one strict
`awf-reviewer-selection` JSON comment in the frozen TaskCard carry both role pairs. The initial
delivery already hashes the exact TaskCard path and commit, so the committed block is transitively
bound without adding optional fields to historical v3 payloads. Dispatch compares the manifest
and TaskCard before mutation. After trusted checkout, each handler validates its own pair before
model invocation; coder review handoff emits the reviewer pair, and a reviewer
`REQUEST_CHANGES` route emits the coder pair. A card without the block preserves the historical
same-pair behavior.

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

## Listener ownership and terminal workspace

`awf_listen.py` establishes local ownership before starting Agent Bus. The configured path must be
the Git root; coder and reviewer roots must be clean, while architect roots may contain operator
work because terminal verification is isolated. A per-user, registry-locked lease rejects a live
duplicate role or two live roles sharing one repository. Stale leases are removed only after an
OS-specific, non-signalling PID check. These denials occur before the listener can consume an event.

The thin `awf node` lifecycle does not assume that its spawned PID is the interpreter PID. Each
managed start creates a random launch identity shared only by its process record and listener lease.
Readiness, status, and stop require that identity plus the role/repository binding. The listener PID
continues to own duplicate detection, while the spawned launcher/process-group PID continues to own
liveness checks and local interrupt signaling. Both PIDs must still be live before a managed node is
reported running or signaled; local stop waits for both sides to exit. Legacy process records without
a launch identity use only their exact PID; role/repository similarity is never sufficient ownership
proof.

The architect terminal handler treats its configured repository as read-only configuration and
object input. It creates a fresh event-scoped clone, copies the already validated remote URLs,
performs all fetch, PR tuple, exact-commit, TaskCard, and ImplementationReport checks inside that
workspace, then removes its remotes. It never checks out, stashes, cleans, or updates refs in the
source checkout. Ledger persistence still precedes inbox completion, and Agent Bus still owns the
success-gated ACK.

`Ctrl-C` is a local lifecycle action, not a transport event. The listener returns 130, releases
only its matching lease under the same registry lock, and emits one concise diagnostic without a
Python traceback. `control:shutdown` remains available for remote cooperative stop.
