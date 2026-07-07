# Roadmap

## Phase 0: Contract Bootstrap ✅ (Current)

- [x] Repository and project structure
- [x] JSON Schema definitions
- [x] Role definitions (6 roles)
- [x] Workflow definitions (4 workflows)
- [x] Artifact templates (7 templates)
- [x] Validation CLI (`awf validate`, `awf inspect`)
- [x] Schema + semantic validation
- [x] Port interfaces (Protocols)
- [x] Local adapter stubs
- [x] Agent Bus integration contract
- [x] AI Memory integration contract
- [x] Documentation (architecture, concepts, lifecycle, ADRs)
- [x] Tests (schema, semantic, CLI)
- [x] GitHub Actions CI

## Phase 1: Local Workflow Runtime 📋

- [ ] Workflow Run engine — create, start, track runs
- [ ] Stage state machine with full lifecycle transitions
- [ ] Local ShellRunner — execute stages via shell commands
- [ ] Stage input resolution — read artifacts from upstream stages
- [ ] Rework loop handling (test failure → re-implement)
- [ ] `awf run <workflow>` CLI command
- [ ] Pause, resume, cancel workflow runs
- [ ] Artifact lifecycle management
- [ ] Retry policy for failed stages
- [ ] Manual approval gate

**Blockers**: Agent Workflow Phase 1 is blocked until Agent Host contract baseline is reviewed and approved.

## Phase 0.1: Host Integration Hardening 📋

Phase 0.1 tracks the review follow-ups needed before Agent Workflow becomes the Agent Host `workflow.engine` plugin. See [docs/reviews/phase0-followups.md](docs/reviews/phase0-followups.md) for the detailed list.

- [ ] WF-01: Package schema resources for wheel installs
- [ ] WF-02: Route CLI validation through semantic checks
- [ ] WF-03: Add the Agent Host architecture layer
- [ ] WF-04: Decide schema strictness
- [ ] WF-05: Separate version domains
- [ ] WF-06: Define the plugin adapter entry point
- [ ] WF-07: Add formal install smoke tests

**Blockers**: Agent Host contract baseline review and approval.

## Phase 2: Agent Bus Adapter 📋

- [ ] `AgentBusAdapter` — map workflow events to agent-bus wire format
- [ ] Publish stage events (`workflow.stage.*`) via `POST /events`
- [ ] Remote worker dispatch — assign stages to remote agents
- [ ] Status callback — remote agent reports stage completion
- [ ] Idempotent event processing with `eventId` deduplication
- [ ] Retry with backoff for publish failures
- [ ] Cross-machine workflow execution

**Blockers**:
- Requires alignment between Agent Workflow event types and Agent Bus wire format
- Agent Bus v0.1 uses `from_agent`/`to_agent` — need mapping layer

## Phase 3: AI Memory Adapter 📋

- [ ] `AIMemoryAdapter` — subprocess integration with `memory.py`
- [ ] Stage pre-execution context request via `memory.py recall`
- [ ] Stage post-execution candidate submission via `memory.py log`
- [ ] Memory reference in workflow artifacts (pointer, not copy)
- [ ] Workflow history reuse — suggest relevant past decisions
- [ ] Graceful degradation when AI Memory is unavailable

**Blockers**:
- `memory.py recall` output format needs stable contract for programmatic parsing
- No programmatic write-candidate API — must use `memory.py log`

## Phase 4: Runner Adapters 📋

- [ ] Codex runner adapter
- [ ] Hermes runner adapter
- [ ] OpenCode runner adapter
- [ ] Claude Code runner adapter
- [ ] Generic Shell runner (full implementation)
- [ ] Generic HTTP runner
- [ ] Runner capability discovery
- [ ] Runner health checks

**Blockers**: None specific — each adapter is independent.

---

## Non-Roadmap

These are explicitly excluded from the roadmap:

- Web UI or dashboard
- Visual workflow builder (drag-and-drop)
- Hosted multi-tenant SaaS
- Database migration from files to SQL/NoSQL
- Kubernetes operator
- MCP Server integration
- Cloud provider SDKs (AWS, GCP, Azure)
