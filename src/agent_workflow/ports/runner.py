"""Port interfaces (Protocols) for swappable adapters."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RunnerPort(Protocol):
    """Interface for stage execution runners."""

    def run_stage(
        self,
        stage_id: str,
        role: str,
        inputs: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a stage. Returns status and outputs."""
        ...

    def cancel_stage(self, stage_run_id: str) -> bool:
        """Cancel a running stage."""
        ...

    def get_status(self, stage_run_id: str) -> dict[str, Any]:
        """Get current status of a stage run."""
        ...


@runtime_checkable
class EventBusPort(Protocol):
    """Interface for event publishing and subscription."""

    def publish(self, event: dict[str, Any]) -> str:
        """Publish an event. Returns the event ID."""
        ...

    def subscribe(self, agent_name: str, callback: Any) -> None:
        """Subscribe to events for a given agent."""
        ...


@runtime_checkable
class MemoryPort(Protocol):
    """Interface for AI Memory context retrieval and write-candidate submission."""

    def request_context(self, query: str, max_items: int = 5) -> dict[str, Any]:
        """Request context from AI Memory. Returns context refs."""
        ...

    def publish_write_candidates(self, candidates: list[dict[str, Any]]) -> list[str]:
        """Submit memory write candidates. Returns candidate IDs."""
        ...


@runtime_checkable
class ArtifactStorePort(Protocol):
    """Interface for structured artifact storage and retrieval."""

    def put(self, artifact: dict[str, Any]) -> str:
        """Store an artifact. Returns its path or ID."""
        ...

    def get(self, artifact_id: str) -> dict[str, Any]:
        """Retrieve an artifact by ID."""
        ...

    def list_for_run(self, workflow_run_id: str) -> list[dict[str, Any]]:
        """List all artifacts for a workflow run."""
        ...
