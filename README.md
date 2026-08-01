# Agent Workflow

**A model-agnostic development method, structured handoff protocol, and verifiable process contract for AI-assisted software projects.**

Agent Workflow concentrates architecture, difficult judgment, explicit escalation, and milestone
acceptance in **high-value models** while **lower-cost models** handle frequent, bounded execution,
testing, first-line review, and deterministic rework. The product optimizes a downstream project's
continuing dependence on scarce high-value-model capacity—not total model calls or total tokens.

The normative method lives in [`constitution.md`](constitution.md). The current implementation is a
thin, stateless `awf` CLI that validates Role, Workflow, and Artifact contracts.

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
- A future external runtime may combine Agent Workflow, Agent Bus, and AI Memory. Agent Workflow
  currently defines no Agent Host integration or Plugin SDK.

## Current Implementation and Dogfood Surface

The repository ships markdown/YAML contracts plus the validation-only `awf` CLI. It never runs a
model or advances a Workflow Run.

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

The remaining gaps are recorded capacity-isolation metrics from that run, automatic continuation
into a next TaskCard, and the first non-infrastructure downstream dogfood. See
the [reviewer-routing implementation report](docs/tasks/reviewer-verdict-routing-implementation-report.md),
the [live semantic-loop report](docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md),
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

The operations surface also has one strict, cross-platform Python
[configuration loader](docs/tasks/config-recovery-maturity-implementation-report.md). Bootstrap,
handoff checks, listeners, dispatch, and native service entry points share the same data-only
parser. Production wrappers no longer source `dispatch.env`, and the Windows service no longer
depends on Git Bash. CI exercises the recovery/configuration suite on Linux and Windows; this is
automated infrastructure evidence, not the separate three-card live dogfood gate.
The architect listener also consumes validated `PASS` and `BLOCKED` terminal decisions
deterministically, so a successful route can reach automatic ACK and pending-empty without a manual
terminal handler.

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

Every new loop can now begin with the versioned, fail-closed
[runtime Preflight](docs/runtime-preflight-architecture.md):
`python scripts/awf_preflight.py fast --repo <repo>`. Fast mode is read-only and separates
TaskCard-authoring readiness from remote-dispatch authority. Explicit Deep mode is required only
for a first remote dispatch, a material runtime/transport change or failure, or an expired proof;
it uses disposable no-model control events and automatic handler-success ACK evidence without
reading or mutating historical events. `scripts/awf_handoff_check.py` remains the legacy human
checklist entry and now renders the Fast report. Role listeners opt into the disposable control
route with `--enable-preflight`.

## Product Gate

**Use first, abstract second.** Technical transport success proves feasibility, not downstream
product value. Before expanding the core or building Agent Host integration, a real downstream
project must show that multiple bounded TaskCards can close with less frequent high-value-model
participation than the previous high-value-model-led baseline. See
[`docs/product-metrics.md`](docs/product-metrics.md) and
[`docs/development-workflow-mvp.md`](docs/development-workflow-mvp.md).

## Validation Quick Start

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

These commands validate and inspect contracts; they do not start or orchestrate a Workflow Run.

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
| 2 | Semantic reviewer routing and live operations proof | Live `PASS` route complete; metrics pending |
| 3 | First downstream capacity-isolation dogfood | Next product gate |
| Later | Evidence-driven helpers and possible external runtime integration | Deferred |

See [`ROADMAP.md`](ROADMAP.md) for acceptance details.

## License

MIT — see [`LICENSE`](LICENSE).
