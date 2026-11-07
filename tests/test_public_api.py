"""The public API: what `import tracehunter` exposes and what it must NOT pull in."""

import subprocess
import sys

import tracehunter


def test_everything_in_all_is_importable() -> None:
    for name in tracehunter.__all__:
        assert hasattr(tracehunter, name), name


def test_collectors_catalog_and_redaction_are_exposed() -> None:
    from tracehunter import (  # noqa: F401
        DEFAULT_CATALOG,
        ClaudeCodeCollector,
        CollectorSync,
        Confidence,
        redact,
    )

    assert redact("token=abc123") == "token=***"
    assert len(DEFAULT_CATALOG) > 40
    assert Confidence.VERIFIED_LOCAL in {tool.confidence for tool in DEFAULT_CATALOG.tools}


def test_library_only_install_does_not_import_optional_extras() -> None:
    """A library-only install must work: the core never imports the web or TUI stacks."""
    code = (
        "import sys, tracehunter;"
        "bad = [m for m in ('fastapi', 'uvicorn', 'textual', 'starlette') if m in sys.modules];"
        "print(','.join(bad))"
    )
    result = subprocess.run(  # noqa: S603 - fixed arguments, no untrusted input
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_version_is_a_string() -> None:
    assert isinstance(tracehunter.__version__, str) and tracehunter.__version__
