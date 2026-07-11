# Contributing

Agent Workflow is in early development (Phase 0). Contributions are welcome in these areas:

## What to Contribute

- **Bug fixes**: Validation logic, schema errors, CLI behavior.
- **Documentation**: Typos, unclear explanations, missing examples.
- **New schemas**: Additional artifact types, policy rule patterns.
- **Role definitions**: Refined responsibilities and constraints.
- **Workflow definitions**: Additional workflow patterns.

## What Not to Contribute (Yet)

These are deferred to later phases. Please hold off until the relevant phase begins:

- Workflow runtime engine (Phase 1)
- Agent Bus adapter (Phase 2)
- AI Memory adapter (Phase 3)
- Runner adapters for specific agents (Phase 4)
- Web UI, databases, Docker, Kubernetes

## Development Setup

```bash
git clone https://github.com/atongrun/agent-workflow.git
cd agent-workflow
pip install -e ".[dev]"
```

## Running Tests

```bash
python -m pytest
ruff check .
awf validate roles
awf validate workflows
awf validate profiles
awf validate examples
```

## Code Style

- Python 3.11+
- Ruff for linting and formatting
- Type hints preferred but not mandated for Phase 0
- Docstrings for public APIs

## Pull Request Process

1. Ensure tests pass locally.
2. Run the four directory-specific `awf validate` commands from project root.
3. Keep PRs focused — one concern per PR.
4. Update CHANGELOG.md if the change is user-facing.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
