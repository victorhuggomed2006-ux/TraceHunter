"""SQLite repository: local storage, nothing is sent elsewhere."""

import contextlib
import json
import logging
import os
import sqlite3
from threading import Lock
from typing import List, Optional

from tracehunter.domain.models import Trace
from tracehunter.domain.repository import TraceRepository

logger = logging.getLogger("tracehunter")


class SQLiteTraceRepository(TraceRepository):
    """Persist each trace as JSON in a SQLite file (or `:memory:`).

    The database file is readable only by its owner (0600), since traces may contain prompts.
    """

    def __init__(self, path: str = "tracehunter.db") -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        if path != ":memory:":
            # On Windows chmod has almost no effect; the folder ACLs are what count.
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
        self._lock = Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id   TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    status     TEXT NOT NULL,
                    start_ts   REAL NOT NULL,
                    data       TEXT NOT NULL
                )
                """
            )

    def save(self, trace: Trace) -> None:
        payload = trace.to_dict()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO traces (trace_id, name, status, start_ts, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    trace.trace_id,
                    trace.name,
                    trace.status.value,
                    trace.start_time.timestamp(),
                    json.dumps(payload, allow_nan=False),
                ),
            )

    def get(self, trace_id: str) -> Optional[Trace]:
        with self._lock:
            row = self._connection.execute(
                "SELECT data FROM traces WHERE trace_id = ?", (trace_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def list_traces(self, limit: int = 50) -> List[Trace]:
        limit = self.check_limit(limit)
        with self._lock:
            rows = self._connection.execute(
                "SELECT data FROM traces ORDER BY start_ts DESC, trace_id DESC LIMIT ?", (limit,)
            ).fetchall()
        loaded = (self._load(row[0]) for row in rows)
        return [trace for trace in loaded if trace is not None]

    @staticmethod
    def _load(raw: str) -> Optional[Trace]:
        """Rebuild a trace; corrupted rows are logged and skipped."""
        try:
            return Trace.from_dict(json.loads(raw))
        except (ValueError, KeyError, TypeError):
            logger.warning("corrupted trace skipped in the database", exc_info=True)
            return None

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._connection.close()
