"""CI-only entry point for binary feasibility candidates."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _bounded(argv: list[str], *, cwd: Path) -> dict[str, object]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout_utf8": "世界" in result.stdout or "awf " in result.stdout,
    }


def _probe() -> int:
    from agent_workflow import node_service
    from agent_workflow.resources import operations_dir, schemas_dir, templates_dir

    operations = operations_dir()
    schemas = schemas_dir()
    templates = templates_dir()
    required = [
        operations / "awf_listen.py",
        operations / "awf_role.py",
        operations / "agent_adapters" / "pi.py",
        operations / "service" / "agent-workflow-listener.service.template",
        schemas / "node-profile.schema.json",
        templates / "artifacts" / "review-report.md",
    ]
    with tempfile.TemporaryDirectory(prefix="awf-binary-probe-") as raw_temp:
        root = Path(raw_temp)
        unicode_root = root / "outside source 世界"
        unicode_root.mkdir()
        fake = unicode_root / "fake external cli.py"
        marker = unicode_root / "argv log.txt"
        fake.write_text(
            "import pathlib,sys\n"
            "pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')\n",
            encoding="utf-8",
        )
        exact_value = "structured 世界; & ^"
        fake_result = _bounded(
            [sys.executable, str(fake), str(marker), exact_value], cwd=unicode_root
        )
        fake_exact = bool(
            fake_result.get("ok")
            and marker.is_file()
            and marker.read_text(encoding="utf-8") == exact_value
        )
        module_result = _bounded(
            [sys.executable, "-m", "agent_workflow.cli", "version"], cwd=unicode_root
        )
        listener_result = _bounded(
            [sys.executable, str(operations / "awf_listen.py"), "--help"], cwd=unicode_root
        )
        profile = SimpleNamespace(
            name="feasibility-coder",
            path=unicode_root / "profile.json",
            repo=unicode_root,
            log_path=unicode_root / "listener.log",
        )
        manager = node_service.resolve_manager("auto")
        rendered = node_service.render_definition(profile, manager=manager)
        lifecycle_render = (
            str(Path(sys.executable).resolve()) in rendered
            and str(unicode_root) in rendered
            and "agent_workflow" in rendered
        )
        print(
            json.dumps(
                {
                    "format": "awf.binary-runtime-probe.v1",
                    "resources": all(path.is_file() for path in required),
                    "resource_directories": all(
                        path.is_dir() for path in (operations, schemas, templates)
                    ),
                    "python_reentry_module": bool(module_result.get("ok")),
                    "python_reentry_script": bool(listener_result.get("ok")),
                    "fake_external_cli_exact_argv": fake_exact,
                    "utf8_log_round_trip": fake_exact,
                    "native_manager": manager,
                    "native_lifecycle_render": lifecycle_render,
                    "real_service_mutation": False,
                    "remote_connection": False,
                    "model_invocation": False,
                },
                sort_keys=True,
            )
        )
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "__feasibility_probe__":
        return _probe()
    from agent_workflow.cli import main as awf_main

    return awf_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
