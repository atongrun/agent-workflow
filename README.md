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
handler-return/ACK gate over Agent Bus. The trusted reviewer now validates structured `PASS`,
deterministic `REQUEST_CHANGES`, and `BLOCKED` reports, embeds the normalized report in its verdict
event, selects exactly one route, and fails closed before ACK when report validation or delivery
fails. These semantics are proven at the deterministic-test level, not yet by a fresh live
cross-machine run. Windows Python 3.12 default-locale portability is also closed with a trusted full
suite. These capabilities remain outside the stable core.

The remaining gaps are a fresh real-machine acceptance of the complete semantic loop, recorded
capacity-isolation metrics from that run, and the first non-infrastructure downstream dogfood. See
the [reviewer-routing implementation report](docs/tasks/reviewer-verdict-routing-implementation-report.md),
the [Windows portability report](docs/tasks/windows-python312-utf8-closeout-v7-implementation-report.md),
and the current [repository handoff](HANDOFF.md).

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
| 2 | Semantic reviewer routing and live operations proof | Deterministic routing complete; live acceptance and metrics pending |
| 3 | First downstream capacity-isolation dogfood | Next product gate |
| Later | Evidence-driven helpers and possible external runtime integration | Deferred |

See [`ROADMAP.md`](ROADMAP.md) for acceptance details.

## License

MIT — see [`LICENSE`](LICENSE).
