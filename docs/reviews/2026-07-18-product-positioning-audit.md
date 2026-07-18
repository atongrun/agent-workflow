# Product Positioning and Repository Truth Audit

**Audit date:** 2026-07-18
**Audited base:** `main` / `origin/main` at `19d8c4470f19786170f631cbc2c1f55b1b731174`
**Change branch:** `codex/product-positioning-capacity-isolation`

This report is the ImplementationReport for the product-positioning phase. Git refs, GitHub PR
metadata, repository files, tests, and versioned evidence were checked directly; old chat state was
not treated as current truth.

## Repository Truth

- The main checkout was clean and matched freshly fetched `origin/main` before the branch was
  created.
- GitHub PR #1 through PR #10 were merged. There were no open or closed-unmerged PRs at audit time.
- The core implementation is a stateless validation CLI with `version`, `validate`, and `inspect`.
  It does not implement `init`, `status`, `next`, `submit`, model execution, or Workflow progression.
- `scripts/` is a separate operations dogfood surface. It is real and tested, but it is not the
  Workflow core.
- The current Reviewer maps successful tool completion to a placeholder and cannot safely route a
  semantic ReviewReport. The complete cross-machine loop is therefore not finished.

Refresh remote refs and PR state before relying on this snapshot in a later task.

## Branch and Worktree Classification

| Ref/worktree | Relationship to audited main | Classification | Action |
|---|---|---|---|
| `main`, `origin/main` | identical at `19d8c44` | authoritative starting point | branch from this ref |
| `codex/windows-python312-utf8` | 10 commits behind, 1 unique commit; adds the original portability TaskCard | preserved event-49 failure evidence | keep untouched |
| `codex/windows-python312-utf8-rerun` | 7 commits behind, 1 unique commit; adds the rerun TaskCard | preserved event-50 failure evidence | keep untouched |
| detached postflight self-test worktree | historical detached commit with uncommitted work | dirty preservation case | audit separately; do not clean here |
| `codex/product-positioning-capacity-isolation` | created from audited main | current documentation/contract branch | review, verify, PR |

The two UTF-8 branches contain unique evidence TaskCards, not newer product direction or a
merge-ready implementation. No branch or worktree was deleted, reset, cleaned, or repurposed.

## Problems in the Previous Positioning

- It described a portable method but did not explicitly state which scarce resource the downstream
  product protects.
- It risked treating total-token reduction or fewer model calls as the goal.
- It did not distinguish infrastructure development from downstream operation.
- Historical ADRs and `docs/later/` still described removed control planes, engines, ports, and
  adapters.
- TaskCard and AI Memory were both documented, but Repository Truth / Run Context / upstream-memory
  boundaries were not explicit.
- Reviewer verdict vocabulary conflicted between the template and the operations TaskCard.
- The reviewer-routing TaskCard pinned the pre-PR-10 baseline.
- `HANDOFF.md`, contributor instructions, and a client guidance file contained stale runtime/status
  language.

## Formal Product Position

Agent Workflow is a **model-agnostic development method, structured handoff protocol, and
verifiable process contract**. Its stable core defines Role/Stage authority, Artifact contracts,
transition semantics, deterministic rework, blocked/escalation/completion rules, and forced
convergence.

It helps downstream projects concentrate high-value-model capacity on architecture, difficult
judgment, genuine escalation, and Phase/Milestone acceptance while lower-cost models perform
frequent bounded planning, execution, testing, first-line review, and deterministic rework.

It is not a model, coding agent, generic multi-agent framework, arbitrary DAG engine, transport,
long-term memory system, hosted SaaS, or runtime.

## Canonical Terms

- **high-value model** — stronger for the decision at hand, but expensive or capacity-limited;
- **lower-cost model** — suitable for frequent bounded work;
- **execution model** — the model assigned to an Executor/Tester/first-line Reviewer role.

These terms are vendor-neutral, describe capability/capacity rather than marketing tiers, and allow
the same model to move between roles as economics and capability change.

## Operating Modes

- **Infrastructure development:** reliability, fail-closed behavior, recoverability, strong review,
  and real-environment evidence are the metrics. High-value models may be used freely.
- **Downstream operation:** measure completed TaskCards and how often/why high-value capacity is
  required. Normal deterministic work should stay in the lower-cost chain.

## Information and System Boundaries

- **TaskCard:** self-contained current-task execution context.
- **Repository Truth:** versioned code, project rules, plans, TaskCards, reports, decisions, tests,
  and PR evidence.
- **Run Context:** current Stage, Artifact, role, branch/commit/PR, failure, retry, and escalation.
- **AI Memory:** long-term, private, historical, preference, recovery, and cross-project knowledge.
- **Agent Bus:** endpoint/identity plus delivery, ACK, retry, and failure propagation; no Workflow
  semantic interpretation.

An Architect/Planner may read AI Memory and compress required facts into a TaskCard. A fresh-session
Executor starts from the TaskCard, repository, project `AGENTS.md`, and listed inputs; it does not
search memory for missing requirements.

## Normal and Escalation Paths

Normal path:

```text
Planner / task generator → Executor → deterministic verification → first-line Reviewer
→ PASS or deterministic REQUEST_CHANGES → next TaskCard
```

High-value escalation is limited to fundamental ambiguity, architecture reopen, genuine `BLOCKED`,
exhausted bounded rework, predefined high risk, changed goal, insufficient evidence, or
Phase/Milestone acceptance. Ordinary test/acceptance failure, allowed-path violation, missing
report, normal `REQUEST_CHANGES`, style, and optional optimization stay in the lower-cost chain.

## Operations Evidence

### Proven

- exact remote branch/commit synchronization before execution;
- model credential stripping and non-interactive stdin boundaries;
- required ImplementationReport gate;
- frozen postflight contract, test rerun, path/artifact/secret/diff checks;
- commit/push plus refreshed remote-SHA equality before review handoff;
- coder-to-reviewer send failure prevents success;
- durable handler lifecycle evidence outside the checkout;
- real Windows no-code handler return followed by Agent Bus ACK only after handler success.

### Not yet proven as one complete loop

- structured ReviewReport production and validation;
- semantic `PASS`, deterministic `REQUEST_CHANGES`, and `BLOCKED` routing;
- verdict-dependent downstream send failure preserving the no-ACK boundary;
- semantic review through decision and merge;
- generation/dispatch of the next TaskCard;
- three-OS service install/reboot/crash-recovery/unattended acceptance.

A dispatch script also retains a best-effort push warning path; remote dispatch safety should be
reviewed with the refreshed reviewer-routing task rather than generalized in this documentation
phase.

## Product Metrics and First Gate

Infrastructure metrics do not include a mandatory reduction in high-value-model calls. Downstream
metrics record completed TaskCards, high-value invocations per TaskCard, high-value-free rate, role
distribution, escalation reasons, lower-cost invocations, deterministic rework, human intervention,
and Phase/Milestone calls.

First-run suggestions—not permanent quotas—are at least three real downstream TaskCards, at least
two with no high-value invocation, and no high-value call on ordinary `PASS` / deterministic
`REQUEST_CHANGES` paths. Exact token/cost data is optional and recorded only when reliably exposed.

## Files and Scope

This phase updates product, method, boundary, metrics, handoff, example, and Role/Artifact contract
documents. The only schema change recognizes `ArchitectureRecord` and `PhasePlan`; their content
remains template-defined during dogfood. No Python, operations script, Agent Bus protocol, AI Memory
interface, remote machine, service, runtime, or Agent Host code was changed.

## Independent Review and Verification

Local CI-equivalent verification after the contract/schema changes:

- `ruff check .` — passed;
- `ruff format --check .` — passed;
- `python -m pytest -v` — 129 passed;
- resource validation — 6/6 roles, 4/4 workflows, 3/3 examples passed;
- `awf inspect workflows/feature-delivery.yaml` — passed;
- `python -m compileall -q src scripts tests` — passed;
- `git diff --check` — passed;
- repository-local Markdown link scan — passed.

The tests ran under Python 3.12 because the local venv's removed Python 3.11 interpreter
made that old environment unusable. The project supports Python 3.11+, and PR CI runs the same suite
under Python 3.11.

An independent `code-reviewer` reviewed 33 changed/new files against the full request and returned
`REQUEST CHANGES` with no CRITICAL or HIGH findings and three MEDIUM consistency findings:

1. default Workflow descriptions did not distinguish deterministic Reviewer `REQUEST_CHANGES` from
   `BLOCKED` escalation;
2. this ImplementationReport still had an independent-review placeholder;
3. `CONTRIBUTING.md` retained stale Phase 0 language.

All three were fixed. Workflow contracts now label review `onFailure` as deterministic
`REQUEST_CHANGES` only and route `BLOCKED` outside the normal rework path; this report contains the
review outcome; contributor guidance is phase-neutral. Final verification was rerun after rework.
The independent re-review covered the five affected files, found no remaining issues or regressions,
and returned `APPROVE`.

## Remaining Product Questions

- Which downstream project will provide the first comparable multi-TaskCard baseline?
- After repeated use, which stateless render/validation helpers are genuinely needed?
- Do any dogfood operations conveniences warrant a supported surface outside the stable core?

These questions do not authorize Agent Host, Plugin SDK, generic runtime, or adapter design now.

## Recommended Next TaskCard

After this branch merges, regenerate **Fail-closed reviewer verdict routing** from the new
`origin/main` and keep its existing narrow operations scope. It is the smallest engineering task
that closes the known semantic handoff gap without changing Agent Bus or the Workflow core.

After that gate, the next product activity is a PhasePlan—not one oversized TaskCard—for the first
real downstream capacity-isolation run: at least three bounded TaskCards with the metrics above.
