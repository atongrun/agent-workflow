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
| `Artifact` | Structured handoff document between stages |

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

### Transitions

Each stage declares an `onSuccess` and `onFailure` transition naming the next stage (or a terminal state); `onFailure` may point to a rework stage (e.g., `test → implement`) or to a terminal state such as `completed`, `rejected`, `cancelled`, or `failed`.

---

## Artifact

Artifacts are the formal handoff mechanism between stages. Every artifact carries:

| Field | Purpose |
|-------|---------|
| `artifactId` | Unique identifier |
| `artifactType` | TaskCard, ImplementationReport, etc. |
| `workflowRunId` | Parent workflow run |
| `stageRunId` | Producing stage |
| `createdBy` | Role attribution |
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
