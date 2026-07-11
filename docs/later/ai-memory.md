# AI Memory Integration (Later — Not in Core)

> **Status: deferred.** This is a future, optional external integration. The Agent
> Workflow core does **not** reserve interfaces for it and ships no memory port or
> adapter. The method runs with only local files. This document is retained as a
> boundary record: when a real project needs shared long-term memory, a fresh adapter
> is written against AI Memory's actual API — not a pre-built stub.

This document describes how Agent Workflow *would* integrate with [AI Memory](https://github.com/atongrun/ai-memory) — the Markdown + Git based shared agent memory repository.

## Integration Model

```
Agent Workflow                        AI Memory
┌──────────────┐                    ┌──────────────────┐
│ Stage        │── context query ──►│ memory.py recall │
│ (before run) │                    │                  │
│              │◄── context refs ───│ file-based memory│
├──────────────┤                    │                  │
│ Stage        │── write candidate─►│                  │
│ (after run)  │                    │ memory.py log    │
│              │                    │ (or manual write)│
└──────────────┘                    └──────────────────┘
```

- Agent Workflow **requests context** before stage execution.
- AI Memory **returns context refs** (file paths, not content).
- Agent Workflow **submits write candidates** after stage completion.
- AI Memory **decides** whether to persist each candidate.

## Context Request Flow

```
1. Stage becomes ready
2. Agent Workflow checks stage.memory.read.enabled
3. If enabled:
   a. Generate MemoryContextRequest with queryTemplate
   b. Send to AI Memory (memory.py recall)
   c. Receive MemoryContextRefs (file paths + summaries)
   d. Stage Runner reads filtered context
4. Stage executes with context available
```

## Memory Write Flow

```
1. Stage completes
2. Agent Workflow checks stage.memory.write.enabled
3. If enabled:
   a. Stage Runner generates MemoryWriteCandidate artifacts
   b. Agent Workflow publishes candidates (event: workflow.memory.write-candidates.published)
   c. AI Memory receives candidates
4. AI Memory independently:
   a. Runs mini-check (Memory Gate)
   b. Deduplicates against existing notes
   c. Decides tier: notes/ → CONTEXT.md → decisions/ → skip
   d. Commits and pushes if Git Sync Policy allows
```

## Design Rules

1. **Agent Workflow cannot force AI Memory to write.** It only submits candidates.
2. **AI Memory runs its own Memory Gate** (mini-check → detailed check → tier decision).
3. **Agent Workflow artifacts save memory references, not full memory content.**
4. **A stage MUST run even if AI Memory is unavailable**, unless the stage explicitly sets `memory` as required.
5. **No direct file writes** from Agent Workflow to AI Memory's repository.

## Stage Memory Configuration

```yaml
- id: plan
  memory:
    read:
      enabled: true
      queryTemplate: "project context for {{ task }}"
      maxItems: 3
    write:
      enabled: true
      candidateTypes:
        - decision
        - project-fact
```

### Fields

| Field | Purpose |
|-------|---------|
| `read.enabled` | Request context before stage |
| `read.queryTemplate` | Template for context query (supports `{{ variable }}` substitution) |
| `read.maxItems` | Max context refs to return |
| `write.enabled` | Submit candidates after stage |
| `write.candidateTypes` | Allowed candidate types: `decision`, `lesson`, `preference`, `project-fact` |

## Memory Write Candidate Structure

```json
{
  "artifactId": "candidate-1",
  "artifactType": "MemoryWriteCandidate",
  "content": {
    "type": "decision",
    "summary": "Chose MIT license for agent-workflow",
    "content": "The agent-workflow project uses MIT license to match agent-bus.",
    "source": {
      "workflowRunId": "run-123",
      "stageId": "decide",
      "confidence": "high"
    }
  }
}
```

## Current AI Memory Compatibility

*Based on inspection of `ai-memory` at `github.com/atongrun/ai-memory`.*

### Confirmed Interfaces

| AI Memory Feature | Status | Notes |
|------------------|--------|-------|
| `memory.py bootstrap` | ✅ Available | Returns read_order, recommended_topics, recommended_reads |
| `memory.py recall` | ✅ Available | Returns matched_topics, recommended_reads, related_decisions, recent_notes |
| `memory.py log` | ✅ Available | Appends events to `runs/<date>/<task-id>/events.jsonl` |
| `memory.py replay` | ✅ Available | Generates replay.md from events |
| `memory.py lint` | ✅ Available | Lints memory markdown for safety and quality |
| Topic-based recall | ✅ Available | Keyword matching via `memory.yml` config |
| Memory Gate (mini-check → detailed) | ✅ Available | Progressive memory check protocol |
| Memory tiers (notes/context/decisions) | ✅ Available | Tiered write policy |
| Git Sync Policy | ✅ Available | Conditional auto-commit/push |

### Known Gaps

| Gap | Impact | Resolution |
|-----|--------|------------|
| No HTTP API — all interaction via CLI (`memory.py`) | Agent Workflow must shell out or use a Python import | Phase 3 adapter will use subprocess or direct Python import |
| `memory.py recall` returns file paths, not content | Stage runner needs to read files separately | Acceptable — lightweight references preferred |
| No write-candidate API | Candidates must be sent as `log` events or written to files | Use `memory.py log` for candidate submission |
| No programmatic context query beyond keyword matching | Complex queries may miss relevant context | Acceptable for Phase 3 |
| File-based storage (no database) | No concurrent write coordination | Acceptable for single-user setup |

### Deferred to Phase 3

- Production `AIMemoryAdapter` implementation
- Subprocess integration with `memory.py recall`
- Write candidate submission via `memory.py log`
- Error handling for AI Memory unavailability

### TODO

- [ ] Define stable `memory.py recall` output format contract for programmatic parsing (Phase 3)
- [ ] Implement `AIMemoryAdapter` using subprocess or Python import (Phase 3)
- [ ] Test context request → stage execution → candidate submission loop (Phase 3)
