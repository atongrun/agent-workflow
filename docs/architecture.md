# Architecture

Agent Workflow is an installed, cross-platform workflow product for executing an approved
repository Plan through a serial Architect -> Coder -> Reviewer -> CI -> merge loop. The
[`constitution.md`](../constitution.md) remains normative; this document describes the current
unreleased RC.2 implementation boundary.

## Product boundary

```text
Human approval
      |
initiating Agent -> MCP application facade -> PlanRun
                                           -> Architect semantic output
                                           -> trusted TaskCard assembly
                                           -> Coder isolated workspace
                                           -> Reviewer exact-head decision
                                           -> trusted CI/merge
                                           -> fresh main / next card / completion

platform-local machine binding -> managed role listeners -> Agent Bus transport
```

The application facade owns the small Agent-facing capability surface: start, status, doctor,
stop, deinitialize, continue after exact Human approval, and authorize one legal replacement. The
CLI remains the operator/debugging surface over the same installed package. MCP is a thin stdio
adapter, not a second workflow engine.

Agent Bus transports events and owns transport ACKs. It does not own PlanRun state, provider
success, replacement authority, Git provenance, review decisions, or merge truth. AWF never exposes
ACK, requeue, replay, or wildcard cleanup as product actions.

## Truth and configuration

Repository truth contains the approved Markdown Plan, generated TaskCards, implementation/review
artifacts, and Git/PR history. The tracked credential-free `.awf/project.yaml` describes project
topology. A platform-local machine binding selects exact generated role profiles, workspaces,
state root, lifecycle manager, tools, models, remotes, and the local `dispatch.env` path.

Credentials remain only in the owner-protected local configuration consumed by the listener and
preflight boundary. They are not copied into tracked topology, provider prompts, TaskCards, run
facts, or evidence.

## Provider and role composition

RC.2 composes three Provider Drivers (Pi, OpenCode, Codex) with three Role Policies (Architect,
Coder, Reviewer), covering all nine cells without nine separate workflow implementations.

- Architect is read-only and returns one closed semantic object or closed milestone decision.
- Coder receives one frozen TaskCard in an isolated writable workspace without trusted GitHub merge
  authority.
- Reviewer inspects one exact pushed head read-only and returns a strict review result.

Trusted AWF code renders argv/stdin/file inputs, strips credentials from model environments, and
hash-binds every invocation. Pi disables sessions, extensions, skills, prompt templates, and context
files. OpenCode runs through its direct non-interactive CLI surface with the same closed input/output
contract. Codex uses its explicit read-only or workspace-write sandbox.

## TaskCard boundary

All Architect providers produce the same closed semantic payload. Trusted assembly injects the
Task ID, exact `agent/<TASK_ID>` branch, frozen main, provider selections, report paths, and one
`awf-postflight` contract before create-only persistence.

Generated TaskCards are one independently reviewable and mergeable change. They are created only
after the preceding card reaches trusted merge and fresh-main observation; AWF does not pre-generate
a queue. Shared conformance fixtures require the early persistence, manifest, Plan binding,
selection, and runtime artifact readers to agree on every field they own. Historical TaskCards keep
their documented legacy selection and branch compatibility, but new generated authority is strict.

## State and failure semantics

PlanRun, invocation, delivery, completed-card, process, lease, profile, workspace, and Git/PR facts
remain separate identities. Provider exit zero is not artifact validity, handler success is not a
transport ACK, and queue depth is not workflow completion.

Unknown or ambiguous outcomes fail closed. Architect failures and invalid output are never replayed.
A Coder replacement requires exact old-delivery/process/checkpoint evidence and creates a fresh
delivery; it never resends or rewrites the old event. Architect and Reviewer failures remain
non-replayable. Human approval continuation requires fresh observation of the exact protected
branch state.

## Native lifecycle

Generated profiles use platform-native managed lifecycle: launchd on macOS, systemd user units on
Linux, and zero-popup Task Scheduler reconciliation on Windows. Stop and deinit bind the exact
profile, installation, launch, process, lease, workspace, repository, and state root. They never use
wildcard process termination or operate on the Windows Schedule service itself.

Disposable acceptance closeout removes exact generated tasks, profiles, workspaces, installations,
processes, leases, and machine bindings while retaining run, event, listener-log, and failure
evidence.

## Design principles

1. Stabilize only transition-critical contracts demonstrated by real use.
2. Keep provider processes outside trusted workflow, credential, Git, and merge authority.
3. Bind every mutable effect to exact immutable facts and observe its result before continuing.
4. Preserve failures; never manufacture a green result through replay or retrospective evidence.
5. Prefer one serial product loop and the smallest repair for a demonstrated Golden Path blocker.
