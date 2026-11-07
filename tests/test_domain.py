"""Unit tests for the domain layer: Span, Trace and TraceContext."""

import asyncio
from typing import List, Optional

import pytest

from tracehunter.domain.context import TraceContext
from tracehunter.domain.models import Span, Status, Trace


class TestSpan:
    def test_initial_state(self) -> None:
        span = Span("llm_call")
        assert span.status is Status.RUNNING
        assert span.end_time is None
        assert span.output_data is None
        assert span.duration_seconds is None
        assert span.span_id

    def test_span_ids_are_unique(self) -> None:
        assert Span("a").span_id != Span("b").span_id

    def test_complete_sets_output_and_status(self) -> None:
        span = Span("llm_call")
        span.complete({"answer": 42})
        assert span.status is Status.COMPLETED
        assert span.output_data == {"answer": 42}
        assert span.duration_seconds is not None and span.duration_seconds >= 0

    def test_fail_sets_status_and_error(self) -> None:
        span = Span("llm_call")
        span.fail("timeout")
        assert span.status is Status.FAILED
        assert span.metadata["error"] == "timeout"
        assert span.end_time is not None

    def test_metadata_is_encapsulated(self) -> None:
        span = Span("a")
        span.metadata["k"] = "v"  # only changes a copy
        assert span.metadata == {}
        span.set_metadata("k", "v")
        assert span.metadata == {"k": "v"}

    def test_attributes_are_read_only(self) -> None:
        span = Span("a")
        with pytest.raises(AttributeError):
            span.status = Status.FAILED  # type: ignore[misc]

    def test_dict_round_trip(self) -> None:
        span = Span("a", input_data={"q": 1}, metadata={"m": 2})
        span.complete({"r": 3})
        restored = Span.from_dict(span.to_dict())
        assert restored.to_dict() == span.to_dict()


class TestTrace:
    def test_initial_state(self) -> None:
        trace = Trace("request")
        assert trace.name == "request"
        assert trace.status is Status.RUNNING
        assert trace.spans == []
        assert trace.duration_seconds is None

    def test_add_span_associates_and_indexes(self) -> None:
        trace = Trace()
        span = Span("step")
        trace.add_span(span)
        assert span.trace_id == trace.trace_id
        assert trace.get_span(span.span_id) is span
        assert trace.spans == [span]

    def test_spans_property_is_a_copy(self) -> None:
        trace = Trace()
        trace.spans.append(Span("x"))
        assert trace.spans == []

    def test_finish_and_fail(self) -> None:
        done, broken = Trace(), Trace()
        done.finish()
        broken.fail()
        assert done.status is Status.COMPLETED
        assert broken.status is Status.FAILED
        assert done.duration_seconds is not None and done.duration_seconds >= 0

    def test_dict_round_trip_with_spans(self) -> None:
        trace = Trace("t")
        child = Span("s")
        child.complete({"ok": True})
        trace.add_span(child)
        trace.finish()
        assert Trace.from_dict(trace.to_dict()).to_dict() == trace.to_dict()


class TestTraceContext:
    @pytest.fixture
    def context(self) -> TraceContext:
        return TraceContext()

    def test_no_active_trace_initially(self, context: TraceContext) -> None:
        assert context.current_trace is None
        assert context.current_span is None

    def test_set_active_trace(self, context: TraceContext) -> None:
        trace = Trace("request")
        context.set_active_trace(trace)
        assert context.current_trace is trace
        context.set_active_trace(None)
        assert context.current_trace is None

    def test_pop_on_empty_stack_returns_none(self, context: TraceContext) -> None:
        assert context.pop_span() is None

    def test_push_then_pop_returns_same_span(self, context: TraceContext) -> None:
        span = Span("a")
        context.push_span(span)
        assert context.current_span is span
        assert context.pop_span() is span
        assert context.pop_span() is None

    def test_stack_is_lifo(self, context: TraceContext) -> None:
        first, second, third = Span("1"), Span("2"), Span("3")
        for span in (first, second, third):
            context.push_span(span)
        popped: list[Optional[Span]] = [context.pop_span() for _ in range(3)]
        assert popped == [third, second, first]

    def test_asyncio_tasks_have_isolated_stacks(self, context: TraceContext) -> None:
        async def worker(name: str) -> Optional[str]:
            context.push_span(Span(name))
            await asyncio.sleep(0)
            current = context.current_span
            return current.name if current else None

        async def main() -> List[Optional[str]]:
            return list(await asyncio.gather(worker("a"), worker("b")))

        assert asyncio.run(main()) == ["a", "b"]
        assert context.current_span is None
