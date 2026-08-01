from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts" / "awf_executor.py"


def production_python_files() -> list[Path]:
    return sorted((ROOT / "scripts").rglob("*.py"))


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
        "scripts/awf-dispatch.sh": 15,
        "scripts/service/awf-listen-service.sh": 35,
        "scripts/service/awf-listen-service.cmd": 20,
    }
    for relative, maximum_lines in launchers.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert len(source.splitlines()) <= maximum_lines
        assert "awf_dispatch.py" in source or "awf_service.py" in source
