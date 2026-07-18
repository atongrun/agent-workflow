# AI Memory Boundary (Later External Composition)

> **Status: external and optional.** Agent Workflow ships no memory port or adapter. AI Memory is a
> potential upstream knowledge source for planning, not a mandatory dependency of every Stage.

## Ownership

AI Memory may preserve:

- long-term project background and historical decision explanation;
- user preferences and cross-project knowledge;
- private machine, environment, and deployment context that must not enter Git;
- recovery context across long interruptions or sessions.

AI Memory does not replace:

- versioned code, project `AGENTS.md`, TaskCards, reports, decisions, tests, or PR evidence;
- Run Context such as the current Stage, branch, commit, retry, or escalation;
- the authority to choose the next Workflow Stage.

## Planner-to-Executor Flow

```text
AI Memory
  ↓ long-term or private background
Architect / Planner
  ↓ select and compress facts required for this task
TaskCard + repository + project AGENTS.md + explicit inputs
  ↓ self-contained execution context
Executor
```

A fresh-session Executor must not be required to search AI Memory or infer missing facts. If a fact
is required for task success and is safe to version, it belongs in the TaskCard or another auditable
Artifact. If it is private, the TaskCard references a safe environment-variable name or operator
action without copying the private value.

Avoid both failure modes:

1. copying all long-term memory into every TaskCard;
2. issuing an incomplete TaskCard and expecting the Executor to discover essential context.

## Future Composition Rule

An external runtime may help the Planner locate candidate memory and may propose post-run memory
updates. AI Memory keeps its own write/lifecycle policy. Agent Workflow must not define stage-level
memory configuration, force a memory write, or make memory availability a hidden transition gate.

No AI Memory API redesign, adapter contract, automatic retrieval subsystem, or cross-repository
migration is authorized by this note.
