# TaskCard: RTS-032 Production Provider Renderer Boundary

## Task ID

runtime-v2-rts-032-provider-renderers

## Goal

Move the existing Codex, OpenCode and Pi process-command construction behind narrow installed
Runtime v2 `ProviderRenderer` implementations. Every renderer receives one immutable, fully bound
`InvocationSpec` and returns one canonical `RenderedInvocation`; the production role wrapper then
uses exactly that executable, argv, cwd, environment, stdin and declared file input at the existing
spawn boundary.

This card changes provider rendering only. The current RunLedger/checkpoint/outbox/inbox path stays
the sole production authority and recovery implementation. RTS-032 must not read or write the
RTS-031 Store, add a second launch journal, change provider replay policy, migrate state, touch
Agent Bus ordering, or change a default.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@2e8a8c1a48d08bb29b4e99352d30214734124b58`
- **Task branch**: `codex/runtime-v2-rts-032-provider-renderers`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 3 successor seam
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Passed prerequisites**: RTS-030 installed Core ports and RTS-031 disposable local Store/journal

Current `scripts/agent_adapters/` functions are pure comparison oracles. Production wrappers in
`scripts/awf_role.py` compose their input and call those functions immediately before `spawn()`.
The installed Runtime contract binds executable/argv/cwd/environment/stdin in
`RenderedInvocation`, but `InvocationSpec` currently binds only an input path. That is insufficient
for the exact stdin, inline prompt and Pi context-file bytes used by production. This card may make
the minimum immutable contract refinement needed to close that identity gap.

## Frozen provider boundary

### Fully bound InvocationSpec

Before a renderer is called, the trusted role wrapper must bind:

- exact invocation/run/task identity and one opaque digest derived from the already-authorized
  current delivery/gate facts;
- exact role, provider, model and executable;
- exact isolated workspace, input path and report path;
- exact final provider input text/bytes, structured provider options and credential-stripped
  environment.

The input payload must be bounded, immutable and included in `InvocationSpec` canonical identity.
It may contain UTF-8 multiline provider input but cannot contain NUL, credentials or an unbounded
opaque object. `InvocationSpec` still exposes no Workflow Stage, attempt/rework counter, RunStore,
journal, state-root mutation handle, Bus operation, GitHub credential or provider registry.

The opaque authorization binding is a projection of current authority for launch identity only. It
does not become a second Workflow decision, is not persisted as a new authority file and cannot
authorize a provider call without the existing pre-invocation/recovery gate.

### Canonical RenderedInvocation

`RenderedInvocation` must cover every actual process input:

- executable and argv as separate structured tokens;
- exact cwd;
- exact credential-stripped environment passed to the child;
- exact optional stdin bytes;
- exact declared file-input path and bytes where a provider consumes `@file` input.

File-input canonical identity includes path, byte length and SHA-256. A renderer declares file
bytes but performs no write. The trusted wrapper may materialize only those exact bytes at the exact
declared path immediately before spawn. It must not silently read a different file or add an
unbound argument/environment value after rendering.

### Closed provider implementations

- OpenCode coder/reviewer preserves exact current `run --dir`, optional `-f`, optional `-m`, `--`
  and final instruction argument behavior.
- Codex reviewer preserves exact current `exec -C`, read-only sandbox, output path, optional model,
  stdin and TaskCard/template input behavior.
- Pi reviewer preserves exact current no-session/no-approve/no-extension/no-skill tool boundary,
  optional model, bounded stdout path, context bytes and message behavior. Its generated context
  file is intentionally relocated from the event state directory to one exact ignored path inside
  the isolated model workspace so the selected `InvocationSpec` containment invariant can bind it;
  no other argv token or input byte may drift.

Use one explicit closed provider/role dispatch. Do not add discovery, entry points, dynamic plugins,
configuration registries, arbitrary providers or a generic provider framework.

## Production adoption rule

1. Existing delivery integrity, selection, pre-invocation authorization and recovery policy run
   before constructing the spec.
2. If legacy recovery says `model_started`, rendering/spawn remains unreachable.
3. The trusted wrapper constructs the complete spec once, renders once and passes the rendered
   values unchanged to the existing controlled subprocess path.
4. Existing checkpoint phase ordering, RunEvidence process facts, Artifact import, Git/PR,
   outbox/inbox, handler success and ACK ownership remain unchanged.
5. Direct/support entry paths must use an explicit bound compatibility identity; no implicit
   fallback to the old adapter is allowed.
6. Existing `scripts/agent_adapters/` may remain as read-only comparison or compatibility modules,
   but production `awf_role.py` must not import or call them after this card.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-032-provider-renderers.md`
- `src/agent_workflow/runtime/contracts.py`
- `src/agent_workflow/runtime/renderers.py`
- `src/agent_workflow/runtime/__init__.py`
- `scripts/awf_role.py`
- `tests/test_runtime_core_contracts.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_provider_renderers.py`
- `tests/test_runtime_command_boundary.py`
- `tests/test_awf_role.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-032-provider-renderers.md`
- `.awf/artifacts/review-report-runtime-v2-rts-032-provider-renderers.md`

After implementation, exact-head CI and independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-032-provider-renderers-implementation-report.md` and update only the
Phase 3 gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Any change to RunLedger, RTS-031 Store/journal, checkpoint/outbox/inbox/RunEvidence formats,
  Workflow transitions, route/attempt/rework/terminal decisions or status.
- Provider process implementation, retry/replay policy, Artifact validation/import, workspace/Git
  lifecycle, PR/CI, Agent Bus send/receive/ACK, handler success, lifecycle or exact stop.
- Reading, converting, shadowing, dual-writing, migrating or deleting legacy/retained state.
- New provider, generic plugin/registry/framework, scheduler, Coordinator, daemon, SQLite, Rust/Go
  production Runtime or native launcher.
- Default switch, production migration, release, live/retained-event operation or destructive
  cleanup.
- Editing the Frozen semantic contract, ADR-0006, RTS-030/031 closeouts or comparison fixtures.

## Budgets and stop rules

- New installed renderer module: at most 320 nonblank/noncomment lines.
- New focused renderer tests: at most 750 nonblank/noncomment lines.
- Net new nonblank/noncomment production lines in `scripts/awf_role.py`: at most 180.
- No new dependency; installed Runtime remains standard-library only.
- One closed renderer dispatch; no registry, discovery or provider abstraction hierarchy.
- One candidate Gate Review and at most two L3 repair/focused re-review rounds.
- If exact process input cannot be bound without persisting a second authority, modifying recovery
  ordering, weakening no-replay, or exceeding these budgets, stop with `PLAN_CONFLICT`.

## Acceptance criteria

- [ ] Task ID equals branch leaf; all changed paths remain in frozen/closeout scope.
- [ ] InvocationSpec immutably binds exact executable, multiline input bytes/text, environment and
      existing identity/path/options without exposing Workflow Stage or mutation handles.
- [ ] RenderedInvocation canonical identity covers executable, argv, cwd, environment, stdin and
      every declared file input by exact path/hash/length.
- [ ] Installed OpenCode coder/reviewer and Codex reviewer renderers reproduce current
      executable/argv/stdin behavior on the same fixtures. Pi reproduces every existing token and
      context byte with only the frozen state-directory-to-workspace context-path substitution.
- [ ] Renderer output contains no shell string and renderer code performs no filesystem, process,
      Git, Bus, network, environment-discovery or Runtime-state effect.
- [ ] Production role wrappers import only installed renderers, construct a fully bound spec after
      existing authorization/recovery gates and use rendered values unchanged at spawn.
- [ ] Pi context materialization writes only the exact declared bytes before spawn; path/content
      drift fails before provider.
- [ ] Existing credential-stripped `model_env`, evidence/tracked phase, stdout bounds, report paths,
      normalized rework feedback and TaskCard/template behavior remain byte-for-byte locked.
- [ ] Ambiguous/completed recovery fixtures prove renderer and spawn are not called again.
- [ ] No Store/journal or legacy authority representation is read/written by renderer tests; no
      second launch identity file exists.
- [ ] Installed-wheel/static boundary tests prove production no longer imports
      `scripts.agent_adapters` and the Runtime renderer package imports no operations scripts.
- [ ] LOC/dependency/closed-provider budgets pass.
- [ ] Focused tests, full pytest/Ruff and ordinary Linux/Windows/macOS CI pass on candidate head.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; any L3 repair receives focused
      re-review by the same Reviewer.
- [ ] Closeout names one later Phase 3 seam without claiming Phase 3 complete or authorizing Store
      adoption, migration, deletion or default change.

## Verification

- Local Mac: AST/static checks, direct pure renderer smoke, LOC/scope audit and `git diff --check`.
- CI: focused Runtime contracts/renderers plus full role/recovery tests, Ruff, installed-wheel and
  ordinary cross-platform jobs.
- Same-fixture parity compares exact current argv/stdin/context bytes before production import
  removal; Pi parity permits only the explicit context-path substitution frozen above.
- Fault fixtures drift executable, every argv token, cwd, environment, stdin and file input and
  prove canonical identity changes or fail-closed rejection.
- Independent Review checks full binding, renderer purity, no old-adapter fallback, no-replay
  reachability, exact spawn adoption and unchanged authority/recovery ordering.

## Required output

- installed narrow provider renderers and minimum immutable input/file identity refinement;
- production wrapper adoption at the existing spawn seam only;
- focused parity/identity/purity/no-replay tests;
- ImplementationReport and independent ReviewReport;
- owner closeout naming exactly one later Phase 3 seam.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-032-provider-renderers.md",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/renderers.py",
    "src/agent_workflow/runtime/__init__.py",
    "scripts/awf_role.py",
    "tests/test_runtime_core_contracts.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_provider_renderers.py",
    "tests/test_runtime_command_boundary.py",
    "tests/test_awf_role.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-032-provider-renderers.md",
    ".awf/artifacts/review-report-runtime-v2-rts-032-provider-renderers.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "scripts/awf_role.py", "tests/test_runtime_provider_renderers.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_core_contracts.py", "tests/test_runtime_provider_renderers.py", "tests/test_runtime_command_boundary.py", "tests/test_awf_role.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credential, token, private URL, provider/business payload, retained-state content or personal environment fact may enter reports or committed fixtures.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-032-provider-renderers.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-032-provider-renderers.md"
}
-->
