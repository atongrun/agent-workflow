from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "src" / "agent_workflow" / "operations" / "awf_executor.py"
ROLE_HANDLER = ROOT / "src" / "agent_workflow" / "operations" / "awf_role.py"
ADAPTERS = ROOT / "src" / "agent_workflow" / "operations" / "agent_adapters"
RUNTIME_WORKSPACE = ROOT / "src" / "agent_workflow" / "runtime" / "workspace.py"
RUNTIME_APPLICATION = ROOT / "src" / "agent_workflow" / "runtime" / "application.py"
RUNTIME_ARTIFACT = ROOT / "src" / "agent_workflow" / "runtime" / "artifact.py"


def production_python_files() -> list[Path]:
    return sorted((ROOT / "src" / "agent_workflow" / "operations").rglob("*.py"))


def test_only_unified_executor_imports_subprocess():
    violations = []
    for path in production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "subprocess" for alias in node.names) and path != EXECUTOR:
                    violations.append(path.relative_to(ROOT).as_posix())
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess" and path != EXECUTOR:
                    violations.append(path.relative_to(ROOT).as_posix())

    assert violations == []


def test_installed_application_and_workspace_are_the_only_runtime_local_process_boundaries():
    violations = []
    runtime_package = ROOT / "src" / "agent_workflow" / "runtime"
    for path in sorted(runtime_package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_subprocess = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name == "subprocess" for alias in node.names)
            )
            or (isinstance(node, ast.ImportFrom) and node.module == "subprocess")
            for node in ast.walk(tree)
        )
        if imports_subprocess and path not in {RUNTIME_APPLICATION, RUNTIME_WORKSPACE}:
            violations.append(path.relative_to(ROOT).as_posix())

    source = RUNTIME_WORKSPACE.read_text(encoding="utf-8")
    application = RUNTIME_APPLICATION.read_text(encoding="utf-8")
    assert violations == []
    assert "shell=False" in source and "shell=False" in application
    assert "shell=True" not in source and "shell=True" not in application


def test_installed_artifact_boundary_has_no_effect_or_authority_escape_hatch():
    source = RUNTIME_ARTIFACT.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RUNTIME_ARTIFACT))
    forbidden_imports = {
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "awf_control_plane",
        "awf_delivery",
        "awf_executor",
    }
    forbidden_calls = {
        "run",
        "Popen",
        "spawn",
        "send_event",
        "import_workspace_delta",
        "commit",
        "push",
        "fetch",
    }
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in forbidden_imports:
                    violations.append(f"{node.lineno}:import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".", 1)[0] in forbidden_imports:
                violations.append(f"{node.lineno}:import:{node.module}")
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in forbidden_calls:
                violations.append(f"{node.lineno}:call:{name}")

    assert violations == []
    assert not any(
        term in source
        for term in (
            "RunStore",
            "InvocationJournal",
            "WorkflowStage",
            "agent-bus",
            "checkpoint",
            "outbox",
            "inbox",
        )
    )


def test_production_code_never_uses_implicit_shell_execution():
    violations = []
    for path in production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    violations.append(path.relative_to(ROOT).as_posix())

    assert violations == []


def test_only_executor_starts_local_processes():
    forbidden = {"Popen", "run", "call", "check_call", "check_output"}
    violations = []
    for path in production_python_files():
        if path == EXECUTOR:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in forbidden
                and isinstance(node.value, ast.Name)
                and node.value.id in {"subprocess", "_subprocess"}
            ):
                violations.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")

    assert violations == []


def test_shell_launchers_remain_thin_python_compatibility_shims():
    launchers = {
        "src/agent_workflow/operations/awf-dispatch.sh": 15,
        "src/agent_workflow/operations/service/awf-listen-service.sh": 35,
        "src/agent_workflow/operations/service/awf-listen-service.cmd": 20,
    }
    for relative, maximum_lines in launchers.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert len(source.splitlines()) <= maximum_lines
        assert "agent_workflow.operations.awf_" in source


def test_agent_adapter_renderers_are_pure_operations_modules():
    forbidden_imports = {
        "awf_control_plane",
        "awf_delivery",
        "awf_executor",
        "awf_role",
        "os",
        "subprocess",
    }
    forbidden_calls = {"spawn", "start_command", "run_command", "send_event"}
    expected_functions = {
        "codex.py": {"render_reviewer_invocation"},
        "opencode.py": {"render_executor_argv", "render_reviewer_argv"},
        "pi.py": {"render_reviewer_argv"},
    }
    violations = []

    for path in sorted(ADAPTERS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if functions != expected_functions[path.name]:
            violations.append(f"{path.name}:unexpected-functions:{sorted(functions)}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_imports:
                        violations.append(f"{path.name}:{node.lineno}:import:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in forbidden_imports:
                    violations.append(f"{path.name}:{node.lineno}:import:{node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_calls:
                    violations.append(f"{path.name}:{node.lineno}:call:{node.func.id}")

    assert sorted(path.name for path in ADAPTERS.glob("*.py")) == [
        "__init__.py",
        "codex.py",
        "opencode.py",
        "pi.py",
    ]
    assert violations == []


def test_awf_role_tool_wrappers_delegate_rendering():
    tree = ast.parse(ROLE_HANDLER.read_text(encoding="utf-8"), filename=str(ROLE_HANDLER))
    source = ROLE_HANDLER.read_text(encoding="utf-8")
    assert "agent_adapters" not in source
    expected_calls = {
        "tool_opencode_exec": {"_provider_spec", "render_provider_invocation", "spawn_rendered"},
        "tool_opencode_review": {
            "_provider_spec",
            "render_provider_invocation",
            "spawn_rendered",
        },
        "tool_codex_review": {"_provider_spec", "render_provider_invocation", "spawn_rendered"},
        "tool_pi_review": set(),
    }
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for wrapper_name, renderer_calls in expected_calls.items():
        wrapper = functions[wrapper_name]
        calls = {
            node.func.id
            for node in ast.walk(wrapper)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        reconstructed_argv = [
            node.lineno
            for node in ast.walk(wrapper)
            if isinstance(node, (ast.Assign, ast.AugAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "argv"
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            )
        ]

        assert renderer_calls <= calls
        assert reconstructed_argv == []

    pi_calls = {
        node.func.id
        for node in ast.walk(functions["tool_pi_review"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "render_pi_reviewer_argv" not in pi_calls
    nested_invoke = next(
        node
        for node in functions["tool_pi_review"].body
        if isinstance(node, ast.FunctionDef) and node.name == "invoke"
    )
    nested_calls = {
        node.func.id
        for node in ast.walk(nested_invoke)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"_provider_spec", "render_provider_invocation", "spawn_rendered"} <= nested_calls
