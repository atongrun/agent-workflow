# Concepts

## Resource Model

All Agent Workflow resources share a unified structure:

```yaml
apiVersion: agent-workflow/v1alpha1
kind: <ResourceKind>
metadata:
  name: <kebab-case-name>
  version: <semver>
spec:
  ...
```

### Supported Kinds

| Kind | Purpose |
|------|---------|
| `Role` | Defines an agent role with responsibilities and constraints |
| `Workflow` | Defines a multi-stage process with transitions |
| `BindingProfile` | Maps roles to concrete runner configurations |
| `Policy` | Stage-level rules and constraints |
| `Artifact` | Structured handoff document between stages |
| `Event` | Workflow event for Agent Bus integration |

---

## Role

A Role is a job description for an agent. It says what the role can do, must do, and must not do — without saying which model or tool performs it.

```yaml
apiVersion: agent-workflow/v1alpha1
kind: Role
metadata:
  name: planner
spec:
  description: Plans and decomposes work.
  responsibilities: [Understand goals, Decompose tasks]
  capabilities: [Read requirements, Write TaskCard]
  forbiddenActions: [Modify code, Approve own plan]
  requiredInputs: [Task description]
  producedArtifacts: [TaskCard]
```

Roles enforce:
- **Accountability**: Every stage run is attributed to a role.
- **Separation of concerns**: Planner doesn't implement. Implementer doesn't approve.
- **Auditability**: What a role was allowed to do is explicit and versioned.

---

## Workflow

A Workflow is a directed graph of stages. Each stage is assigned a role.

```yaml
spec:
  stages:
    - id: plan
      role: planner
      onSuccess: implement
      onFailure: failed
    - id: implement
      role: implementer
      onSuccess: test
      onFailure: failed
```

### Stage Lifecycle

```
pending → ready → running → waiting → blocked
                 ↓            ↑
              completed ←──────┘
                 ↓
              failed / cancelled
```

### Workflow Run Lifecycle

```
created → running → waiting → blocked
           ↓
       completed / failed / cancelled
```

### Transitions

- `onSuccess`: Next stage when the current stage completes successfully.
- `onFailure`: Next stage when the current stage fails. Can point to a rework stage (e.g., `test → implement`) or a terminal state.
- Terminal states: `completed`, `rejected`, `cancelled`, `failed`.

### Memory Hints

A stage can optionally declare memory integration:

```yaml
- id: plan
  memory:
    read:
      enabled: true
      queryTemplate: "project context for {{ task }}"
      maxItems: 3
    write:
      enabled: true
      candidateTypes: [decision, project-fact]
```

---

## Binding Profile

A Binding Profile decouples roles from runners:

```yaml
spec:
  bindings:
    planner:
      runner: codex
      model: claude-sonnet-4
      mode: planning-only
    implementer:
      runner: hermes
      mode: write
```

The same workflow can use different bindings in different environments — local dev uses `shell`, remote CI uses `hermes`, without changing the workflow definition.

---

## Artifact

Artifacts are the formal handoff mechanism between stages. Every artifact carries:

| Field | Purpose |
|-------|---------|
| `artifactId` | Unique identifier |
| `artifactType` | TaskCard, ImplementationReport, etc. |
| `workflowRunId` | Parent workflow run |
| `stageRunId` | Producing stage |
| `createdBy` | Role + runner attribution |
| `sourceRefs` | Links to upstream artifacts |
| `content` | Structured payload |

### Artifact Types

| Type | Produced By | Purpose |
|------|-------------|---------|
| `TaskCard` | planner | Task definition: scope, acceptance criteria, risks |
| `ImplementationReport` | implementer | What was changed, commands run, deviations |
| `TestReport` | tester | Test results and acceptance criteria status |
| `ReviewReport` | reviewer | Findings, verdict, regression risk |
| `DecisionPacket` | summarizer | Compressed multi-stage summary for arbiter |
| `Decision` | arbiter | Final verdict and mandatory actions |
| `MemoryWriteCandidate` | any stage | Proposed memory entry for AI Memory |

---

## Policy

Policies constrain stage behavior:

```yaml
spec:
  rules:
    - id: no-scope-creep
      effect: deny
      description: Implementer must not expand scope beyond TaskCard
    - id: max-time
      effect: warn
      conditions:
        maxStageMinutes: 30
```

Policies are referenced by stages via the `policy` field. The policy engine evaluates rules and enforces `allow`/`deny`/`warn` effects.

---

## Runner

A Runner is the execution backend for a stage. Runners can be:

- **Local**: Shell commands, subprocesses
- **Remote**: Agent clients (Codex, Hermes, OpenCode, Claude Code)
- **Mock**: No-op implementations for testing

Runners implement `RunnerPort`:

```
run_stage(stage_id, role, inputs, config) → result
cancel_stage(stage_run_id) → bool
get_status(stage_run_id) → status
```
