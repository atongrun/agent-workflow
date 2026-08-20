# TaskCard: RTS-035 Selected Local Workflow Application

## Task ID

runtime-v2-rts-035-local-application

## Goal

Compose the accepted installed Runtime v2 contracts, checksummed atomic Store/journal, closed
provider renderers, isolated workspace/trusted import and Artifact validation APIs behind one narrow
local application boundary with the steady command shape `run/status/stop`.

This is a newly created disposable-state candidate only. It proves the selected Python package and
application ownership before any production adoption. Current
RunLedger/checkpoint/outbox/inbox/RunEvidence remains the sole production authority and recovery
path. RTS-035 must not read, convert, shadow or dual-write that state, replace the production CLI or
handler, operate Agent Bus or remote truth, change a default, migrate state or delete compatibility.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@6c46664de50b043007559e235fa496e7202c7771`
- **Task branch**: `codex/runtime-v2-rts-035-local-application`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 3 / RTS-035 successor seam
- **Frozen contract**: `docs/runtime-v2-semantic-contract.md`
- **Accepted decision**: `docs/adr/0006-runtime-v2-product-boundary-implementation-choice.md`
- **Passed prerequisites**: RTS-030 through RTS-034 installed contracts, atomic Store/journal,
  provider renderers, workspace/trusted import and Artifact validation seams

The package seams passed independently but have not yet been accepted as one application. The
existing RTS-020 Python experiment is comparison evidence only and cannot become a second
implementation or be imported by the installed package. The RTS-031 Store remains disposable and
must be the only writer for this candidate's Workflow authorization, journal, handoff, terminal and
local-stop facts.

## Frozen application boundary

### Commands and ownership

The installed candidate exposes exactly one application implementation with three operator-shaped
methods or commands:

- `run` accepts one immutable `RunSpec` plus exact local execution inputs, reopens or initializes
  the bound Store, and advances only the legal current Workflow action;
- `status` reconstructs a `RunSnapshot` from validated Store authority without writing, starting a
  provider, executing a reported action or consulting a derived cache; and
- `stop` records an exact run-bound local application stop only when no provider result is
  ambiguous. It never kills a process or claims native lifecycle evidence.

`run` may be called repeatedly to converge a complete disposable local path. It must re-read current
authority before every effect, skip an already durable provider result, and return the exact current
decision instead of hiding ambiguity. Internal Store/journal/path names do not enter the normal
command result.

The application is the only caller that composes Workflow Stage knowledge. Renderers, provider
process handles, workspace helpers, Artifact validators and status readers remain Stage-blind and
cannot mutate Workflow authority except through the exact Store/journal APIs already selected.

### Provider process boundary

RTS-035 may add only a narrow local process port needed to prove authorization-to-launch ordering:

1. `RunStore.authorize` durably binds the exact `InvocationSpec` digest before rendering or start.
2. The selected closed renderer returns a structured `RenderedInvocation`.
3. The journal durably records the exact rendered launch intent before a process start attempt.
4. A typed launcher starts structured argv with `shell=False`, applies only the bound environment
   and file/stdin inputs, and returns one exact process handle/identity.
5. The journal records process observation before waiting for the result, then records the exact
   return code and result digest.
6. Launch intent without a trusted result remains `AMBIGUOUS_NO_REPLAY`; neither `run` nor `stop`
   may invoke or kill a guessed process.

Focused tests use only a repository-owned scripted local provider in disposable workspaces. No
Codex/OpenCode/Pi network intelligence, credentials, user configuration or ambient provider state
is invoked. The existing OpenCode coder and Pi reviewer render shapes are exercised; no generic
provider registry, plugin framework or alternate renderer is added.

### Local validation, lineage and transitions

The application uses the passed workspace and Artifact APIs rather than copying their policy:

- every coder/rework invocation uses a fresh no-remote workspace at the exact trusted local commit;
- the immutable TaskCard contract supplies exact report paths, allowed paths and verification argv;
- provider exit zero is followed by ImplementationReport, verification, workspace-state,
  postflight, exact Artifact and trusted-import checks before one Store handoff intent;
- review uses the exact trusted workspace/input lineage, validates the normalized ReviewReport and
  records either PASS terminal, deterministic REQUEST_CHANGES handoff, or BLOCKED terminal;
- rework binds the exact prior implement/review lineage carried by the current Store and uses the
  remaining budget; a second review remains separately authorized; and
- validation/trusted effect plus handoff or terminal commits through the one Store writer. There is
  no transport send or ACK claim in this local boundary.

The focused application fixture must cover the complete legal paths:

1. implement -> review -> PASS -> completed;
2. implement -> review -> REQUEST_CHANGES -> rework -> review -> PASS -> completed; and
3. implement -> review -> BLOCKED -> blocked.

It must also execute all 14 machine rows in
`tests/fixtures/runtime_v2_shared_slice_cases.json` against the installed application, preserving
the normalized outcomes, prohibited effects and read-only/idempotent evidence. The fixture remains
read-only comparison input and is not rewritten by this card.

### Exact local application stop

The Store/port ABI may receive one minimal typed stop command/fact refinement because RTS-031 did
not freeze a Python ABI. The stop fact is inside the existing checksummed authority envelope and is
written by the same exact writer/lock; no second file or lifecycle representation is allowed.

- stop binds RunSpec digest, run ID, exact writer and current sequence;
- exact replay is idempotent and conflicting/stale identity denies without mutation;
- an invocation with launch intent/process observation but no durable result denies stop as
  ambiguous and preserves evidence;
- after a durable stop, new authorization, journal mutation, handoff and terminal mutation deny;
- status reports the stopped fact, owner/cause and one legal support action without mutation; and
- stop does not signal a PID, inspect process names, remove locks, alter business terminal or claim
  OS/native-manager success. Phase 4B still owns native exact process/incarnation stop.

## Frozen writable scope

- `docs/tasks/runtime-v2-rts-035-local-application.md`
- `src/agent_workflow/runtime/__init__.py`
- `src/agent_workflow/runtime/contracts.py`
- `src/agent_workflow/runtime/ports.py`
- `src/agent_workflow/runtime/store.py`
- `src/agent_workflow/runtime/application.py`
- `tests/fixtures/runtime_v2_local_application_provider.py`
- `tests/test_runtime_application.py`
- `tests/test_runtime_atomic_store.py`
- `tests/test_runtime_core_boundary.py`
- `tests/test_runtime_core_contracts.py`
- `tests/test_runtime_command_boundary.py`
- `.awf/artifacts/impl-report-runtime-v2-rts-035-local-application.md`
- `.awf/artifacts/review-report-runtime-v2-rts-035-local-application.md`

After implementation, exact-head CI and independent Gate Review PASS, owner closeout may add
`docs/tasks/runtime-v2-rts-035-local-application-implementation-report.md` and update only the
Phase 3 gate/next-step sections of the Runtime v2 plan, HANDOFF and ROADMAP.

## Out of scope

- Any production `scripts/`, CLI/facade/node/status/listener/service path, manifest/schema or
  existing Runtime authority representation.
- Reading, converting, importing, shadowing, dual-writing or deleting RunLedger/context packet,
  checkpoint, outbox, inbox, RunEvidence, profile/process/lease, Feedback or retained state.
- Agent Bus send/receive/retry/ACK, handler-success claim, remote Git/GitHub, PR/CI/merge, native
  lifecycle/process kill, cross-host adoption or external transaction claim.
- Production provider intelligence, credentials or ambient configuration; generic provider,
  adapter, validation, workspace, task or plugin framework.
- Scheduler, arbitrary DAG, physical Coordinator, daemon, leader election, distributed lock,
  SQLite, Rust/Go production Runtime or native launcher.
- Production adoption, representation migration, compatibility deletion, default switch, release,
  live/retained-event operation or destructive cleanup.
- Editing the Frozen semantic contract, ADR-0006, Phase 2 experiments or shared fault fixtures.

## Budgets and stop rules

- New installed `application.py`: at most 700 nonblank/noncomment lines.
- New focused application tests plus scripted provider: at most 1,100 nonblank/noncomment lines.
- Combined net nonblank/noncomment refinement in `contracts.py`, `ports.py` and `store.py`: at most
  180 lines; only exact local application stop and facts required by composition may be added.
- No new dependency; installed Runtime remains standard-library only.
- One application, one Store authority envelope/lock and one typed launcher implementation; no
  generic registry, alternate Store/application, background service or new persistent family.
- One candidate Gate Review and at most two L3 repair/focused re-review rounds.
- If the complete local fixture requires production/legacy dual write, a second authority graph,
  provider replay after ambiguity, remote/Bus/native claims, a generic framework or any budget
  breach, stop with `PLAN_CONFLICT` rather than widening scope.

## Acceptance criteria

- [ ] Task ID equals branch leaf; every changed path stays within frozen/closeout scope.
- [ ] One installed local application composes the passed RunSpec, Store/journal, renderer,
      workspace and Artifact APIs; no experiment or operations-script implementation is imported.
- [ ] `run/status/stop` is the complete normal candidate surface and does not expose Store path,
      checkpoint/outbox/inbox, profile or lease concepts.
- [ ] Authorization and exact InvocationSpec are durable before renderer/process start; launch
      intent precedes start; process observation precedes result; ambiguous launch never replays.
- [ ] Provider renderer remains pure and Stage-blind; structured argv uses no shell and only the
      exact bound environment/stdin/file inputs.
- [ ] Implement/review PASS, deterministic rework then second review PASS, and BLOCKED paths reach
      exact Store terminal outcomes with one logical writer and no transport/ACK claim.
- [ ] Artifact/report/path/hash/postflight and isolated-workspace/trusted-import policy is delegated
      to the passed installed APIs with no copied fallback body.
- [ ] Exact rework binds the prior implement/review identities and budget; drift, missing lineage,
      advisory-only findings and exhausted budget deny before provider or trusted mutation.
- [ ] All 14 shared machine rows preserve normalized outcome, legal next action and prohibited
      effects; status and identical replay leave every authority/external-observation byte stable.
- [ ] Exact local stop is Store-bound/idempotent, denies stale/conflicting/ambiguous identity and
      cannot signal/kill or alter business terminal; stopped authority denies later mutations.
- [ ] Missing/corrupt/foreign/rechecksummed authority, TaskCard/RunSpec/InvocationSpec/workspace/
      Artifact/result drift and partial local effects fail closed at the first legal boundary.
- [ ] No legacy state or second journal/stop/status authority file is read or written; derived
      status remains deletable/reconstructable and strictly read-only.
- [ ] Static boundary tests prove no Agent Bus, remote Git/GitHub, lifecycle, credentials, shell,
      scheduler/Coordinator, generic registry, migration, fallback or production CLI integration.
- [ ] LOC/dependency/single-implementation/representation budgets pass.
- [ ] Focused tests, full pytest/Ruff and ordinary Linux/Windows/macOS/installed-wheel CI pass on the
      candidate head; automatically triggered Binary Feasibility remains green comparison evidence.
- [ ] One independent TaskCard Gate Reviewer returns `PASS`; any L3 repair receives focused
      re-review by the same Reviewer.
- [ ] Closeout names exactly one later Phase 3/4 gate without claiming production adoption,
      representation migration, default, native lifecycle, launcher, release or deletion authority.

## Verification

- Local Mac: AST/static/import checks, direct disposable Git/scripted-process smoke, Store byte
  snapshots, scope/LOC/dependency audit and `git diff --check` only.
- CI: focused application/Store/Core tests plus full pytest/Ruff, installed-wheel and ordinary
  cross-platform jobs.
- Fault injection snapshots authority, trusted repo and provider-call evidence before denied/status/
  replay operations and asserts exact stability.
- Independent Review checks one logical writer, authorization/launch/result/effect order,
  no-replay ambiguity, rework lineage, terminal/stop identity, status purity, closed provider and
  external/production boundaries.

## Required output

- one installed disposable local Runtime application with `run/status/stop`;
- minimal typed local process and exact-stop facts with one Store writer;
- complete local PASS/rework/BLOCKED plus 14-row fault fixtures;
- ImplementationReport and independent ReviewReport;
- owner closeout naming exactly one later gate.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-035-local-application.md",
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/contracts.py",
    "src/agent_workflow/runtime/ports.py",
    "src/agent_workflow/runtime/store.py",
    "src/agent_workflow/runtime/application.py",
    "tests/fixtures/runtime_v2_local_application_provider.py",
    "tests/test_runtime_application.py",
    "tests/test_runtime_atomic_store.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_core_contracts.py",
    "tests/test_runtime_command_boundary.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-035-local-application.md",
    ".awf/artifacts/review-report-runtime-v2-rts-035-local-application.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "compileall", "-q", "src/agent_workflow/runtime", "tests/fixtures/runtime_v2_local_application_provider.py", "tests/test_runtime_application.py"],
    ["{python}", "-m", "pytest", "-q", "tests/test_runtime_application.py", "tests/test_runtime_atomic_store.py", "tests/test_runtime_core_boundary.py", "tests/test_runtime_core_contracts.py", "tests/test_runtime_command_boundary.py"],
    ["git", "diff", "--check"]
  ],
  "secrets_policy": "No credential, token, private URL, provider/business payload, retained-state content or personal environment fact may enter application fixtures or reports.",
  "implementation_report": ".awf/artifacts/impl-report-runtime-v2-rts-035-local-application.md",
  "review_report": ".awf/artifacts/review-report-runtime-v2-rts-035-local-application.md"
}
-->
