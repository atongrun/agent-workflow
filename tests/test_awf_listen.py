from __future__ import annotations

from pathlib import Path

from agent_workflow import node
from agent_workflow.operations import awf_listen


def profile(tmp_path: Path, *, finding_enabled: bool) -> node.NodeProfile:
    return node.NodeProfile(
        tmp_path / "profile.json",
        {
            "format": node.PROFILE_FORMAT,
            "name": "project-machine-reviewer",
            "role": "reviewer",
            "repo": str((tmp_path / "repo").resolve()),
            "tool": "opencode",
            "tool_executable": str((tmp_path / "bin/opencode").resolve()),
            "model": "model",
            "on_type": "task:awf-review-v3",
            "upstream_repo": "owner/project",
            "head_repo": "contributor/project",
            "state_root": str((tmp_path / "state").resolve()),
            "finding_enabled": finding_enabled,
            "enable_preflight": True,
        },
    )


def test_profile_finding_opt_in_is_an_explicit_listener_argument(tmp_path: Path) -> None:
    enabled = node._listener_argv(profile(tmp_path, finding_enabled=True))
    disabled = node._listener_argv(profile(tmp_path, finding_enabled=False))

    assert "--enable-finding" in enabled
    assert "--enable-finding" not in disabled


def test_profile_binds_plan_start_and_existing_preflight_registration(tmp_path: Path) -> None:
    selected = profile(tmp_path, finding_enabled=False)
    argv = node._listener_argv(selected)

    assert argv[argv.index("--profile-path") + 1] == str(selected.authoring_path)
    assert argv[argv.index("--profile-sha256") + 1] == selected.digest
    assert argv[argv.index("--tool-executable") + 1] == selected.values["tool_executable"]
    assert "--enable-preflight" in argv


def test_plan_start_handler_uses_structured_payload_and_exact_profile(tmp_path: Path) -> None:
    from agent_workflow.resources import operations_dir

    argv = awf_listen.build_plan_start_handler_argv(
        "python",
        str(operations_dir() / "awf_plan.py"),
        repo=tmp_path / "repo",
        profile_path=str(tmp_path / "architect.json"),
        profile_sha256="sha256:" + "a" * 64,
        tool="pi",
        model="",
        config_path=tmp_path / "dispatch.env",
        authority_manifest=tmp_path / "authority.json",
        state_root=tmp_path / "state",
        upstream_remote="upstream",
        head_remote="fork",
        head_repo="contributor/project",
        gh_bin="gh",
    )

    assert "{payload.plan}" in argv
    assert "{payload.architect}" in argv
    assert argv[argv.index("--event-id") + 1] == "{id}"
    assert argv[argv.index("--profile-sha256") + 1] == "sha256:" + "a" * 64


def test_listener_bypasses_only_the_private_bus_host() -> None:
    environment = {"NO_PROXY": "localhost", "no_proxy": "localhost"}

    awf_listen.configure_network_bypass(environment, "http://100.81.0.1:8800")

    expected = {"localhost", "100.81.0.1"}
    assert set(environment["NO_PROXY"].split(",")) == expected
    assert environment["no_proxy"] == environment["NO_PROXY"]
