"""Local Memory adapter — returns empty context, logs candidates to temp dir.

Stub implementation for Phase 0. Real ai-memory integration is deferred to Phase 3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_workflow.ports.memory import MemoryPort


class LocalMemory(MemoryPort):
    """File-based no-op memory adapter.

    Always returns empty context. Logs write candidates to a local temp directory.
    Real ai-memory integration will be added in Phase 3.
    """

    def __init__(self, temp_dir: str | None = None):
        self._temp_dir = Path(temp_dir or ".awf/memory-candidates")
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._candidate_counter = 0

    def request_context(self, query: str, max_items: int = 5) -> dict[str, Any]:
        """Returns empty context — ai-memory integration deferred to Phase 3."""
        return {"query": query, "contexts": [], "source": "local-memory-noop"}

    def publish_write_candidates(self, candidates: list[dict[str, Any]]) -> list[str]:
        """Log candidates to local temp directory. Does not write to ai-memory."""
        ids = []
        for candidate in candidates:
            self._candidate_counter += 1
            cid = f"candidate-{self._candidate_counter}"
            ids.append(cid)
            candidate_file = self._temp_dir / f"{cid}.json"
            with open(candidate_file, "w") as f:
                json.dump(candidate, f, indent=2)
        return ids
