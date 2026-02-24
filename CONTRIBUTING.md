# Contributing to OpenReach

Contributions are welcome. This document outlines the process and expectations.

## Development Setup

```bash
# Clone and set up
git clone https://github.com/Coolcorbinian/OpenReach.git
cd openreach

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# Install with dev dependencies
pip install -e ".[dev]"

# Install Playwright
playwright install chromium
```

## Code Standards

- **Python 3.11+** required
- **Ruff** for linting and formatting: `ruff check . && ruff format .`
- **mypy** for type checking: `mypy openreach/`
- **pytest** for tests: `pytest tests/`
- All functions must have type annotations
- All public functions must have docstrings

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes with tests
4. Run the full check suite: `ruff check . && mypy openreach/ && pytest`
5. Commit with a clear message describing the change
6. Open a PR against `main`

## Architecture Guidelines

- **Agent engine** (`openreach/agent/`) -- Core loop and planning logic
- **Browser automation** (`openreach/browser/`) -- Playwright interactions
- **LLM integration** (`openreach/llm/`) -- Ollama client and prompts
- **Data layer** (`openreach/data/`) -- SQLite, CSV, and API client
- **Web UI** (`openreach/ui/`) -- Flask dashboard

Keep modules loosely coupled. The agent engine should not depend directly on Instagram-specific code -- use the browser abstraction layer.

## Reporting Issues

- Use GitHub Issues
- Include: Python version, OS, Ollama model, reproduction steps
- For browser issues: include the Playwright version and browser info

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
