from __future__ import annotations

from pathlib import Path

from agent_workflow import node


def profile(tmp_path: Path, *, finding_enabled: bool) -> node.NodeProfile:
    return node.NodeProfile(
        tmp_path / "profile.json",
        {
            "format": node.PROFILE_FORMAT,
            "name": "project-machine-reviewer",
            "role": "reviewer",
            "repo": str((tmp_path / "repo").resolve()),
            "tool": "opencode",
            "model": "model",
            "on_type": "task:awf-review-v3",
            "upstream_repo": "owner/project",
            "head_repo": "contributor/project",
            "state_root": str((tmp_path / "state").resolve()),
            "finding_enabled": finding_enabled,
        },
    )


def test_profile_finding_opt_in_is_an_explicit_listener_argument(tmp_path: Path) -> None:
    enabled = node._listener_argv(profile(tmp_path, finding_enabled=True))
    disabled = node._listener_argv(profile(tmp_path, finding_enabled=False))

    assert "--enable-finding" in enabled
    assert "--enable-finding" not in disabled
