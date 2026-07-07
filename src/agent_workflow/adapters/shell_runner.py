"""Shell Runner adapter — executes stages via local shell commands.

Stub implementation for Phase 0. Real runner integration deferred to Phase 1.
"""

from __future__ import annotations

from typing import Any

from agent_workflow.ports.runner import RunnerPort


class ShellRunner(RunnerPort):
    """Local shell-based stage runner.

    Executes stages by running commands in a shell. This is a minimal
    implementation for Phase 0 validation.

    TODO (Phase 1): Implement full stage lifecycle with state machine.
    """

    def run_stage(
        self,
        stage_id: str,
        role: str,
        inputs: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a stage. Returns a result dict.

        In Phase 0, this is a no-op placeholder. Phase 1 will run actual commands
        and track stage state.
        """
        return {
            "stage_id": stage_id,
            "role": role,
            "status": "completed",
            "outputs": {},
            "message": (
                "ShellRunner.run_stage is a Phase 0 stub."
                " Full implementation deferred to Phase 1."
            ),
        }

    def cancel_stage(self, stage_run_id: str) -> bool:
        return True

    def get_status(self, stage_run_id: str) -> dict[str, Any]:
        return {"stage_run_id": stage_run_id, "status": "unknown"}
