"""Synchronization: run a collector periodically and save only what changed to the repository."""

import json
import logging
import threading
from typing import Dict, Optional

from tracehunter.domain.collector import Collector
from tracehunter.domain.repository import TraceRepository

logger = logging.getLogger("tracehunter")


class CollectorSync:
    """Call `collector.collect()` every `interval` seconds and save the changed traces."""

    def __init__(self, collector: Collector, repository: TraceRepository, interval: float = 2.0):
        self._collector = collector
        self._repository = repository
        self._interval = interval
        self._digests: Dict[str, int] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def sync_once(self) -> int:
        """Collect and save once. Return how many traces were saved (new or changed)."""
        saved = 0
        for trace in self._collector.collect():
            digest = hash(json.dumps(trace.to_dict(), sort_keys=True))
            if self._digests.get(trace.trace_id) == digest:
                continue
            self._repository.save(trace)
            self._digests[trace.trace_id] = digest
            saved += 1
        return saved

    def start(self) -> None:
        """Start synchronization in the background (daemon thread)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="tracehunter-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to stop and wait for it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.sync_once()
            except Exception:  # noqa: BLE001 - synchronization must never bring the server down
                logger.exception("failed to sync %s", self._collector.name)
