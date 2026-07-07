"""Filesystem Artifact Store adapter.

Stores artifacts under .awf/runs/<workflow-run-id>/artifacts/
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent_workflow.ports.artifact_store import ArtifactStorePort


class FilesystemArtifactStore(ArtifactStorePort):
    """Artifact storage backed by the local filesystem.

    Directory layout:
        .awf/runs/<workflow-run-id>/artifacts/<artifact-id>.json
    """

    def __init__(self, base_dir: str | None = None):
        self._base_dir = Path(base_dir or ".awf/runs")

    def _artifact_path(self, workflow_run_id: str, artifact_id: str) -> Path:
        return self._base_dir / workflow_run_id / "artifacts" / f"{artifact_id}.json"

    def put(self, artifact: dict[str, Any]) -> str:
        workflow_run_id = artifact.get("spec", {}).get("workflowRunId", "unknown")
        artifact_id = artifact.get("spec", {}).get("artifactId", "unknown")
        path = self._artifact_path(workflow_run_id, artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(artifact, f, indent=2)
        return str(path)

    def get(self, artifact_id: str) -> dict[str, Any]:
        """Get an artifact by full path or by searching under .awf/runs/."""
        # Try as direct path first
        path = Path(artifact_id)
        if path.exists():
            with open(path) as f:
                return json.load(f)

        # Search under .awf/runs
        for run_dir in self._base_dir.iterdir():
            artifact_path = run_dir / "artifacts" / f"{artifact_id}.json"
            if artifact_path.exists():
                with open(artifact_path) as f:
                    return json.load(f)

        raise FileNotFoundError(f"Artifact not found: {artifact_id}")

    def list_for_run(self, workflow_run_id: str) -> list[dict[str, Any]]:
        run_dir = self._base_dir / workflow_run_id / "artifacts"
        if not run_dir.exists():
            return []

        artifacts = []
        for fname in sorted(os.listdir(run_dir)):
            if fname.endswith(".json"):
                with open(run_dir / fname) as f:
                    artifacts.append(json.load(f))
        return artifacts
