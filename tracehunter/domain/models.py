"""TraceHunter domain entities: Span and Trace."""

import math
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

_MAX_JSON_DEPTH = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize to UTC; naive datetimes are treated as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _parse(value: Optional[str]) -> Optional[datetime]:
    return _aware(datetime.fromisoformat(value)) if value else None


def to_jsonable(value: Any, _depth: int = 0) -> Any:
    """Convert any value into something serializable as strict JSON.

    Dictionary keys become text, NaN/Infinity become text and unknown
    objects become `str(obj)`; never raises.
    """
    if _depth > _MAX_JSON_DEPTH:
        return "<max depth>"
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v, _depth + 1) for v in value]
    return _scalar_to_jsonable(value)


def _scalar_to_jsonable(value: Any) -> Any:
    """Part of `to_jsonable` for values that are not collections."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break recording
        return f"<{type(value).__name__}>"


class Status(str, Enum):
    """Possible states of a Span or Trace."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Span:
    """Smallest unit of tracked execution within an AI flow."""

    def __init__(
        self,
        name: str,
        *,
        span_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: Status = Status.RUNNING,
    ) -> None:
        self._name = name
        self._span_id = span_id or _new_id()
        self._trace_id = trace_id
        self._parent_span_id = parent_span_id
        self._input_data = input_data
        self._output_data = output_data
        self._start_time = _aware(start_time) or _utcnow()
        self._end_time = _aware(end_time)
        self._metadata: Dict[str, Any] = dict(metadata or {})
        self._status = status

    @property
    def name(self) -> str:
        return self._name

    @property
    def span_id(self) -> str:
        return self._span_id

    @property
    def trace_id(self) -> Optional[str]:
        return self._trace_id

    @property
    def parent_span_id(self) -> Optional[str]:
        return self._parent_span_id

    @property
    def input_data(self) -> Optional[Dict[str, Any]]:
        return self._input_data

    @property
    def output_data(self) -> Optional[Dict[str, Any]]:
        return self._output_data

    @property
    def start_time(self) -> datetime:
        return self._start_time

    @property
    def end_time(self) -> Optional[datetime]:
        return self._end_time

    @property
    def metadata(self) -> Dict[str, Any]:
        """Copy of the metadata; use `set_metadata` to change it."""
        return dict(self._metadata)

    @property
    def status(self) -> Status:
        return self._status

    @property
    def duration_seconds(self) -> Optional[float]:
        """Span duration in seconds, or None while it is still running."""
        if self._end_time is None:
            return None
        return (self._end_time - self._start_time).total_seconds()

    def set_metadata(self, key: str, value: Any) -> None:
        """Record a key/value pair in the span metadata."""
        self._metadata[key] = value

    def attach_to_trace(self, trace_id: str) -> None:
        """Attach the span to a trace."""
        self._trace_id = trace_id

    def complete(self, output_data: Optional[Dict[str, Any]] = None) -> None:
        """Finish the span successfully, recording the output and the end time."""
        self._output_data = output_data
        self._end_time = _utcnow()
        self._status = Status.COMPLETED

    def fail(self, error_message: str) -> None:
        """Mark the span as failed and store the error in the metadata."""
        self._end_time = _utcnow()
        self._status = Status.FAILED
        self._metadata["error"] = error_message

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the span to a dictionary compatible with strict JSON."""
        return {
            "name": self._name,
            "span_id": self._span_id,
            "trace_id": self._trace_id,
            "parent_span_id": self._parent_span_id,
            "input_data": to_jsonable(self._input_data),
            "output_data": to_jsonable(self._output_data),
            "start_time": _iso(self._start_time),
            "end_time": _iso(self._end_time),
            "metadata": to_jsonable(self._metadata),
            "status": self._status.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Span":
        """Rebuild a span from `to_dict`."""
        return cls(
            data["name"],
            span_id=data["span_id"],
            trace_id=data.get("trace_id"),
            parent_span_id=data.get("parent_span_id"),
            input_data=data.get("input_data"),
            output_data=data.get("output_data"),
            start_time=_parse(data["start_time"]),
            end_time=_parse(data.get("end_time")),
            metadata=data.get("metadata"),
            status=Status(data["status"]),
        )


class Trace:
    """Group the Spans of a single request or flow. Safe to use across threads."""

    def __init__(
        self,
        name: str = "default_trace",
        *,
        trace_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: Status = Status.RUNNING,
        spans: Optional[List[Span]] = None,
    ) -> None:
        self._name = name
        self._trace_id = trace_id or _new_id()
        self._start_time = _aware(start_time) or _utcnow()
        self._end_time = _aware(end_time)
        self._status = status
        self._lock = threading.Lock()
        self._spans: Dict[str, Span] = {}
        for span in spans or []:
            self.add_span(span)

    @property
    def name(self) -> str:
        return self._name

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def start_time(self) -> datetime:
        return self._start_time

    @property
    def end_time(self) -> Optional[datetime]:
        return self._end_time

    @property
    def status(self) -> Status:
        return self._status

    @property
    def spans(self) -> List[Span]:
        """Spans of the trace in insertion order (a copy)."""
        with self._lock:
            return list(self._spans.values())

    @property
    def duration_seconds(self) -> Optional[float]:
        """Trace duration in seconds, or None while it is still running."""
        if self._end_time is None:
            return None
        return (self._end_time - self._start_time).total_seconds()

    def add_span(self, span: Span) -> None:
        """Add a span to the trace and attach it to it.

        Raise `ValueError` if a span with the same id already exists.
        """
        with self._lock:
            if span.span_id in self._spans:
                raise ValueError(f"duplicate span_id: {span.span_id}")
            span.attach_to_trace(self._trace_id)
            self._spans[span.span_id] = span

    def get_span(self, span_id: str) -> Optional[Span]:
        """Return the span with the given id, or None."""
        with self._lock:
            return self._spans.get(span_id)

    def finish(self) -> None:
        """Finish the trace successfully."""
        self._end_time = _utcnow()
        self._status = Status.COMPLETED

    def fail(self) -> None:
        """Finish the trace as failed."""
        self._end_time = _utcnow()
        self._status = Status.FAILED

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the trace (with its spans) to a dictionary compatible with strict JSON."""
        return {
            "name": self._name,
            "trace_id": self._trace_id,
            "start_time": _iso(self._start_time),
            "end_time": _iso(self._end_time),
            "status": self._status.value,
            "spans": [span.to_dict() for span in self.spans],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trace":
        """Rebuild a trace from `to_dict`."""
        return cls(
            data["name"],
            trace_id=data["trace_id"],
            start_time=_parse(data["start_time"]),
            end_time=_parse(data.get("end_time")),
            status=Status(data["status"]),
            spans=[Span.from_dict(item) for item in data.get("spans", [])],
        )
