"""In-memory repository, useful for tests and ephemeral use."""

from threading import Lock
from typing import Dict, List, Optional

from tracehunter.domain.models import Trace
from tracehunter.domain.repository import TraceRepository


class InMemoryTraceRepository(TraceRepository):
    """Keep the traces in a dictionary protected by a lock."""

    def __init__(self) -> None:
        self._traces: Dict[str, Trace] = {}
        self._lock = Lock()

    def save(self, trace: Trace) -> None:
        with self._lock:
            self._traces[trace.trace_id] = trace

    def get(self, trace_id: str) -> Optional[Trace]:
        with self._lock:
            return self._traces.get(trace_id)

    def list_traces(self, limit: int = 50) -> List[Trace]:
        limit = self.check_limit(limit)
        with self._lock:
            traces = list(self._traces.values())
        traces.sort(key=lambda t: (t.start_time, t.trace_id), reverse=True)
        return traces[:limit]
