"""Local EventBus adapter — synchronous, in-process, no-op.

Stub implementation for Phase 0. Real agent-bus integration is deferred to Phase 2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_workflow.ports.event_bus import EventBusPort


class LocalEventBus(EventBusPort):
    """In-process event bus that logs events to a local file.

    This adapter exists so the core can run without Agent Bus.
    Real agent-bus integration will be added in Phase 2.
    """

    def __init__(self, log_dir: str | None = None):
        self._log_dir = Path(log_dir or ".awf/events")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def publish(self, event: dict[str, Any]) -> str:
        self._counter += 1
        event_id = event.get("eventId", f"local-{self._counter}")
        event["eventId"] = event_id

        log_file = self._log_dir / "events.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        return event_id

    def subscribe(self, agent_name: str, callback: Any) -> None:
        """Not implemented in Phase 0 — event bus integration deferred to Phase 2."""
        pass
