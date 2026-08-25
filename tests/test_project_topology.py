import pytest

from agent_workflow import cli, project_topology


def test_official_profiles_round_trip(tmp_path):
    for name in project_topology.PROFILES:
        written = project_topology.write(tmp_path / name, project_topology.for_profile(name))
        assert project_topology.load(written.parents[1]).name == name


def test_rejects_unknown_machine_or_credential_fields():
    document = project_topology.for_profile("role-specialized").document()
    document["roles"]["coder"]["token"] = "secret"
    with pytest.raises(project_topology.ProjectTopologyError):
        project_topology.parse(document)


@pytest.mark.parametrize(
    "value",
    [
        "https://host/model",
        "/private/model",
        r"C:\\model",
        "token=secret",
        "api_key:secret",
        "192.168.1.2",
        "host.example",
        "workspace/model",
        "user@host",
        "host.com",
        "api-key=secret",
        "password = secret",
        "key=secret",
        "bearer: secret",
        "dev/project",
        "provider/model-v2",
    ],
)
def test_rejects_unsafe_model_refs(value):
    document = project_topology.for_profile("role-specialized").document()
    document["roles"]["architect"]["model"] = value
    with pytest.raises(project_topology.ProjectTopologyError):
        project_topology.parse(document)


def test_preserves_safe_logical_agents_with_official_model_default():
    document = project_topology.for_profile("role-specialized").document()
    document["roles"]["architect"]["agent"] = "architecture-main"
    parsed = project_topology.parse(document)
    assert parsed.document() == document


def test_rejects_symlinked_awf_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".awf").symlink_to(outside, target_is_directory=True)
    with pytest.raises(project_topology.ProjectTopologyError):
        project_topology.write(repo, project_topology.for_profile("uniform-opencode"))
    assert not list(outside.iterdir())


def test_cli_init_and_check_are_topology_only(tmp_path, capsys):
    assert cli.main(["project", "init", "--repo", str(tmp_path)]) == 0
    path = tmp_path / project_topology.PROJECT_PATH
    before = path.read_bytes()
    assert cli.main(["project", "check", "--repo", str(tmp_path)]) == 0
    assert path.read_bytes() == before
    assert not any(path.parent.glob("machine.json"))
    assert "role-specialized" in capsys.readouterr().out


def test_replace_requires_existing_valid_project(tmp_path):
    path = tmp_path / project_topology.PROJECT_PATH
    path.parent.mkdir()
    path.write_text("not: a-project\n", encoding="utf-8")
    with pytest.raises(project_topology.ProjectTopologyError):
        project_topology.write(
            tmp_path, project_topology.for_profile("uniform-opencode"), replace=True
        )
    assert path.read_text(encoding="utf-8") == "not: a-project\n"


def test_load_rejects_duplicate_yaml_keys(tmp_path):
    path = tmp_path / project_topology.PROJECT_PATH
    path.parent.mkdir()
    path.write_text(
        """apiVersion: agent-workflow/v1
kind: Project
repository: {baseRef: main}
topology: {name: role-specialized}
roles:
  architect: {agent: architect, tool: pi, model: token=secret}
  architect: {agent: architect, tool: pi, model: tool-default}
  coder: {agent: coder, tool: opencode, model: tool-default}
  reviewer: {agent: reviewer, tool: codex, model: tool-default}
""",
        encoding="utf-8",
    )
    with pytest.raises(project_topology.ProjectTopologyError):
        project_topology.load(tmp_path)


def test_load_rejects_oversized_project_file(tmp_path):
    path = tmp_path / project_topology.PROJECT_PATH
    path.parent.mkdir()
    path.write_bytes(b"x" * (project_topology.MAX_PROJECT_BYTES + 1))
    with pytest.raises(project_topology.ProjectTopologyError):
        project_topology.load(tmp_path)
