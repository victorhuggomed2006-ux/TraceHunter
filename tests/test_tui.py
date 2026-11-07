"""TUI tests: pure presentation logic and a smoke test with the real app."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Static, Tree  # noqa: E402

from tracehunter import InMemoryTraceRepository, Status, Trace, Tracer  # noqa: E402
from tracehunter.tui.app import TraceHunterApp  # noqa: E402
from tracehunter.tui.view import (  # noqa: E402
    children_map,
    format_duration,
    format_tokens,
    matches,
    relative_time,
    span_detail,
    span_label,
    split_project,
    status_icon,
    summary,
    trace_row,
    trace_tokens,
)


def _repo() -> InMemoryTraceRepository:
    repo = InMemoryTraceRepository()
    tracer = Tracer(repo)
    with tracer.trace("fix [the] bug"):
        with tracer.span("assistant", {"prompt": "hi [x]"}):
            with tracer.span("Bash: ls") as tool:
                tool.complete({"result": "file.txt"})
    try:
        with tracer.trace("broken flow"):
            with tracer.span("tool"):
                raise ValueError("boom")
    except ValueError:
        pass
    return repo


def _traces() -> List[Trace]:
    return _repo().list_traces()


class TestView:
    def test_duration_formats(self) -> None:
        assert format_duration(None) == "—"
        assert format_duration(1.44) == "1.4s"
        assert format_duration(125) == "2m05s"

    def test_icons_cover_every_status(self) -> None:
        for status in Status:
            assert status.value and status_icon(status)

    def test_tokens_format(self) -> None:
        assert format_tokens(950) == "950"
        assert format_tokens(12_400) == "12.4k"
        assert format_tokens(1_200_000) == "1.2M"

    def test_relative_time(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert relative_time(now, now) == "now"
        assert relative_time(now - timedelta(seconds=45), now) == "45s"
        assert relative_time(now - timedelta(minutes=5), now) == "5m"
        assert relative_time(now - timedelta(hours=3), now) == "3h"
        assert relative_time(now - timedelta(days=2), now) == "2d"

    def test_split_project(self) -> None:
        assert split_project("[MyProj] fix the bug") == ("MyProj", "fix the bug")
        assert split_project("no prefix") == ("", "no prefix")

    def test_trace_tokens_sum_model_usage(self) -> None:
        repo = InMemoryTraceRepository()
        tracer = Tracer(repo)
        with tracer.trace("t") as trace:
            with tracer.span("a", metadata={"input_tokens": 10, "output_tokens": 5}):
                pass
            with tracer.span("b", metadata={"input_tokens": 1, "output_tokens": 2}):
                pass
            with tracer.span("c", metadata={"input_tokens": "bad"}):
                pass
        assert trace_tokens(trace) == (11, 7)
        assert "↑" in summary([trace]) and "↓" in summary([trace])

    def test_summary_counts(self) -> None:
        text = summary(_traces())
        assert "2[/] traces" in text and "✖ 1" in text and "◐ 0" in text

    def test_filters(self) -> None:
        traces = _traces()
        assert [t.name for t in traces if matches(t, "BUG")] == ["fix [the] bug"]
        assert [t.name for t in traces if matches(t, "", failed_only=True)] == ["broken flow"]
        assert all(matches(t, "") for t in traces)

    def test_row_escapes_markup_in_user_text(self) -> None:
        row = trace_row(next(t for t in _traces() if "fix" in t.name))
        assert r"\[the]" in row[3]
        assert len(row) == 7

    def test_children_map_nests_tools_under_their_parent(self) -> None:
        trace = next(t for t in _traces() if "fix" in t.name)
        groups = children_map(trace)
        assert [s.name for s in groups[None]] == ["assistant"]
        parent_id = groups[None][0].span_id
        assert [s.name for s in groups[parent_id]] == ["Bash: ls"]

    def test_orphan_spans_go_to_the_root(self) -> None:
        trace = next(t for t in _traces() if "fix" in t.name)
        orphan = trace.spans[1]
        orphan._parent_span_id = "does-not-exist"
        assert orphan in children_map(trace)[None]

    def test_span_detail_and_label(self) -> None:
        span = next(t for t in _traces() if "fix" in t.name).spans[0]
        assert "prompt" in span_detail(span)
        assert "assistant" in span_label(span)


class TestApp:
    def test_app_lists_traces_and_builds_the_span_tree(self) -> None:
        async def scenario() -> None:
            app = TraceHunterApp(_repo(), refresh_seconds=60)
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one("#traces", DataTable)
                assert table.row_count == 2
                assert "2 traces" in str(app.query_one("#stats", Static).render())
                tree = app.query_one("#spans", Tree)
                assert tree.root.children, "the tree must have steps for the selected trace"
                await pilot.press("f")  # failures only
                await pilot.pause()
                assert table.row_count == 1
                await pilot.press("f")
                await pilot.press("slash")
                await pilot.press(*"broken")
                await pilot.pause()
                assert table.row_count == 1

        asyncio.run(scenario())

    def test_app_survives_an_empty_repository(self) -> None:
        async def scenario() -> None:
            app = TraceHunterApp(InMemoryTraceRepository(), refresh_seconds=60)
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.query_one("#traces", DataTable).row_count == 0
                await pilot.press("r")

        asyncio.run(scenario())


class TestNavigation:
    def test_help_opens_and_closes(self) -> None:
        async def scenario() -> None:
            app = TraceHunterApp(_repo(), refresh_seconds=60)
            async with app.run_test() as pilot:
                await pilot.pause()
                assert len(app.screen_stack) == 1
                await pilot.press("question_mark")
                await pilot.pause()
                assert len(app.screen_stack) == 2
                await pilot.press("escape")
                await pilot.pause()
                assert len(app.screen_stack) == 1

        asyncio.run(scenario())

    def test_j_and_k_move_the_cursor_and_enter_focuses_the_steps(self) -> None:
        async def scenario() -> None:
            app = TraceHunterApp(_repo(), refresh_seconds=60)
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one("#traces", DataTable)
                start = table.cursor_row
                await pilot.press("j")
                await pilot.pause()
                assert table.cursor_row == start + 1
                await pilot.press("k")
                await pilot.pause()
                assert table.cursor_row == start
                await pilot.press("enter")
                await pilot.pause()
                assert app.focused is app.query_one("#spans", Tree)

        asyncio.run(scenario())
