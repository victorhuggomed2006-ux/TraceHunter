"""TraceHunter: local observability for AI applications.

Record what your code does (a *trace* made of *spans*)::

    from tracehunter import SQLiteTraceRepository, Tracer

    tracer = Tracer(SQLiteTraceRepository("tracehunter.db"))

    @tracer.observe()
    def retrieve(question): ...

    with tracer.trace("question"):
        retrieve("what is RAG?")

Read AI command-line tools' own history instead of instrumenting code::

    from tracehunter import ClaudeCodeCollector, CollectorSync, SQLiteTraceRepository

    repository = SQLiteTraceRepository("claude.db")
    CollectorSync(ClaudeCodeCollector(), repository).sync_once()

Then ``tracehunter tracehunter.db`` opens the local web interface and ``tracehunter tui`` the
terminal one. The web app factory lives in ``tracehunter.api.app`` (it needs the ``server`` extra).
"""

from importlib.metadata import PackageNotFoundError, version

from tracehunter.application.collector_sync import CollectorSync
from tracehunter.application.tracer import NoActiveTraceError, Tracer
from tracehunter.catalog import DEFAULT_CATALOG, Catalog, CliTool, Confidence
from tracehunter.domain.collector import Collector
from tracehunter.domain.context import TraceContext
from tracehunter.domain.models import Span, Status, Trace
from tracehunter.domain.redaction import redact, safe_text
from tracehunter.domain.repository import TraceRepository
from tracehunter.infrastructure.claude_code_collector import ClaudeCodeCollector
from tracehunter.infrastructure.memory_repository import InMemoryTraceRepository
from tracehunter.infrastructure.sqlite_repository import SQLiteTraceRepository

try:
    __version__ = version("tracehunter")
except PackageNotFoundError:  # running straight from the source tree, not installed
    __version__ = "0+unknown"

__all__ = [
    "DEFAULT_CATALOG",
    "Catalog",
    "ClaudeCodeCollector",
    "CliTool",
    "Collector",
    "CollectorSync",
    "Confidence",
    "InMemoryTraceRepository",
    "NoActiveTraceError",
    "SQLiteTraceRepository",
    "Span",
    "Status",
    "Trace",
    "TraceContext",
    "TraceRepository",
    "Tracer",
    "__version__",
    "redact",
    "safe_text",
]
