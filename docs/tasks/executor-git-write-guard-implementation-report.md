# Executor Git Write Guard Implementation Report

## Incident

Downstream dogfood event `97` reached the Windows OpenCode executor on the frozen product branch.
The executor ignored the explicit prompt boundary, committed, and pushed before returning. The
trusted runner subsequently failed postflight because no working-tree changes remained, so the
event stayed unacknowledged and no reviewer event was emitted. The pushed side-effect branch is
preserved as evidence; it was not reset, acknowledged, or requeued.

## Changes

- OpenCode coder and fallback reviewer subprocesses run in fresh event-scoped clones outside the
  trusted checkout. The runner removes every remote before model invocation and does not expose the
  source checkout through `AWF_REPO_DIR`, `PWD`, `INIT_CWD`, Git repository-path variables,
  alternates, reflogs, or `FETCH_HEAD` metadata.
- Model children receive an explicit cross-platform environment allowlist rather than the parent
  environment. Listener `AWF_*`, Agent Bus, inherited process Git config, cloud credentials,
  provider API keys, arbitrary secrets, and executable-injection variables are absent. The runner
  reintroduces only the isolated workspace path and the interpreter needed by the Git shim.
- Git shim and hook assets are copied to a fresh event-local guard directory. Neither `PATH` nor
  `core.hooksPath` discloses the trusted Agent Workflow checkout, and inherited `PATH` entries below
  that checkout are removed.
- A model-only Git shim permits read-oriented inspection commands and rejects write/unknown
  commands even when `--no-verify` or higher-precedence `git -c` options are supplied.
- Model environments also remove GitHub/GitLab token, askpass, SSH command, and SSH-agent credential
  channels. Protocol denial, invalid push URLs, and hooks remain defense in depth.
- After model return, the runner rejects isolated `HEAD`, remote-set, or reviewer-base mutation and
  refreshes the real remote task ref before accepting output.
- Before any post-model Git command, the runner compares an in-memory hash manifest of mutable
  `.git` control metadata. Changes to config, refs, index, hooks, or info files fail before Git can
  execute a model-planted helper. Import Git plumbing also runs in a credential-free environment
  with global/system config, fsmonitor, hooks, external diff, and textconv disabled.
- TaskCard verification commands are treated as model-controlled code: the runner rechecks the Git
  metadata manifest immediately after verification and again after delta gates. Delta discovery,
  secret scanning, and whitespace checks always use the credential-free Git plumbing, so a
  verification-time helper injection cannot regain the runner environment.
- Frozen verification, allowed-path, artifact, secret, and diff gates run inside the isolated coder
  workspace. The runner serializes its full binary Git delta, applies it to the trusted checkout,
  and requires both Git tree hashes to match before commit/push.
- OpenCode reviewer fallback may create only its requested ReviewReport; the runner validates and
  copies that report back. Codex review remains in its existing read-only sandbox.
- Reviewer TaskCard and ImplementationReport inputs must resolve to repository-relative files;
  absolute paths and parent traversal fail before either review tool starts.
- Trusted executor commits now use contiguous git-native Lore trailers.
- The trusted checkout commits the exact index produced by verified `git apply --index`; it no
  longer runs a second `git add -A`, and it rechecks the staged tree immediately before commit.
- Windows model environments disable current-directory executable lookup, and every production
  `.cmd`/`.bat` wrapper uses `cmd.exe /d /s /c` so AutoRun cannot run in model, listener, handoff, or
  credential-bearing event-send paths.
- The executor prompt states that the guard is enforced and Git writes must not enter its task
  list.

Trusted runner Git operations use the parent environment and are unaffected. Agent Bus code,
protocol, authentication, storage, and historical events are unchanged.

This boundary closes the observed prompt-violating ordinary Git command class, including
`--no-verify` and `git -c` through the model's normal `PATH`. It is not presented as a hostile-code
sandbox: an arbitrary same-user process can seek an absolute Git binary, another network client,
or ambient credential storage. Eliminating that residual requires a separate uncredentialed OS
principal/container and network policy, which is outside this recovery patch.

## Verification

- Regression tests first failed against the prompt-only boundary. Two independent security passes
  then proved hooks/push URL denial and environment Git config were bypassable with direct remotes,
  `--no-verify`, `git -c`, or cleared `GIT_CONFIG_*`; both vulnerable heads were rejected.
- Real Git tests prove the normal model Git path rejects commit and direct bare-origin push even
  with `--no-verify` plus `git -c protocol.file.allow=always`, leaving the external ref unchanged.
- Isolation tests prove the model clone has the exact dispatched `HEAD`, no remote, no alternates,
  no reflogs or `FETCH_HEAD`, and no source-checkout path in any `.git` metadata file while local Git
  inspection remains available.
- Environment tests prove trusted runner paths, Bus metadata, inherited Git config, cloud/provider
  credentials, arbitrary secrets, and injection variables do not reach the model process.
- A malicious repository-local `diff.external` configuration is rejected by the raw metadata gate
  before any Git command runs with trusted state.
- A verification command that mutates `.git/config` is rejected before delta discovery performs
  any Git read.
- Delta tests cover tracked modification, deletion, untracked binary import, exact tree equality,
  `.git` metadata exclusion, and a late trusted-checkout file that remains untracked and absent from
  the pushed commit.
- End-to-end coder tests prove only the trusted runner creates the Lore commit/push; a model-created
  local commit fails before either the trusted checkout or external ref changes.
- The OpenCode reviewer return-chain test runs in the isolated clone and imports only the validated
  report.
- Reviewer boundary tests reject absolute and parent-traversing TaskCard or ImplementationReport
  paths before model invocation.
- Ref-integrity tests reject local `HEAD`, remote task-branch, model remote, and reviewer-base
  mutation.
- `git interpret-trailers --parse` recognizes the generated executor commit trailers.
- Full Mac suite after the final security rework: 200 passed, 1 Windows-only skip.
- Exact-head Windows Python 3.12 role module: 155 passed, 1 expected platform skip; the focused
  `git -c ... push --no-verify` bypass regression passed through the Windows `cmd` resolution path.
- A diagnostic full-repository Windows run had 190 passes, the same expected skip, and one unrelated
  pre-existing CLI newline assertion (`\r\n` vs `\n`); PR #22 does not change that CLI surface.
- Ruff check and format, shell syntax, and `git diff --check`: passed.

## Remaining Verification

- Fresh exact-head Windows Python 3.12 role/full verification, independent native Codex security
  review, GitHub CI, merge, and three-machine exact-version rollout.
- The pre-existing retry gap after a successful push but failed downstream event send remains a
  separate operations issue. It requires a durable/idempotent outbox design and is intentionally
  not mixed into this Git-boundary security patch. No historical event is acknowledged, requeued,
  or mutated by this change.
