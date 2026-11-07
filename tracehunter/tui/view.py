"""TUI presentation logic, with no Textual dependency (testable without opening a terminal)."""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from rich.markup import escape

from tracehunter.domain.models import Span, Status, Trace

_ICONS = {
    Status.COMPLETED: "[green]✔[/]",
    Status.FAILED: "[bold red]✖[/]",
    Status.RUNNING: "[bold yellow]◐[/]",
}
_PROJECT = re.compile(r"^\[([^\]]+)\]\s*(.*)$", re.S)
_SLOW_SECONDS = 30.0


def status_icon(status: Status) -> str:
    """Colored icon (Rich markup): ✔ completed, ✖ failed, ◐ running."""
    return _ICONS.get(status, "[dim]?[/]")


def format_duration(seconds: Optional[float]) -> str:
    """'1.4s', '2m03s' or '—' when not finished yet."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m{rest:02d}s"


def format_tokens(count: int) -> str:
    """'950', '12.4k' or '1.2M'."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


def relative_time(moment: datetime, now: Optional[datetime] = None) -> str:
    """'now', '5m', '3h' or '2d' since `moment`."""
    seconds = int(((now or datetime.now(timezone.utc)) - moment).total_seconds())
    if seconds < 10:
        return "now"
    for limit, unit, size in ((60, "s", 1), (3600, "m", 60), (86400, "h", 3600)):
        if seconds < limit:
            return f"{seconds // size}{unit}"
    return f"{seconds // 86400}d"


def clip(text: str, limit: int) -> str:
    """Cut the text to `limit` characters, using an ellipsis."""
    return text if len(text) <= limit else text[: max(limit - 1, 1)] + "…"


def split_project(name: str) -> Tuple[str, str]:
    """Split '[Project] text' into ('Project', 'text'); without a prefix, the project is empty."""
    match = _PROJECT.match(name)
    return (match.group(1), match.group(2)) if match else ("", name)


def _usage(span: Span, key: str) -> int:
    value = span.metadata.get(key)
    return value if isinstance(value, int) else 0


def trace_tokens(trace: Trace) -> Tuple[int, int]:
    """Sum of tokens (input, output) of the model responses in the trace."""
    return trace.token_usage


COLUMNS = ("", "when", "project", "prompt", "steps", "tok", "time")


def trace_row(trace: Trace, prompt_width: int = 60) -> Tuple[str, ...]:
    """Table cells: icon, when, project, prompt, steps, output tokens and duration."""
    project, prompt = split_project(trace.name)
    seconds = trace.duration_seconds
    slow = seconds is not None and seconds > _SLOW_SECONDS
    duration = format_duration(seconds)
    _, out_tokens = trace_tokens(trace)
    return (
        status_icon(trace.status),
        f"[dim]{relative_time(trace.start_time)}[/]",
        f"[cyan]{escape(clip(project, 14))}[/]",
        escape(clip(" ".join(prompt.split()), prompt_width)),
        str(len(trace.spans)),
        format_tokens(out_tokens) if out_tokens else "[dim]·[/]",
        f"[yellow]{duration}[/]" if slow else duration,
    )


def matches(trace: Trace, query: str, failed_only: bool = False) -> bool:
    """True if the trace passes the filters (text in the name and/or failed only)."""
    if (
        failed_only
        and trace.status is not Status.FAILED
        and not any(s.status is Status.FAILED for s in trace.spans)
    ):
        return False
    return query.lower() in trace.name.lower() if query else True


def summary(traces: Sequence[Trace]) -> str:
    """Totals line at the top (Rich markup), with summed tokens."""
    failed = sum(1 for t in traces if t.status is Status.FAILED)
    running = sum(1 for t in traces if t.status is Status.RUNNING)
    tokens = [trace_tokens(t) for t in traces]
    tokens_in, tokens_out = sum(t[0] for t in tokens), sum(t[1] for t in tokens)
    return (
        f"[b]{len(traces)}[/] traces   [red]✖ {failed}[/] failed   [yellow]◐ {running}[/] running"
        f"   [dim]tokens[/] ↑{format_tokens(tokens_in)} ↓{format_tokens(tokens_out)}"
    )


def span_label(span: Span) -> str:
    """Label of a tree node: icon, kind, name, duration and tokens."""
    kind = "[b cyan]◆[/]" if span.name.startswith("assistant") else "[blue]▸[/]"
    out_tokens = _usage(span, "output_tokens")
    extra = f" · {format_tokens(out_tokens)} tok" if out_tokens else ""
    name = escape(clip(span.name, 60))
    elapsed = format_duration(span.duration_seconds)
    return f"{status_icon(span.status)} {kind} {name} [dim]{elapsed}{extra}[/]"


def children_map(trace: Trace) -> Dict[Optional[str], List[Span]]:
    """Group the spans by parent. Spans whose parent does not exist go to the root (key None)."""
    spans = trace.spans
    known = {s.span_id for s in spans}
    grouped: Dict[Optional[str], List[Span]] = {}
    for span in spans:
        parent = span.parent_span_id if span.parent_span_id in known else None
        grouped.setdefault(parent, []).append(span)
    return grouped


def span_header(span: Span) -> str:
    """Header of the details panel (Rich markup)."""
    return (
        f"[bold]{escape(span.name)}[/]\n"
        f"{status_icon(span.status)} {span.status.value.lower()}  ·  "
        f"{format_duration(span.duration_seconds)}"
    )


def span_sections(span: Span) -> List[Tuple[str, str]]:
    """Detail sections (title, formatted JSON): whichever of metadata, input and output exist."""
    data = span.to_dict()
    sections = []
    for title, key in (
        ("metadata", "metadata"),
        ("input", "input_data"),
        ("output", "output_data"),
    ):
        if data[key]:
            sections.append(
                (title, json.dumps(data[key], ensure_ascii=False, indent=2, default=str))
            )
    return sections


def span_detail(span: Span) -> str:
    """Detail as plain text (header + sections); used in tests and as a fallback."""
    parts = [span_header(span)]
    for title, body in span_sections(span):
        parts.append(f"[cyan]{title}[/]\n{escape(body)}")
    return "\n\n".join(parts)
