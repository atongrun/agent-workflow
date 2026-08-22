# Phase 5-01 Capability-First Init ImplementationReport

## Result

Implemented the TaskCard-approved L2 vertical slice on
`codex/phase5-01-capability-init` from integrated Phase 4B base
`6ce518273cc21cabdf9821ab01958e9f7f7a01ac`. No TaskCard was executed, no model or business event
was sent, and no Runtime default, Agent Bus server, migration, release or Phase 5-02 boundary was
changed.

## User journey

Normal machine onboarding is now:

```text
awf init
  -> verify Git and authenticated GitHub CLI
  -> resolve configured Agent Bus client
  -> prove agent-bus.listen.on-argv.v1 from local listen --help
  -> detect installed OpenCode/Pi/Codex version probes
  -> recommend supported role bindings
  -> accept with Enter or customize roles/tool/model
  -> stage one exact local clone per selected role
  -> atomically write exact credential-free role profiles and .awf/machine.json
  -> Finding off unless --finding-enabled

awf doctor
awf status
awf start|stop|drain|logs
```

Non-interactive automation uses `--roles architect,coder,reviewer` plus the existing per-role model
flags. `--roles none` is an explicit zero-role machine. Existing TaskCard-bound onboarding remains
available through `awf enroll` and the compatibility `awf init --card ...` path.

Model selection has two persisted machine-binding modes. `tool-default` stores no reference and the
role profile keeps the existing empty `model` value, so renderers omit an explicit model argument.
`explicit` stores one bounded opaque tool-native reference and the profile/renderers pass it
unchanged, for example Pi `--model opencode-go/deepseek-v4-flash`. Init does not inspect private
tool configuration, query model APIs, authenticate providers or mutate any tool default. Manual
entry and tool-default are sufficient; later tool rejection cannot silently fall back.

## Supported product capability matrix

| Role | Supported agent tool(s) |
|---|---|
| Architect | Pi |
| Coder | OpenCode |
| Reviewer | OpenCode, Pi, Codex |

The matrix is a closed static mapping, not a registry or plugin system. `architect + none` remains
the internal deterministic terminal-listener compatibility shape but is not advertised as an agent
tool. Unsupported selections fail before profile/workspace/machine-config mutation.

## Machine composition and workspace identity

- `.awf/machine.json` is ignored, credential-free local configuration. It binds machine/project,
  source repository, shared host-local state root, Finding state and exact per-role profile digest,
  workspace, tool and normalized `{mode, ref}` model-selection facts. It is not Workflow authority.
- Every selected role receives one deterministic profile name and a separate full local Git clone
  under the AWF config home. Clones are detached at the source HEAD and receive the exact existing
  trusted upstream/fork remote names and URLs after embedded-credential denial.
- Existing exact clean clones may be reused. Unknown, dirty, drifted or mismatched destinations fail
  with explicit operator remediation; init does not delete or guess-repair them.
- New clones are staged before rename. On a failed initialization, only exact staging or final paths
  created by that invocation are cleaned.
- Coder and Reviewer may point to the same OpenCode executable/config. Their profiles, roles,
  state nodes, listener leases and workspace paths remain distinct. Exact same tool/model emits one
  non-blocking review-independence note.
- Existing live listener same-path conflict rejection is unchanged.

## Pi Architect support

- `InvocationSpec` now accepts only `architect + pi` at the closed provider-contract boundary.
- `PiArchitectRenderer` uses text/no-session/no-approve/no-extension/no-skill mode, the existing
  read-only `read,grep,find,ls` tool set, one exact trusted context file and TaskCard stdout.
- Pi has no direct TaskCard or Git write authority.
- `runtime.architect.persist_architect_taskcard` validates bounded UTF-8, safe Task ID/branch,
  postflight JSON, safe/unique allowed paths, exact ImplementationReport/ReviewReport bindings,
  secret shapes, repository containment, parent/symlink/escape and create-only destination before
  writing. It returns only `ArtifactFact`; no RunSpec, Store, journal, application, transport,
  listener or Workflow transition consumes it in Phase 5-01.

## Agent Bus compatibility

- Init and node doctor resolve the configured client, run local `listen --help`, and require
  `--on-argv` before Bus health/listener work.
- Readiness records `agent-bus.listen.on-argv.v1`, resolved executable SHA-256, help-output SHA-256
  and their combined provenance digest. The client has no reliable version command, so diagnostics
  state `unreported; capability-probed` instead of trusting historical `0.3.0` ambiguity.
- Init never installs or changes Agent Bus and sends no event. A formal compatible Agent Bus client
  release remains the separate pre-dogfood prerequisite.

## Finding default

- Node profile schema adds only `finding_enabled: boolean`; omission is false.
- Profile-driven listeners pass an explicit internal flag. Off means no Finding prompt injection,
  no capture/strip/queue attempt and no Feedback block in normal status.
- Explicit true preserves existing Phase A prompt, capture, Feedback Outbox and reporter CLI
  behavior. `awf feedback ...` remains independently callable.
- No Finding field was added to RunSpec, InvocationSpec, Runtime application, Store/journal,
  transport or Workflow authority.

## Verification

- TaskCard boundary Review: initial `REQUEST_CHANGES` on two ambiguity findings; repaired TaskCard
  `8ba54c1`; focused re-review `PASS`. Owner model-selection clarification `7a0abb2` then received a
  second focused boundary `PASS` without widening the milestone.
- Focused Phase 5-01 suite: `470 passed, 2 skipped`.
- Full repository suite after the Runtime export repair and model-binding clarification:
  `913 passed, 5 skipped`.
- Ruff check and format check: PASS across the repository.
- Compileall and `git diff --check`: PASS.
- Resource validation: roles `6/6`, workflows `4/4`, examples `3/3` PASS.
- Fresh wheel from unrelated cwd: PASS for exact wheel SHA-256
  `a9d44e394df6bc68a1f306b56d949a64213e89b289ca21f318499609f8f2d9b5`.
- No provider/model invocation, Agent Bus event, ACK/retry/requeue, remote service, lifecycle
  manager or retained state operation was used for acceptance.

## Closed development failure

The first full suite found two Runtime root-export allowlist failures because the new Pi class/helper
were initially added to `agent_workflow.runtime.__all__`. The repair removed both root exports and
kept the existing public package boundary unchanged: provider use remains through the existing
`render_provider_invocation`, and trusted TaskCard persistence is an explicit submodule function.
Focused boundary tests and the full suite then passed.

The first independent L2 candidate Review returned `REQUEST_CHANGES` for one partial-init boundary:
profile files were replaced one-by-one before machine config, so a later write failure could split
old/new bindings. The bounded repair stages and validates all profile/config files, uses exact
same-filesystem backups during one recoverable batch, validates the final machine binding before
discarding backups, and restores byte-identical predecessors on any failure. A four-row table-driven
fault test covers fresh/replace state crossed with mid-profile/machine-config failure. No Workflow,
Runtime authority or lifecycle semantics changed.

## Limitations and next boundary

- Phase 5-01 does not invoke Pi Architect through `awf run`; it supplies the real renderer and
  non-authorizing trusted output seam for the next milestone.
- Machine role workspaces are exact at init HEAD; advancing or replacing them requires explicit
  operator action rather than hidden synchronization.
- Agent Bus server reachability and each selected role token/provider are fully verified by
  `awf doctor`, not by an event during init.
- Formal Agent Bus release identity remains absent and is required before real Phase 5 dogfood.
- The only next legal milestone is a separately frozen Phase 5-02 TaskCard for fresh
  `awf run <TaskCard>` production integration. It has not started.
