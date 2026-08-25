"""Credential-free tracked RC.2 project topology."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml
from yaml.nodes import MappingNode

PROJECT_PATH = ".awf/project.yaml"
FORMAT = "agent-workflow/v1"
MAX_PROJECT_BYTES = 64 * 1024
ROLE_ORDER = ("architect", "coder", "reviewer")
PROFILES = {
    "uniform-opencode": {role: "opencode" for role in ROLE_ORDER},
    "role-specialized": {"architect": "pi", "coder": "opencode", "reviewer": "codex"},
}
_BASE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}\Z")
_AGENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class ProjectTopologyError(ValueError):
    """A project topology is malformed or outside the credential-free contract."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _model_ref_is_safe(value: str) -> bool:
    # This bounded card ships only the two official topology defaults. Explicit
    # tool-native model refs remain a pre-PlanRun override until provider
    # conformance establishes a non-ambiguous tracked grammar.
    return value == "tool-default"


@dataclass(frozen=True)
class ProjectTopology:
    name: str
    base_ref: str
    roles: Mapping[str, str]
    agents: Mapping[str, str]
    models: Mapping[str, str]

    def document(self) -> dict[str, object]:
        return {
            "apiVersion": FORMAT,
            "kind": "Project",
            "repository": {"baseRef": self.base_ref},
            "topology": {"name": self.name},
            "roles": {
                role: {
                    "agent": self.agents[role],
                    "tool": self.roles[role],
                    "model": self.models[role],
                }
                for role in ROLE_ORDER
            },
        }


def for_profile(name: str, *, base_ref: str = "main") -> ProjectTopology:
    if (
        name not in PROFILES
        or not _BASE_REF_RE.fullmatch(base_ref)
        or base_ref.startswith(("/", "-"))
        or base_ref.endswith(("/", ".lock"))
        or ".." in base_ref.split("/")
        or "//" in base_ref
    ):
        raise ProjectTopologyError("unsupported project topology")
    return ProjectTopology(
        name=name,
        base_ref=base_ref,
        roles=PROFILES[name],
        agents={role: role for role in ROLE_ORDER},
        models={role: "tool-default" for role in ROLE_ORDER},
    )


def parse(document: object) -> ProjectTopology:
    if not isinstance(document, dict) or set(document) != {
        "apiVersion",
        "kind",
        "repository",
        "topology",
        "roles",
    }:
        raise ProjectTopologyError("project topology keys are invalid")
    if document["apiVersion"] != FORMAT or document["kind"] != "Project":
        raise ProjectTopologyError("project topology format is invalid")
    repository, topology, roles = document["repository"], document["topology"], document["roles"]
    if (
        not isinstance(repository, dict)
        or set(repository) != {"baseRef"}
        or not isinstance(repository["baseRef"], str)
    ):
        raise ProjectTopologyError("repository baseRef is invalid")
    if (
        not isinstance(topology, dict)
        or set(topology) != {"name"}
        or not isinstance(topology["name"], str)
    ):
        raise ProjectTopologyError("topology name is invalid")
    expected = for_profile(topology["name"], base_ref=repository["baseRef"])
    if not isinstance(roles, dict) or set(roles) != set(ROLE_ORDER):
        raise ProjectTopologyError("project roles are invalid")
    agents: dict[str, str] = {}
    models: dict[str, str] = {}
    for role in ROLE_ORDER:
        value = roles[role]
        if not isinstance(value, dict) or set(value) != {"agent", "tool", "model"}:
            raise ProjectTopologyError("project role keys are invalid")
        agent = value["agent"]
        if not isinstance(agent, str) or not _AGENT_RE.fullmatch(agent):
            raise ProjectTopologyError("project agent identity is invalid")
        if value["tool"] != expected.roles[role]:
            raise ProjectTopologyError("project role topology drifted")
        model = value["model"]
        if not isinstance(model, str) or not _model_ref_is_safe(model):
            raise ProjectTopologyError("project model reference is unsafe")
        agents[role] = agent
        models[role] = model
    return ProjectTopology(
        name=expected.name,
        base_ref=expected.base_ref,
        roles=expected.roles,
        agents=agents,
        models=models,
    )


def load(repo: Path) -> ProjectTopology:
    root = Path(repo).resolve()
    awf_dir = root / ".awf"
    path = awf_dir / "project.yaml"
    if awf_dir.is_symlink() or path.is_symlink():
        raise ProjectTopologyError("project topology path must not be a symbolic link")
    try:
        info = path.stat()
        if not path.is_file() or info.st_size > MAX_PROJECT_BYTES:
            raise ProjectTopologyError("project topology file is invalid")
        return parse(yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader))
    except (OSError, yaml.YAMLError) as exc:
        raise ProjectTopologyError("project topology is unavailable or invalid") from exc


def write(repo: Path, topology: ProjectTopology, *, replace: bool = False) -> Path:
    root = Path(repo).resolve()
    awf_dir = root / ".awf"
    path = awf_dir / "project.yaml"
    if awf_dir.is_symlink() or path.is_symlink():
        raise ProjectTopologyError("project topology path must not be a symbolic link")
    if path.exists() and not replace:
        raise ProjectTopologyError("project topology already exists")
    if path.exists():
        load(root)
    data = yaml.safe_dump(topology.document(), sort_keys=False).encode("utf-8")
    try:
        awf_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".project.yaml.stage-", dir=awf_dir)
    except OSError as exc:
        raise ProjectTopologyError("project topology destination is unavailable") from exc
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ProjectTopologyError("project topology write failed") from exc
    return path
