"""Collector contract: read the local records of an AI tool and produce traces."""

from abc import ABC, abstractmethod
from typing import List

from tracehunter.domain.models import Trace


class Collector(ABC):
    """Read the history that an AI tool (CLI, editor, agent) keeps on disk."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the source tool (e.g. 'Claude Code')."""

    @abstractmethod
    def collect(self) -> List[Trace]:
        """Return the traces new or changed since the last call (all of them on the first call)."""
