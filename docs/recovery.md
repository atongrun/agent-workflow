# Recovery and security boundaries

## Durable identities

The Host holds a single-writer lock and atomically replaces a private JSON state file after file sync; supported Unix systems also sync the containing directory. Native Pi sessions are separate and authoritative. Each task has a stable primary Pi ID (and an optional reviewer ID only when enabled), defaults, branch intent and accumulated budgets. Request records bind a caller ID to task, operation and canonical payload. A duplicate never implicitly retries an uncertain model prompt.

The node holds its own single-writer lock and durable job records. It persists session/message mapping and dispatch intent before native prompt submission. OpenCode's caller-supplied `messageID` is not an idempotency guarantee. The node never blindly resends after a lost native prompt acknowledgement. It reconciles native messages, linked assistant parent IDs, status, tools, errors and permission/question waits.

The Host records the first node submission attempt before sending it. A missing job after that attempt is `needs_verification`, even after network restoration. It does not recreate the job automatically if the node ledger vanished. First restore the original durable ledger or inspect the original native session/workspace. No force-retry endpoint exists in this slice. A Host restart resumes read-only job reconciliation and never resets the execution budget or branch/session identity. Browser closure has no effect on accepted background work.

## What is evidence

- HTTP acceptance is not completion
- Pi `agent_end` is not the stable idle boundary; use `agent_settled`
- OpenCode status-map absence alone is not completion
- Model prose is not a commit, passing test or approval
- Native tool records are evidence to review; they remain labeled unverified in projections
- Default Done/Needs Changes is a structured same-Pi conclusion after native evidence; optional Approved is an independent reviewer conclusion; Git merge is independently unknown

Large evidence projections are bounded excerpts with native message/tool references. Full records remain with native OpenCode. Earlier rounds are retained in node jobs and Host execution history. A native session file that was previously populated must not silently fall back to an empty replacement session if missing or unreadable. New Pi sessions can return a filename before their first persisted message; that empty-session case is handled separately.

## Cancellation

Stopping Pi clears its queued inputs and then calls native abort. Cleared input text is returned as a recoverable UI event. It does not cancel OpenCode. Execution cancellation uses a separate durable request and native abort receipt, then verifies native idle state. A late cancellation after genuine completion must not rewrite completed work into a false cancellation. Cancellation before any dispatch must never start work.

If a native process or transport disappears, preserve the request and report uncertainty. Do not use new task/session IDs to bypass it. Native extension UI responses are single-use and process-bound; no response ACK exists, so the Host distinguishes sent from confirmed.

## Budgets and limits

Defaults are 60 active minutes per task, at most two reworks and 180 active minutes for tasks sharing a plan ID. Role/session changes do not reset them. Pi active time is checkpointed; execution time comes from observed native active intervals. User dialog/permission waits and unavailable intervals are excluded. Counts are operational observations, not billing measurements; unknown execution during a node outage is not magically reconstructed. On exhausted observed budget the Host stops generation/cancels active execution; the node independently enforces its remaining timeout.

Only one task may run native work for a project at a time. The default path uses the same Pi for planning and result reporting. If a separate reviewer is explicitly enabled, role generation is serialized and model contexts remain separate. Token delta replay is process-local and bounded, not a second conversation database. Native history is fetched after restart, compaction or expired cursors.

This initial implementation uses local files and a small control layer. It is not a generic multi-agent framework, a multi-tenant service or a hard sandbox. Operate it as a personal trusted-agent system with appropriately isolated OS accounts and native tool permissions.
