# Contributing

Thanks for your interest! The project is small and in alpha, so please open an issue to discuss a
change before sending a large pull request.

## Setup

```bash
uv venv && uv pip install -e ".[dev]"
uv run pre-commit install        # optional: runs the checks below before each commit
```

## Before you open a pull request

```bash
python -m pytest
ruff check . && ruff format --check .
mypy
bandit -r tracehunter -c pyproject.toml
xenon --max-absolute B --max-modules A --max-average A tracehunter
```

CI runs the same checks plus Semgrep, gitleaks, pip-audit, container and infrastructure scans.

## Guidelines

- The code is object-oriented on purpose: classes with private attributes (`_name`) exposed through
  properties, full type hints and docstrings. Docstrings, comments and messages are in English.
- Keep the layers separate: `domain` knows nothing about `infrastructure`, `application` or `api`.
- Instrumentation must **never** break or hide errors from the code it observes.
- The web UI uses no inline scripts or styles, because the server sends a strict
  Content-Security-Policy. Put code in `tracehunter/api/static/`.
- Add tests for every change. Property-based tests (Hypothesis) are welcome for serialization.
- Never commit secrets, real traces or `.db` files.

By contributing you agree that your work is released under the [MIT License](LICENSE).
