"""Data models matching the agent-workflow resource schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Metadata:
    name: str
    version: str
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class RoleSpec:
    description: str
    responsibilities: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    forbiddenActions: list[str] = field(default_factory=list)
    requiredInputs: list[str] = field(default_factory=list)
    producedArtifacts: list[str] = field(default_factory=list)
    completionCriteria: list[str] = field(default_factory=list)
    escalationConditions: list[str] = field(default_factory=list)


@dataclass
class StageDef:
    id: str
    role: str
    needs: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    policy: str = ""
    onSuccess: str = ""
    onFailure: str = ""
    memory: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowSpec:
    description: str
    stages: list[StageDef] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    terminalStates: list[str] = field(default_factory=list)


@dataclass
class Resource:
    apiVersion: str
    kind: str
    metadata: Metadata
    spec: dict[str, Any]


VALID_KINDS = {"Role", "Workflow", "Artifact"}
