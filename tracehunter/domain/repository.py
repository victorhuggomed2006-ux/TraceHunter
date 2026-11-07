"""Trace persistence contract."""

from abc import ABC, abstractmethod
from typing import List, Optional

from tracehunter.domain.models import Trace

MAX_LIST_LIMIT = 1000


class TraceRepository(ABC):
    """Interface that every trace storage must implement."""

    @staticmethod
    def check_limit(limit: int) -> int:
        """Validate the `limit` of `list_traces`: reject negatives and cap it at 1000."""
        if limit < 0:
            raise ValueError("limit must be >= 0")
        return min(limit, MAX_LIST_LIMIT)

    @abstractmethod
    def save(self, trace: Trace) -> None:
        """Persist the trace, replacing any previous version with the same id."""

    @abstractmethod
    def get(self, trace_id: str) -> Optional[Trace]:
        """Return the trace with the given id, or None."""

    @abstractmethod
    def list_traces(self, limit: int = 50) -> List[Trace]:
        """List traces, most recent first (up to `limit`, at most 1000).

        Raise `ValueError` if `limit` is negative.
        """
