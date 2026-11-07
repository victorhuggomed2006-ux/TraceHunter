"""Claude Code collector: turn the sessions recorded in ~/.claude/projects into traces.

Each prompt typed by a person becomes a trace. Inside it there is one span for each model
response (with model and tokens) and, as its children, one span for each tool used. Only a short
summary of what went in and out is stored, with secrets masked; the model's internal reasoning
("thinking") is never copied.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from tracehunter.domain.collector import Collector
from tracehunter.domain.models import Span, Status, Trace
from tracehunter.domain.redaction import clip, safe_text

logger = logging.getLogger("tracehunter")

Event = Dict[str, Any]

_ACTIVE_SECONDS = 120  # a turn with no news for longer than this is considered finished
_PATH_KEYS = {
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookEdit": ("notebook_path",),
}
_TOOL_KEYS = {
    "Bash": ("command", "description"),
    "Grep": ("pattern", "path", "glob"),
    "Glob": ("pattern", "path"),
    "WebFetch": ("url",),
    "WebSearch": ("query",),
    "Agent": ("description", "subagent_type"),
    "Task": ("description", "subagent_type"),
}


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _blocks(event: Event) -> List[Event]:
    """Content blocks of the message (plain text becomes a text block)."""
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _human_prompt(event: Event) -> Optional[str]:
    """Prompt text if the message was typed by a person; None for everything else
    (tool results, system notices, subagents, notifications)."""
    if event.get("type") != "user" or event.get("isSidechain") or event.get("isMeta"):
        return None
    origin = event.get("origin")
    if isinstance(origin, dict) and origin.get("kind") != "human":
        return None
    texts = [str(b.get("text", "")) for b in _blocks(event) if b.get("type") == "text"]
    text = "\n".join(texts).strip()
    if not text or text.startswith(("<", "[Request interrupted")):
        return None
    return text


def _read_events(path: Path) -> Iterator[Event]:
    """Read the `user` and `assistant` lines of the file, skipping invalid lines."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") in ("user", "assistant"):
                yield event


@dataclass
class _Turn:
    prompt_id: str
    started: datetime
    text: str
    project: str
    events: List[Event] = field(default_factory=list)


@dataclass
class _Call:
    """One model response (may span several lines of the file, with the same id)."""

    message_id: str
    model: str
    started: datetime
    ended: datetime
    usage: Dict[str, Any] = field(default_factory=dict)
    stop_reason: Optional[str] = None
    texts: List[str] = field(default_factory=list)
    tools: List[Event] = field(default_factory=list)


def _split_turns(events: Iterator[Event]) -> List[_Turn]:
    turns: List[_Turn] = []
    for event in events:
        started = _parse_time(event.get("timestamp"))
        prompt = _human_prompt(event)
        if prompt is not None and started is not None:
            project = Path(str(event.get("cwd") or "")).name or "claude"
            turns.append(
                _Turn(str(event.get("uuid") or started.isoformat()), started, prompt, project)
            )
        elif turns:
            turns[-1].events.append(event)
    return turns


def _absorb(call: _Call, event: Event, message: Event, when: datetime) -> None:
    """Add a line of the file (a piece of the response) to the matching call."""
    call.ended = max(call.ended, when)
    call.usage = message.get("usage") or call.usage
    call.stop_reason = message.get("stop_reason") or call.stop_reason
    for block in _blocks(event):
        kind = block.get("type")
        if kind == "text":
            call.texts.append(str(block.get("text", "")))
        elif kind == "tool_use":
            call.tools.append(block)


def _collect_calls(events: List[Event]) -> List[_Call]:
    calls: Dict[str, _Call] = {}
    for event in events:
        when = _parse_time(event.get("timestamp"))
        message = event.get("message")
        if event.get("type") != "assistant" or when is None or not isinstance(message, dict):
            continue
        key = str(message.get("id") or event.get("uuid"))
        call = calls.setdefault(key, _Call(key, str(message.get("model") or "?"), when, when))
        _absorb(call, event, message, when)
    return list(calls.values())


def _tool_results(events: List[Event]) -> Dict[str, Tuple[datetime, Event]]:
    results: Dict[str, Tuple[datetime, Event]] = {}
    for event in events:
        when = _parse_time(event.get("timestamp"))
        if event.get("type") != "user" or when is None:
            continue
        for block in _blocks(event):
            if block.get("type") == "tool_result" and block.get("tool_use_id"):
                results[str(block["tool_use_id"])] = (when, block)
    return results


def _result_text(block: Event) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""


def _tool_input(name: str, data: Any) -> Dict[str, Any]:
    """Short, masked summary of the call (without file contents)."""
    if not isinstance(data, dict):
        return {"input": safe_text(data, 200)}
    keys = _PATH_KEYS.get(name) or _TOOL_KEYS.get(name) or tuple(data)[:6]
    return {k: safe_text(data[k], 300) for k in keys if k in data}


def _tool_label(name: str, summary: Dict[str, Any]) -> str:
    target = next(iter(summary.values()), "")
    return f"{name}: {clip(str(target), 60)}" if target else name


def _llm_span(call: _Call) -> Span:
    usage = call.usage
    return Span(
        f"assistant · {call.model}",
        span_id=call.message_id,
        output_data={"text": safe_text(" ".join(call.texts), 400)} if call.texts else None,
        start_time=call.started,
        end_time=call.ended,
        metadata={
            "model": call.model,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "stop_reason": call.stop_reason,
        },
        status=Status.COMPLETED,
    )


def _tool_span(
    call: _Call,
    tool: Event,
    tool_id: str,
    result: Optional[Tuple[datetime, Event]],
    active: bool,
    fallback_end: datetime,
) -> Span:
    name = str(tool.get("name") or "tool")
    summary = _tool_input(name, tool.get("input"))
    base: Dict[str, Any] = {
        "name": _tool_label(name, summary),
        "span_id": tool_id,
        "parent_span_id": call.message_id,
        "input_data": summary,
        "start_time": call.ended,
    }
    if result is None:
        status = Status.RUNNING if active else Status.COMPLETED
        return Span(end_time=None if active else fallback_end, status=status, **base)
    ended, block = result
    text = safe_text(_result_text(block), 300)
    if block.get("is_error"):
        return Span(end_time=ended, status=Status.FAILED, metadata={"error": text}, **base)
    return Span(end_time=ended, status=Status.COMPLETED, output_data={"result": text}, **base)


def _build_trace(session_id: str, turn: _Turn, active: bool) -> Trace:
    calls = _collect_calls(turn.events)
    results = _tool_results(turn.events)
    times = [t for t in (_parse_time(e.get("timestamp")) for e in turn.events) if t]
    last = max([turn.started, *times])
    first_line = turn.text.splitlines()[0] if turn.text else "(prompt)"
    trace = Trace(
        f"[{turn.project}] {safe_text(first_line, 120)}",
        trace_id=f"claude-code:{session_id}:{turn.prompt_id}",
        start_time=turn.started,
        end_time=None if active else last,
        status=Status.RUNNING if active else Status.COMPLETED,
    )
    for call in calls:
        _add_span(trace, _llm_span(call))
        for index, tool in enumerate(call.tools):
            tool_id = str(tool.get("id") or f"{call.message_id}:tool{index}")
            result = results.get(tool_id)
            _add_span(trace, _tool_span(call, tool, tool_id, result, active, last))
    return trace


def _add_span(trace: Trace, span: Span) -> None:
    """Add a span; skip a duplicate id (a repeated line in a session file) instead of failing."""
    try:
        trace.add_span(span)
    except ValueError:
        logger.debug("skipping duplicate span id %s", span.span_id)


def _modified_time(path: Path) -> float:
    """Modification time, or 0 if the file vanished in the meantime."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def default_projects_dir() -> Path:
    """Sessions folder: $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


class ClaudeCodeCollector(Collector):
    """Read the recent Claude Code sessions and convert them into traces."""

    def __init__(self, projects_dir: Optional[Path] = None, max_files: int = 8) -> None:
        self._projects_dir = projects_dir or default_projects_dir()
        self._max_files = max_files
        self._seen: Dict[Path, Tuple[int, int]] = {}
        self._active: Set[Path] = set()

    @property
    def name(self) -> str:
        return "Claude Code"

    def _recent_files(self) -> List[Path]:
        if not self._projects_dir.is_dir():
            return []
        files = list(self._projects_dir.glob("*/*.jsonl"))
        files.sort(key=_modified_time, reverse=True)
        return files[: self._max_files]

    def collect(self) -> List[Trace]:
        traces: List[Trace] = []
        for path in self._recent_files():
            try:
                stat = path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
                if self._seen.get(path) == stamp and path not in self._active:
                    continue
                traces.extend(self._parse(path, stat.st_mtime))
                self._seen[path] = stamp
            except Exception:  # noqa: BLE001 - one bad session must not stop the others
                logger.warning("could not read session %s", path.name, exc_info=True)
        return traces

    def _parse(self, path: Path, modified: float) -> List[Trace]:
        turns = _split_turns(_read_events(path))
        recent = time.time() - modified < _ACTIVE_SECONDS
        traces = [
            _build_trace(path.stem, turn, recent and index == len(turns) - 1)
            for index, turn in enumerate(turns)
        ]
        if recent and turns:
            self._active.add(path)
        else:
            self._active.discard(path)
        return traces
