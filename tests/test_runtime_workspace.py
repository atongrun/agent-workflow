from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import subprocess
from pathlib import Path

import pytest

import agent_workflow.runtime.workspace as workspace_module
from agent_workflow.runtime import (
    WorkspaceDelta,
    WorkspaceError,
    WorkspaceSpec,
    assert_frozen_workspace,
    assert_workspace_state,
    bind_environment,
    import_workspace_delta,
    prepare_workspace,
    restore_workspace_manifest,
    serialize_workspace_delta,
    workspace_control_sha256,
    workspace_manifest,
    workspace_manifest_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_MODULE = ROOT / "src" / "agent_workflow" / "runtime" / "workspace.py"
ROLE_HANDLER = ROOT / "scripts" / "awf_role.py"


def run_git(repo: Path | None, *args: str, environment: dict[str, str] | None = None) -> str:
    argv = ["git"]
    if repo is not None:
        argv += ["-C", str(repo)]
    argv.extend(args)
    completed = subprocess.run(
        argv,
        check=True,
        shell=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    return completed.stdout.rstrip("\n\r")


def repository(tmp_path: Path, name: str = "source") -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir()
    run_git(None, "init", "-q", "-b", "main", str(repo))
    run_git(repo, "config", "user.name", "Runtime Test")
    run_git(repo, "config", "user.email", "runtime@example.invalid")
    (repo / "task.md").write_text("frozen task\n", encoding="utf-8")
    run_git(repo, "add", "task.md")
    run_git(repo, "commit", "-q", "-m", "frozen source")
    return repo.resolve(), run_git(repo, "rev-parse", "HEAD^{commit}")


def workspace_environment(tmp_path: Path) -> tuple[tuple[str, str], ...]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    inherited = {}
    for key in (
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    ):
        if key in os.environ:
            inherited[key] = os.environ[key]
    inherited.update(
        {
            "GCM_INTERACTIVE": "Never",
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_KEY_1": "core.hooksPath",
            "GIT_CONFIG_KEY_2": "credential.helper",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_VALUE_1": os.devnull,
            "GIT_CONFIG_VALUE_2": "",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home),
        }
    )
    return bind_environment(inherited)


def spec(tmp_path: Path, repo: Path, commit: str) -> WorkspaceSpec:
    return WorkspaceSpec(
        source_repo=str(repo),
        expected_commit=commit,
        state_dir=str((tmp_path / "event-state").resolve()),
        workspace_prefix="model-workspace-",
        environment=workspace_environment(tmp_path),
    )


def legacy_manifest(
    workspace: Path,
    environment: tuple[tuple[str, str], ...],
) -> dict[str, tuple[str, str]]:
    git_dir = workspace / ".git"
    result: dict[str, tuple[str, str]] = {}
    for path in sorted(git_dir.rglob("*")):
        relative = path.relative_to(git_dir)
        parts = relative.parts
        if parts and parts[0] == "objects" and parts[:2] != ("objects", "info"):
            continue
        if relative.as_posix() == "index":
            continue
        name = relative.as_posix()
        if path.is_symlink():
            result[name] = ("symlink", os.readlink(path))
        elif path.is_file():
            result[name] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        elif path.is_dir():
            result[name] = ("dir", "")
        else:
            result[name] = ("other", "")
    env = dict(environment)
    staged = run_git(workspace, "ls-files", "--stage", "-z", environment=env)
    tree = run_git(workspace, "write-tree", environment=env)
    result["index-semantic"] = (
        "git-index",
        hashlib.sha256(staged.encode("utf-8") + b"\0" + tree.encode("ascii")).hexdigest(),
    )
    return result


def canonical_manifest_sha256(manifest: dict[str, tuple[str, str]]) -> str:
    payload = {key: list(value) for key, value in manifest.items()}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def test_prepare_workspace_is_exact_no_remote_and_event_contained(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)

    prepared = prepare_workspace(operation)
    workspace = Path(prepared.path)

    assert workspace.parent == Path(operation.state_dir)
    assert not workspace.is_symlink()
    assert run_git(workspace, "rev-parse", "HEAD^{commit}") == commit
    assert run_git(workspace, "remote") == ""
    assert not (workspace / ".git" / "logs").exists()
    assert not (workspace / ".git" / "FETCH_HEAD").exists()
    assert prepared.expected_commit == commit
    assert prepared.manifest_sha256 == workspace_manifest_sha256(
        prepared.path, operation.environment
    )


def test_workspace_manifest_and_digests_match_current_oracle(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)

    current = workspace_manifest(prepared.path, operation.environment)
    expected = legacy_manifest(Path(prepared.path), operation.environment)
    expected_stable = {
        key: value for key, value in expected.items() if key not in {"HEAD", "index-semantic"}
    }

    assert current == expected
    assert workspace_manifest_sha256(prepared.path, operation.environment) == (
        canonical_manifest_sha256(expected)
    )
    assert workspace_control_sha256(prepared.path, operation.environment) == (
        canonical_manifest_sha256(expected_stable)
    )


def test_control_drift_denies_before_model_controlled_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    config = Path(prepared.path) / ".git" / "config"
    config.write_text(config.read_text(encoding="utf-8") + "[credential]\nhelper = rogue\n")

    def forbidden_git(*_args, **_kwargs):
        raise AssertionError("Git must remain unreachable after control drift")

    monkeypatch.setattr(workspace_module, "_run_git", forbidden_git)

    with pytest.raises(WorkspaceError, match="control metadata changed"):
        assert_frozen_workspace(prepared.path, operation.environment)


def test_semantic_index_drift_is_rejected(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    workspace = Path(prepared.path)
    (workspace / "rogue.txt").write_text("rogue\n", encoding="utf-8")
    run_git(workspace, "add", "rogue.txt", environment=dict(operation.environment))

    with pytest.raises(WorkspaceError, match="control metadata changed"):
        assert_frozen_workspace(prepared.path, operation.environment)


def test_durable_manifest_restore_requires_exact_compatible_digest(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    workspace_module._FROZEN_MANIFESTS.clear()

    with pytest.raises(WorkspaceError, match="not frozen"):
        assert_frozen_workspace(prepared.path, operation.environment)
    with pytest.raises(WorkspaceError, match="does not match"):
        restore_workspace_manifest(
            prepared.path,
            "sha256:" + "0" * 64,
            operation.environment,
        )

    assert (
        restore_workspace_manifest(
            prepared.path,
            prepared.manifest_sha256,
            operation.environment,
        )
        == prepared.path
    )
    assert_frozen_workspace(prepared.path, operation.environment)


@pytest.mark.parametrize("mutation", ["head", "remote"])
def test_workspace_head_or_remote_drift_fails_closed(tmp_path: Path, mutation: str) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    workspace = Path(prepared.path)
    if mutation == "head":
        (workspace / "changed.txt").write_text("changed\n", encoding="utf-8")
        run_git(workspace, "add", "changed.txt")
        run_git(workspace, "config", "user.name", "Untrusted Model")
        run_git(workspace, "config", "user.email", "model@example.invalid")
        run_git(workspace, "commit", "-q", "-m", "untrusted commit")
    else:
        run_git(workspace, "remote", "add", "rogue", str(repo))

    with pytest.raises(WorkspaceError):
        assert_workspace_state(prepared.path, commit, operation.environment)


def test_exact_delta_identity_and_trusted_import_match_verified_tree(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    workspace = Path(prepared.path)
    (workspace / "result.txt").write_text("trusted delta\n", encoding="utf-8")

    delta = serialize_workspace_delta(prepared.path, operation.environment)
    imported_tree = import_workspace_delta(delta, str(repo), operation.environment)

    assert delta.base_tree == run_git(repo, "rev-parse", "HEAD^{tree}")
    assert delta.model_tree == imported_tree == run_git(repo, "write-tree")
    assert delta.patch_sha256 == hashlib.sha256(delta.patch).hexdigest()
    assert len(delta.identity_sha256) == 64
    assert (repo / "result.txt").read_text(encoding="utf-8") == "trusted delta\n"


def test_patch_mutation_changes_identity_and_denies_import(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    (Path(prepared.path) / "result.txt").write_text("delta\n", encoding="utf-8")
    delta = serialize_workspace_delta(prepared.path, operation.environment)
    mutated = WorkspaceDelta(delta.base_tree, delta.model_tree, b"not a Git patch\n")

    assert mutated.identity_sha256 != delta.identity_sha256
    with pytest.raises(WorkspaceError, match="Git operation failed"):
        import_workspace_delta(mutated, str(repo), operation.environment)
    assert run_git(repo, "status", "--porcelain") == ""


def test_git_capture_stops_at_the_explicit_bound(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    (Path(prepared.path) / "task.md").write_text("bounded output\n", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="output is too large"):
        workspace_module._run_git(
            operation.environment,
            "-C",
            prepared.path,
            "diff",
            "--binary",
            capture_limit=8,
        )


def test_empty_delta_and_trusted_tree_mismatch_deny(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)

    with pytest.raises(WorkspaceError, match="no importable changes"):
        serialize_workspace_delta(prepared.path, operation.environment)

    (Path(prepared.path) / "result.txt").write_text("delta\n", encoding="utf-8")
    delta = serialize_workspace_delta(prepared.path, operation.environment)
    mismatched = WorkspaceDelta(delta.base_tree, delta.base_tree, delta.patch)
    with pytest.raises(WorkspaceError, match="trusted imported tree"):
        import_workspace_delta(mismatched, str(repo), operation.environment)


def test_redirected_state_or_trusted_repo_is_rejected(tmp_path: Path) -> None:
    repo, commit = repository(tmp_path)
    real_state = tmp_path / "real-state"
    real_state.mkdir()
    state_link = tmp_path / "state-link"
    trusted_link = tmp_path / "trusted-link"
    try:
        state_link.symlink_to(real_state, target_is_directory=True)
        trusted_link.symlink_to(repo, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(WorkspaceError, match="redirected"):
        WorkspaceSpec(
            source_repo=str(repo),
            expected_commit=commit,
            state_dir=str(state_link),
            workspace_prefix="model-workspace-",
            environment=workspace_environment(tmp_path),
        )

    operation = spec(tmp_path, repo, commit)
    prepared = prepare_workspace(operation)
    (Path(prepared.path) / "result.txt").write_text("delta\n", encoding="utf-8")
    delta = serialize_workspace_delta(prepared.path, operation.environment)
    with pytest.raises(WorkspaceError, match="redirected"):
        import_workspace_delta(delta, str(trusted_link), operation.environment)


@pytest.mark.parametrize(
    "environment",
    [
        {"PATH": "/bin", "AWF_CODER_TOKEN": "redacted"},
        {"PATH": "/bin", "API_PASSWORD": "redacted"},
        {"PATH": "/bin", "PATH\x00": "invalid"},
        {},
    ],
)
def test_workspace_environment_rejects_credentials_or_invalid_input(
    environment: dict[str, str],
) -> None:
    with pytest.raises(WorkspaceError):
        bind_environment(environment)


def test_installed_workspace_has_closed_commands_and_wrappers_only_delegate() -> None:
    source = WORKSPACE_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(WORKSPACE_MODULE))
    literal_commands = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    public = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }

    assert "push" not in literal_commands
    assert "fetch" not in literal_commands
    assert "shell=True" not in source
    assert "from scripts" not in source
    assert "import scripts" not in source
    assert all(
        parameter.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        for name in public
        for parameter in inspect.signature(getattr(workspace_module, name)).parameters.values()
    )

    role_tree = ast.parse(ROLE_HANDLER.read_text(encoding="utf-8"), filename=str(ROLE_HANDLER))
    functions = {
        node.name: node
        for node in role_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    expected = {
        "prepare_model_workspace": {"prepare_workspace"},
        "assert_model_workspace_state": {"runtime_assert_workspace_state"},
        "import_model_delta": {"serialize_workspace_delta", "import_workspace_delta"},
    }
    for name, required in expected.items():
        calls = {
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert required <= calls
        assert "run_command" not in calls
        assert "git" not in calls
        assert "git_out" not in calls
