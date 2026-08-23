# Agent Workflow

**A model-agnostic development method, structured handoff protocol, and verifiable process contract for AI-assisted software projects.**

Agent Workflow concentrates architecture, difficult judgment, explicit escalation, and milestone
acceptance in **high-value models** while **lower-cost models** handle frequent, bounded execution,
testing, first-line review, and deterministic rework. The product optimizes a downstream project's
continuing dependence on scarce high-value-model capacity—not total model calls or total tokens.

The normative method lives in [`constitution.md`](constitution.md). The current implementation
combines those validation contracts with a bounded operations product path that invokes configured
Agent Tools from an exact committed Plan while keeping Git, review, merge and transport authority in
trusted code.

Binary distribution remains unsupported: the completed CI-only feasibility study returned
`NO_GO_PRODUCTION_BINARY`, not an installer or release format. All three candidates failed the
installed-Python interpreter re-entry acceptance bar on the five-target matrix; see the
[P2 TaskCard](docs/tasks/binary-distribution-feasibility.md) and
[feasibility report](docs/tasks/binary-distribution-feasibility-report.md). The follow-up
[release-readiness report](docs/tasks/binary-release-readiness-report.md) derives four technical
blockers from the raw 15-cell evidence and recommends testing a native launcher with a relocatable
real CPython runtime and installed AWF application. That shape is not an adopted production ABI;
Agent Bus remains independently distributed.

## Two Operating Modes

### Infrastructure development

Agent Workflow, Agent Bus, AI Memory, and future critical infrastructure may use high-value models
freely for architecture, implementation, safety review, failure analysis, and real-environment
validation. Reducing high-value-model use while building this infrastructure is not a product goal;
reliability, recoverability, and evidence quality are.

### Downstream operation

For projects developed under the method, the normal path keeps frequent work in the lower-cost
execution chain:

```text
Planner / task generator
→ Executor
→ deterministic verification
→ first-line Reviewer
→ PASS or deterministic rework
→ next TaskCard
```

A high-value model enters at named escalation points: fundamental ambiguity, frozen-architecture
reopen, genuine `BLOCKED`, exhausted bounded rework, predefined high-risk change, insufficient
evidence, changed project goal, or Phase/Milestone acceptance. Ordinary test failures, missing
reports, allowed-path violations, `REQUEST_CHANGES`, style preferences, and optional improvements
stay in the lower-cost chain.

The generic terms **high-value model** and **lower-cost model** describe the capacity and role, not a
vendor. A high-value model has stronger relevant capability but is expensive or capacity-limited; a
lower-cost model is suitable for frequent, bounded work. The same model may occupy different roles
as capabilities and constraints change.

## Stable Core

Agent Workflow defines:

- the development method and forced-convergence rules;
- Role responsibilities and authority boundaries;
- Stage and transition semantics;
- versioned Artifact contracts;
- `rework`, `blocked`, `escalation`, and `completion` rules.

It is not an LLM, coding agent, general multi-agent framework, arbitrary DAG engine, cross-machine
transport, long-term memory system, hosted SaaS, or model runner. Model invocation, process
supervision, scheduling, and inner agent loops belong to external runtimes.

## Information Boundaries

| Layer | Owns | Does not own |
|---|---|---|
| Repository Truth | Versioned code, project rules, plans, TaskCards, reports, decisions, tests, and PR evidence | Private machine facts or transient run status |
| Run Context | Current Stage, Artifact, branch/commit/PR, role, retry, failure, and escalation state | Long-term knowledge or hidden transition rules |
| TaskCard | Self-contained execution context for one current task | A copy of all long-term memory |
| AI Memory | Long-term background, decision history, private environment facts, preferences, and cross-project knowledge | Versioned task evidence or the authority to choose the next Stage |

A fresh-session Executor must be able to start from the TaskCard, repository, project `AGENTS.md`,
and explicitly listed inputs. A Planner or Architect may read AI Memory and compress only the facts
required for this task into the TaskCard. Required execution facts belong in auditable Artifacts;
long-lived explanation and private context stay in AI Memory.

## Related Infrastructure

- **Agent Bus** transports cross-machine events and owns endpoint/agent identity, delivery, ACK,
  retry, and failure propagation. It does not interpret Workflow Stages, Review verdicts, or task
  completion.
- **AI Memory** preserves long-term and private context. It is a potential upstream knowledge
  source for planning, not a mandatory dependency of every Executor.
- The installed operations surface composes Agent Workflow and Agent Bus for the bounded Plan happy
  path. It still defines no generic Agent Host, Plugin SDK, scheduler, TaskCard queue or remote
  supervisor.

## Current Implementation and Dogfood Surface

The repository ships markdown/YAML contracts plus `awf`. Validation and inspection commands remain
read-only. The Agent-facing committed-Plan start is different: it invokes the configured Pi
Architect fresh, then owns a strictly serial one-card or milestone loop through existing trusted
operations.

`scripts/` is a separate **operations surface** produced by real dogfood. It has demonstrated exact
checkout synchronization, trusted model-process boundaries, postflight verification, allowed-path
and secret gates, commit/push plus remote-SHA proof, durable handler evidence, and a real Windows
handler-return/ACK gate over Agent Bus. Dispatch also fails before event delivery when its TaskCard
branch cannot be pushed, so a remote executor is never pointed at an unavailable commit. The
Windows handoff check parses ACL principals independently from the echoed `C:\Users\...` target
path, preserving fail-closed owner-only enforcement without path-based false failures. The trusted
operations entry points also add the configured Bus host to `NO_PROXY`, so private Tailscale
traffic cannot be diverted through a desktop HTTP proxy. OpenCode coder and fallback reviewer
subprocesses run in fresh event-scoped clones with no remotes or source-checkout path in their
ordinary runtime context. A read-only Git command shim, stripped credential channels, denied Git
protocols, and hooks block the observed prompt-violating commit/push class in depth. Credential-free
proxy settings remain available for inference, while authenticated proxy URLs fail before model
launch instead of exposing their userinfo. After the model returns, the trusted runner verifies
both workspaces and the real remote ref, runs postflight in the isolated clone, force-includes the
configured report even when its directory is ignored, imports the exact tree delta, and retains the
only normal credentialed commit/push path. Reviewers accept only ImplementationReports tracked by
the dispatched commit. This is not an adversarial same-user OS sandbox; hostile arbitrary code still
requires a separate uncredentialed principal or network isolation. The trusted reviewer
now validates structured `PASS`,
deterministic `REQUEST_CHANGES`, and `BLOCKED` reports, embeds the normalized report in its verdict
event, selects exactly one route, and fails closed before ACK when report validation or delivery
fails. A fresh 2026-07-26 run completed one uninterrupted Mac architect → Windows coder → Mac
reviewer → architect `PASS` route with trusted postflight, commit/push, remote-SHA, durable handler,
and ACK evidence. Windows Python 3.12 default-locale portability is also closed with a trusted full
suite. These capabilities remain outside the stable core.

The first non-infrastructure downstream dogfood later completed three serial TaskCards. Phase 5 then
closed an Agent-facing committed-Plan path and a real two-card Architect-led milestone: Pi created
each card only after exact current facts, Card 2 bound freshly observed main containing Card 1, and
AWF completed both PR/CI/merge facts before exact `MILESTONE_COMPLETE`. The remaining measurement gap
is a prospectively instrumented high-value-model-led baseline. See
the [reviewer-routing implementation report](docs/tasks/reviewer-verdict-routing-implementation-report.md),
the [live semantic-loop report](docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md),
the [three-card acceptance report](docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md),
the [Windows portability report](docs/tasks/windows-python312-utf8-closeout-v7-implementation-report.md),
the [executor Git-boundary report](docs/tasks/executor-git-write-guard-implementation-report.md),
and the current [repository handoff](HANDOFF.md).

The operations surface now persists a versioned run ledger and bounded context packet outside
checkouts. `python scripts/awf_control_plane.py recover --run-id <id>` is the fresh-session
recovery contract. Trusted listeners perform route, stage, attempt, rework, replay, and terminal
checks before starting a model; denials are durable and do not ACK or alter retained history. See
the [run control-plane report](docs/tasks/run-control-plane-implementation-report.md) and the
example [authority manifest](scripts/authority-manifest.example.json).

The default operations route is also fork/PR-aware. Trusted local configuration separates a
read-only upstream remote from a writable contribution fork; contributor machines do not need
upstream write permission. The runner alone pushes the verified commit, creates or reuses the PR,
and binds the reviewer to an exact, persisted upstream/base and fork/head/PR provenance tuple.
Only canonical credential-free GitHub HTTPS remotes are accepted, and model workspaces still have
no remote or publishing credentials. See the
[fork/PR implementation report](docs/tasks/fork-pr-trusted-runner-implementation-report.md).
A post-merge Mac/Windows proof confirmed contributor-fork publication and exact-PR-head review;
the [live-proof closeout](docs/tasks/fork-pr-live-proof-closeout-20260729.md) records the evidence
and the exact PR-number recovery fix found during that run.

The v3 coder and reviewer additionally persist role-specific monotonic
[phase checkpoint](docs/tasks/durable-phase-checkpoint-recovery-implementation-report.md) before
model invocation and after their verified model, artifact, publication/provenance, and outbox
boundaries. Duplicate deliveries resume from the last trusted boundary; an ambiguous model
invocation is never repeated. A retained Windows-to-Mac proof recovered the same coder and reviewer
deliveries, routed a structured PASS, and completed architect ACK without repeating either model.
For v3 `REQUEST_CHANGES`, the coder reuses the initial coder-owned durable workspace only after the
same RunLedger identifies one unique authorized implement delivery and its completed checkpoint
matches the exact current PR tuple, trusted implementation commit/tree, and credential-free Git
manifest. Trusted code advances that same no-remote workspace after commit creation; immutable
invocation identity remains bound to the original delivery/source commit. Agent Bus carries no
workspace path or new lineage payload, and any lineage or Git drift fails before rework provider
invocation.
For every metadata-complete v1-v3 coder or reviewer delivery, the effective listener `tool` and
`model` must also match the selection already bound into the canonical payload hash. Mismatches fail
before control-plane authorization, recovery/outbox work, model invocation, or inbox completion;
legacy direct handlers without delivery metadata retain their environment overrides.
Reviewer execution currently accepts Codex, OpenCode, and a narrow Pi reviewer adapter. Pi runs
with read-only tools and returns the ReviewReport on stdout; the trusted runner writes that stdout
to the requested ReviewReport path only after a successful Pi exit. `dispatch.env` may set
`AWF_PI_BIN` when the `pi` executable is not on `PATH`.

Mixed-role runs freeze both selections in the owner RunManifest and in one machine-readable
`awf-reviewer-selection` JSON comment in the TaskCard. Dispatch rejects any disagreement before
Git or Agent Bus mutation. The exact TaskCard commit is already delivery-hash-bound; coder and
reviewer handlers re-read it after trusted checkout and fail before model invocation on role
selection drift. Coder handoff uses the frozen reviewer pair, while `REQUEST_CHANGES` returns to
the frozen coder pair. Cards without the block keep the legacy same-tool selection and v3 payload
shape.

The operations surface also has one strict, cross-platform Python
[configuration loader](docs/tasks/config-recovery-maturity-implementation-report.md). Bootstrap,
handoff checks, listeners, dispatch, and native service entry points share the same data-only
parser. Production wrappers no longer source `dispatch.env`, and the Windows service no longer
depends on Git Bash. CI exercises the recovery/configuration suite on Linux and Windows. The
separate live product gate also completed on 2026-08-09: three serial Dousansi TaskCards reached
trusted implementation, structured Pi review, PR, green CI, architect terminal ACK, merge, and
empty queues. See the
[three-card acceptance report](docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md).
Production wheels include this operations surface under the installed `agent_workflow` package:
listener/role/dispatch/preflight/config/service modules, agent adapters, model Git guards, service
templates, the default authority manifest, and artifact templates. The `awf` entry point resolves
those packaged resources first and falls back to the repository directories only in a source or
editable checkout. An installed `awf` therefore does not need an Agent Workflow source checkout.
CI builds a wheel and proves the resource/import boundary from a fresh virtual environment and an
unrelated working directory on Linux, Windows, and macOS.
The architect listener also consumes validated `PASS` and `BLOCKED` terminal decisions
deterministically, so a successful route can reach automatic ACK and pending-empty without a manual
terminal handler. Terminal verification now runs in a fresh event-scoped, no-remote workspace:
the configured source checkout supplies only validated remote bindings and is never fetched,
checked out, stashed, cleaned, or overwritten. Dirty operator files therefore cannot spend a
healthy terminal delivery's retry budget.

Every listener also completes a pre-Bus ownership gate. Coder and reviewer roles require a
dedicated clean Git root; architect may use a dirty source checkout because its terminal work is
isolated. A per-user listener lease rejects duplicate role PIDs and cross-role repository sharing
before any event can reach a handler. Local `Ctrl-C` stops with exit code 130, removes the matching
lease, and does not require a `control:shutdown` event.

TaskCard dispatch is native Python on every supported host:
`python scripts/awf_dispatch.py ...`. The retained `scripts/awf-dispatch.sh` file is a small POSIX
compatibility shim only; Windows dispatch, listeners, bootstrap, and services require neither Git
Bash nor WSL. Windows dispatch also requires a native Agent Bus executable rather than a `.cmd` or
`.bat` wrapper, keeping task-controlled payload bytes outside `cmd.exe`.

All local production commands now cross one
[runtime executor](docs/runtime-execution-architecture.md). PowerShell, Git Bash, and macOS zsh are
supported launch environments, while business code always supplies structured argv and never
invokes a shell directly. Runtime detection, Git Bash executable-path normalization, closed stdin,
Windows wrapper policy, redacted failure diagnostics, and timeout handling are enforced centrally
and protected by an AST boundary test.

Listener handlers now keep that boundary across Agent Bus as well. Agent Workflow emits the pinned
`awf.handler-argv.v1` token list as UTF-8 JSON through Bus `--on-argv`; role, rework, terminal and
Preflight paths no longer collapse executable paths, fixed flags or payload placeholders into a
command string. Deploy the compatible Bus consumer before this Workflow version; rollback Workflow
before Bus. An incompatible older Bus fails while parsing local listener arguments, before SSE
connection or event delivery.

Every new loop can now begin with the versioned, fail-closed
[runtime Preflight](docs/runtime-preflight-architecture.md):
`python scripts/awf_preflight.py fast --repo <repo> --model-tool <cli>` on model-executing
runtimes, or `python scripts/awf_preflight.py fast --repo <repo> --source-role architect
--model-tool-policy not-applicable` on a non-model architect runtime. The two model-tool options
are mutually exclusive, and coder/reviewer cannot use the exception. Fast mode is read-only and separates
TaskCard-authoring readiness from remote-dispatch authority. Explicit Deep mode is required only
for a first remote dispatch, a material runtime/transport change or failure, or an expired proof;
it uses disposable no-model control events and automatic handler-success ACK evidence without
reading or mutating historical events. If the initiating command times out but its exact result
arrives later, `awf preflight resume-deep --probe-id <probe-id> ...` revalidates
the durable result, current fingerprint, and zero queues without sending or altering a delivery.
`scripts/awf_handoff_check.py` remains the legacy human
checklist entry and now renders the Fast report. Role listeners opt into the disposable control
route with `--enable-preflight`.

## Normal Product Journey

Agent Workflow assumes Agent Bus, GitHub CLI and each selected Agent Tool are already
installed/authenticated/configured. Normal human UX is setup, passive observation and safe stop;
the committed-Plan start is an Agent-facing capability:

```bash
awf init
awf status --explain
awf stop

# Called by an initiating Agent after explicit Human authorization:
awf plan start --plan docs/plans/<plan>.md --one-card
awf plan start --plan docs/plans/<plan>.md --milestone
```

Init checks Git/authenticated GitHub CLI, resolves the configured Agent Bus executable, proves
`agent-bus.listen.on-argv.v1`, and version-probes the installed OpenCode/Pi/Codex tools without
starting a model or running Deep. After the complete role plan validates, init installs/reconciles
and starts one local managed listener per selected RoleBinding, registers the existing Preflight
handlers, and prints Ready only after exact process/profile/lease plus Agent Bus connected evidence.
It recommends only implemented bindings: Pi Architect, OpenCode Coder, and OpenCode/Pi/Codex
Reviewer. Enter accepts defaults; Customize permits any current-machine role subset and per-role
tool/model selection.

Each role gets a deterministic credential-free profile and a separate exact local checkout. One
OpenCode installation may serve Coder and Reviewer; using the same explicit model is legal and
produces only an informational independence note. `.awf/machine.json` binds exact local profiles,
digests, workspaces and selection facts but is not Workflow authority.

Model selection is `tool-default` or one opaque Agent Tool-native reference. Tool-default leaves the
profile `model` empty and renders no model override. An explicit value such as
`opencode-go/deepseek-v4-flash` is passed unchanged to the selected tool. AWF does not inspect or
mutate the tool's provider/auth/default configuration, query remote model catalogs, or silently
fall back.

Finding is off unless `awf init --finding-enabled` explicitly creates maintainer profiles. Off means
no Finding prompt/capture or Feedback block in normal status; existing `awf feedback ...` remains
available independently.

`awf plan start` compiles the exact tracked Plan/main/blob and configured Pi Architect binding,
records a minimal PlanRun, runs existing Fast/Deep internally, and returns after durable Agent Bus
start. A Human does not author the TaskCard. AWF asks Pi for one card, reuses the established
Coder/Reviewer/Git/PR/merge path, observes fresh upstream main after every merge, and only then asks
Pi for the next card or exact milestone completion.

`awf status` is passive: it displays local roles, listener/workspace/queue observations, PlanRun,
current/last card, recorded Fast/Deep, PR/merge/completion and the first blocker. It never runs
doctor, Preflight, logs or resume. `awf stop` records no-new-work, observes every selected queue,
refuses unsafe pending authority, then exact-stops only the selected local listeners.

`awf enroll` retains the earlier TaskCard-bound coder/reviewer profile + RunManifest/compiler flow;
`awf init --card ...` is its compatibility path. Top-level `start`, raw `drain`, `node ...`,
`doctor`, `logs`, `resume`, upgrade and uninstall remain support/admin/recovery commands. They are
not the normal product journey and are not deleted in this release candidate.

Use `--role architect|coder|reviewer` on support lifecycle/status/log commands to operate one
binding. Public `awf run <TaskCard>` remains a compatibility/support surface, not the normal Human
journey.

The advanced surface remains available unchanged for compatibility and debugging:

```bash
awf setup --repo . --card <path-or-id> \
  --tool opencode --model <coder-model> \
  --reviewer-tool pi --reviewer-model <reviewer-model> \
  --state-root <host-local-state-root> \
  --profile coder=<profile-name-or-path> \
  --profile reviewer=<profile-name-or-path>
awf plan check --repo . --run-manifest .awf/run-manifest.json
awf run --repo . --card <path-or-id> --run-manifest .awf/run-manifest.json
awf status --run <run-id>
awf resume --run <run-id>
```

`awf setup` writes credential-free, owner-only `.awf/run-manifest.json` and
`.awf/run-contract.json`; secrets remain in the existing owner-only `dispatch.env`, and `.envrc`
is never written. The RunManifest persists the canonical state-root and exact coder/reviewer
profile references. The compiled report binds their resolved identities and the internal authority
input.
`awf plan check` is a read-only pre-operation compiler/linter. It resolves durable installed
profiles when available, keeps the owner RunManifest and internal authority-manifest classes
distinct, checks the frozen TaskCard plus ImplementationReport/ReviewReport allowlist, and emits an
`awf.run-contract-report.v1` with compiler provenance and mutual SHA-256 bindings. It does not
initialize a ledger, mutate Git, connect to Agent Bus, start a process, or dispatch an event.
`awf run` recompiles the current local graph, requires exact equality with the persisted report,
and binds its `contract_sha256` into the context packet before resolving Git HEAD or initializing a
ledger. Generic `--manifest` is rejected on setup/run in favor of the class-specific
`--run-manifest`; an older uncompiled manifest receives an explicit setup migration error. The
lower-level dispatch compatibility surface remains unchanged in this package. `dispatch.env`
remains limited to secrets and runtime binaries. The default run ID is
`task-<branch-task-suffix>`, matching
trusted listener recovery. Status labels unrecorded health/checkpoint/queue values
explicitly, and resume is fail-closed: it cannot replay a model, ACK, requeue,
or historical delivery.

Dogfood Findings use a separate best-effort operations path. A trusted coder/reviewer may extract
one bounded safe EOF Finding from its model Report and strip it before formal Report validation,
hashing, import, verdict, or business handoff. Operators inspect and explicitly flush this queue:

```bash
awf feedback status
awf feedback status --json
awf feedback flush --config ~/.config/awf/dispatch.env
```

The flush sends `feedback:awf-finding-v1` to the independent `awf-reporter` identity. Reporter
handlers invoke `awf feedback ingest --payload-json <payload>` and return success only after exact
occurrence dedupe and durable local commit. Feedback failures never delay or change the business
handler ACK. This Phase A path does not triage, group, publish, create GitHub issues, run a daemon,
or change Agent Bus Core. The bounded contract is in
[`docs/tasks/dogfood-finding-phase-a.md`](docs/tasks/dogfood-finding-phase-a.md).

An installed wheel exposes explicit session-bound and user-managed listener lifecycles:

```bash
awf node doctor --profile reviewer-mac
awf node doctor --profile reviewer-mac --json --ttl-seconds 3600
awf node start --profile reviewer-mac
awf node status --profile reviewer-mac
awf node status --profile reviewer-mac --run task-DOGFOOD-001 --json
awf node status --profile reviewer-mac --run task-DOGFOOD-001 --explain
awf node logs --profile reviewer-mac --lines 100
awf node stop --profile reviewer-mac
awf node install --profile coder-windows
awf node restart --profile coder-windows
awf node upgrade --profile coder-windows
awf node uninstall --profile coder-windows
```

The run-aware status projection names the first observed blocker, its owner and cause, whether a
model invocation is proven by the exact run's authorized delivery checkpoints, payload-blind event
metadata, and one legal next action. Feedback capture/outbox/flush facts remain separate from the
business terminal and ACK state. Status is read-only and never ACKs, requeues, recovers, dispatches,
flushes Feedback, or invokes a model.

```json
{
  "format": "awf.node-profile.v1",
  "name": "reviewer-mac",
  "role": "reviewer",
  "repo": "/absolute/path/to/dedicated-review-checkout",
  "tool": "pi",
  "model": "reviewer-model",
  "upstream_repo": "owner/project",
  "head_repo": "contributor/project",
  "state_root": "/absolute/path/to/host-local-awf-state"
}
```

Persistent user profiles add one secret-free lifecycle object:

```json
{
  "lifecycle": {
    "mode": "managed",
    "manager": "auto",
    "scope": "user"
  }
}
```

A named profile resolves to the platform config directory under `awf/profiles/<name>.json`; an
absolute JSON path is also accepted. The `awf.node-profile.v1` schema contains only non-secret
role, repository, tool, route, state, and log settings. `state_root` is required and is the sole
state source for a node-managed listener; direct script entry points retain an explicit
`--state-root` / `AWF_STATE_ROOT` / platform-default compatibility order. Tokens and the Bus URL remain exclusively
in owner-only `dispatch.env`. `doctor` checks the schema, role/tool boundary, strict credential
file, role-aware Git workspace, Bus health, and model executable before start; it does not replace
the existing Fast/Deep remote-dispatch proof. Profiles that omit `lifecycle` retain the local
`session` mode. Under SSH, session start is rejected unless `--allow-session-bound` makes the
temporary limitation explicit. `managed` mode renders the same complete profile into a launchd
user agent, lingering systemd user unit, or Windows Task Scheduler `InteractiveToken` task whose
target is `awf node reconcile`. The reconciler reads an atomic desired-state JSON record and runs
the unchanged foreground listener. Windows currently requires the same user to own the active local
console session; RDP-only and pre-login operation are outside this user-scope contract. The Windows
user remains the normal model/Git/config identity; no
service account, password, WinSW binary, or PowerShell setup is required. Agent Bus
`control:shutdown` remains the graceful remote stop, while `awf node stop` independently terminates
the exact bound local process tree. Windows durability was accepted only after a new SSH session
proved the manager, listener PID, launch identity, lease, queue consumption, crash recovery, and
clean local stop. The evidence matrix is recorded in the
[lifecycle implementation report](docs/tasks/windows-listener-service-lifecycle-implementation-report.md).

For `lifecycle.mode=managed`, `awf node install` validates the authoring profile and writes a
credential-free content-addressed snapshot under the platform AWF configuration directory.
Generated native definitions and the install record reference only that durable snapshot; the
authoring file is provenance and optional upgrade input, not runtime identity. `start`, `status`,
`logs`, `stop`, `restart`, `upgrade`, `uninstall`, and supervisor reconcile resolve the exact
installed binding after the source moves or disappears. Missing, malformed, ambiguous, or
digest-drifted bindings fail closed instead of scanning for a replacement. Changing name, role,
repository, state root, or lifecycle ownership requires uninstall/install rather than disguising a
new node identity as an upgrade.

`doctor --json` emits one credential-free `awf.node-readiness.v2` snapshot for operator discovery.
It binds the installed `awf`, profile, strict configuration, workspace, selected tool version, and
listener observation into a SHA-256 fingerprint and gives the observation a bounded reuse window.
The report has no umbrella `ready` state: `configured`, `installed`, `running`, `connected`, and
`dispatch_capable` are independent facts with explicit evidence status and one legal next action.
An architect may collect it with one remote command and reuse it across a short serial TaskCard
run while the listed invalidation conditions remain false. The snapshot is not written, sent over
Agent Bus, or accepted as dispatch authority. Missing, stale, or merely unexamined Fast/Deep
Preflight evidence never becomes dispatch authority.

Node status is read-only. It reports the same five lifecycle facts without performing doctor or
Preflight work, so configuration/connectivity may honestly remain unknown. It labels the source of listener/PID/lease, Git workspace, run-ledger,
delivery-checkpoint, Agent Bus pending, artifact, pull-request, and CI observations; unavailable
live facts remain `unknown`, `not_recorded`, or `not_requested`. Recorded and live PR/CI facts are
shown separately so drift stays visible. ReviewReport integrity also uses two explicit names:
`file_sha256` is the raw Markdown byte hash from a delivery checkpoint or live file, while
`canonical_report_sha256` is the normalized ReviewReport object hash recorded by the terminal
ledger. Status never ACKs, requeues, resumes, redispatches, or rewrites a ledger.

## Product Gate

**Use first, abstract second.** The first downstream product gate is complete: three bounded product
TaskCards closed across the managed Windows coder and Mac Pi reviewer without high-value model calls
inside their business delivery handlers. Exact surrounding planning/acceptance call counts and a
comparable prior baseline were not instrumented, so the project does not claim precise token or cost
savings. The next evidence gate is a second downstream phase and an honest baseline comparison, not
a generic engine or Agent Host abstraction. See
[`docs/product-metrics.md`](docs/product-metrics.md) and
[`docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md`](docs/tasks/dousansi-three-card-dogfood-acceptance-20260809.md).

## Validation Quick Start

Install the published release without an Agent Workflow source checkout:

```bash
python -m pip install \
  https://github.com/atongrun/agent-workflow/releases/download/v0.3.0/agent_workflow-0.3.0-py3-none-any.whl
awf version
```

For repository development and validation:

```bash
pip install -e ".[dev]"
ruff check .
ruff format --check .
python -m pytest -v
awf validate roles
awf validate workflows
awf validate examples
awf inspect workflows/feature-delivery.yaml
```

These development commands validate and inspect contracts; only the explicitly authorized
Agent-facing Plan start enters the managed product loop.

## Repository Structure

```text
constitution.md       normative development method
docs/                 product, architecture, ADR, lifecycle, and deferred-boundary docs
schemas/              Role, Workflow, and Artifact schemas
roles/                default role contracts
workflows/            example transition contracts
templates/artifacts/  handoff templates
examples/             bounded examples and dogfood inputs
src/agent_workflow/   stateless validation/inspection CLI
scripts/              non-core operations dogfood surface
tests/                validation and operations regression tests
```

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Method contract and validation CLI | Complete |
| 1 | Product-positioning and repository-truth convergence | Complete on `main` |
| 2 | Semantic reviewer routing and live operations proof | Complete |
| 3 | First downstream capacity-isolation dogfood | Three-card operational gate complete; baseline comparison pending |
| 4 | Evidence-driven hardening and second downstream phase | Next product gate |
| Later | Possible external runtime integration | Deferred |

See [`ROADMAP.md`](ROADMAP.md) for acceptance details.

## License

MIT — see [`LICENSE`](LICENSE).
