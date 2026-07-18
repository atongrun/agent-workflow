# Contributing

Agent Workflow is in early development. Contributions are welcome in these areas:

## What to Contribute

- **Bug fixes**: Validation logic, schema errors, CLI behavior.
- **Documentation**: Typos, unclear explanations, missing examples.
- **Contract refinements**: Transition-critical Artifact fields proven by real use.
- **Role definitions**: Refined responsibilities and constraints.
- **Workflow definitions**: Additional workflow patterns.

## What Not to Contribute (Yet)

These are deferred to later phases. Please hold off until the relevant phase begins:

- Generic Workflow Engine or arbitrary DAG runtime
- Agent Bus or AI Memory adapters/protocol redesign
- Agent Host integration or Plugin SDK
- Provider-specific model runners in the core
- Web UI, dashboards, SaaS, or new databases

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
awf validate examples
```

## Code Style

- Python 3.11+
- Ruff for linting and formatting
- Type hints preferred for new and changed public code
- Docstrings for public APIs

## Pull Request Process

1. Ensure tests pass locally.
2. Run the three directory-specific `awf validate` commands from project root.
3. Keep PRs focused — one concern per PR.
4. Update CHANGELOG.md if the change is user-facing.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
