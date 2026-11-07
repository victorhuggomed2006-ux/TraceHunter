# Changelog

## Unreleased

- Estimated cost (USD) per trace in the web interface and the API (`cost_usd`), from a bundled snapshot of OpenRouter list prices (`scripts/update_prices.py` refreshes it). It is an estimate at list prices: it ignores subscription plans, discounts and batch pricing, and models missing from the table get no cost. The Claude Code collector now also records cache token counts.
- The web interface shows token usage (input / output) per trace in the list and in the trace detail; the API returns it as `tokens`.

## 0.1.0 (2026-11-08)

First public version (alpha).

**Library**
- `Tracer` with `trace()` / `span()` context managers and an `observe()` decorator (sync and async).
- Context isolation per thread and per asyncio task (`ContextVar`); nested traces get their own span stack.
- In-memory and SQLite repositories (the SQLite file is created with mode 0600, ordered by timestamp, corrupted rows are skipped).
- Instrumentation never breaks or hides errors from the observed code: safe, size-limited `repr`, and a failure while saving only goes to the log.
- Argument masking and size limits in `observe()`; `capture_io=False` records nothing.
- Public API exposed in `import tracehunter`: tracer, models, repositories, collectors, catalog and redaction helpers.

**Collectors**
- Claude Code collector: one trace per prompt you type, one span per model reply (model and tokens) with tool calls nested under it. Secrets are masked and the model's private reasoning is never copied.
- `CollectorSync` keeps a repository up to date in the background and only rewrites what changed.
- Catalog of 49 AI CLIs and where they store sessions, with a confidence level per entry (`tracehunter.catalog`).

**Interfaces**
- Read-only FastAPI API and web viewer: strict Content-Security-Policy, `Host` validation against DNS rebinding, 18 languages with automatic detection, terminal and classic themes, auto-refresh and keyboard shortcuts.
- Terminal UI (`tracehunter tui`, extra `tui`): trace list, span tree and detail panel with token totals, search, failures filter and a `?` help screen.
- `tracehunter` command (`--claude-code`, `--claude-dir`, `--max-sessions`, `--sync-interval`).

**Project**
- MIT license, security policy, contributing guide, Dockerfile and compose file, and a CI that runs Ruff, mypy, Bandit, Xenon, pytest with property-based tests, Semgrep, gitleaks, pip-audit, Trivy, Grype, Checkov, KICS, OWASP ZAP and a load test.
- Release workflow: pushing a `v*` tag builds the package and attaches it to a GitHub Release (PyPI publishing is prepared but off).
