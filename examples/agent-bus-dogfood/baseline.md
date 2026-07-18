# Agent Bus Example Baseline

This is the expected brownfield baseline for the first dogfood run. `awf init` must regenerate and verify it against the selected checkout rather than trusting this file blindly.

## Implemented and Working

- Python 3.11 project using Click and HTTPX for the CLI.
- FastAPI, SQLite, and SSE provide the durable relay.
- CLI supports send, pending inspection, ACK, and listen.
- Listener ACK occurs after successful handler completion.
- Existing authentication and CLI helper tests provide a regression base.

## Existing Constraints

- Keep the relay simple and single-node.
- Preserve flexible event payloads and current ACK semantics.
- Avoid new dependencies and server changes for this milestone.
- Live network state is not deterministic test evidence.

## Not Yet Implemented

- A single diagnostic command that classifies configuration, network, service, and token failures.
- The later active send/pending/ACK diagnostic probe.

## Next Milestone

Implement the non-mutating `agent-bus doctor --json` slice from [goal.md](goal.md), with deterministic tests and no unrelated refactor.

## Current Blockers

- The proposed Agent Workflow run commands do not exist; manual Artifact handoff is acceptable and
  a generic controller is not a prerequisite.
- The operations Reviewer path does not yet validate and route semantic ReviewReports. This blocks
  a claim that the cross-machine chain is complete, but it does not invalidate earlier transport
  and handler evidence.
