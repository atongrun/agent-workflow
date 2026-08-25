"""Locate canonical runtime resources in a source tree or installed wheel."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_DIR.parent.parent


def _resource_directory(packaged_name: str, source_name: str) -> Path:
    packaged = PACKAGE_DIR / packaged_name
    if packaged.is_dir():
        return packaged
    source = SOURCE_ROOT / source_name
    if source.is_dir():
        return source
    raise RuntimeError(f"Agent Workflow resource directory is unavailable: {packaged_name}")


def operations_dir() -> Path:
    """Return the production operations directory without depending on cwd."""
    return _resource_directory("operations", "operations")


def templates_dir() -> Path:
    """Return the canonical artifact templates directory."""
    return _resource_directory("templates", "templates")


def schemas_dir() -> Path:
    """Return the canonical JSON schema directory."""
    return _resource_directory("schemas", "schemas")


def authority_manifest_path() -> Path:
    """Return the packaged default operations authority manifest."""
    path = operations_dir() / "authority-manifest.example.json"
    if not path.is_file():
        raise RuntimeError("Agent Workflow authority manifest is unavailable")
    return path
