"""Error types for agent-workflow."""

from __future__ import annotations


class AgentWorkflowError(Exception):
    """Base error for agent-workflow."""

    exit_code: int = 1


class ValidationError(AgentWorkflowError):
    """Schema or semantic validation failure."""

    def __init__(self, message: str, path: str = "", field: str = ""):
        self.message = message
        self.path = path
        self.field = field
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [self.path]
        if self.field:
            parts.append(self.field)
        location = ": ".join(filter(None, parts))
        if location:
            return f"{location}: {self.message}"
        return self.message


class SchemaValidationError(AgentWorkflowError):
    """JSON Schema validation failure for a specific file."""

    def __init__(self, path: str, errors: list[str]):
        self.path = path
        self.errors = errors
        super().__init__(f"{path}: {', '.join(errors)}")


class SemanticValidationError(AgentWorkflowError):
    """Semantic validation failure (cross-resource consistency)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ParseError(AgentWorkflowError):
    """Error parsing a resource file."""

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")
