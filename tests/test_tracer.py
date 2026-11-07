"""Tests for the Tracer and the repositories."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tracehunter import (
    InMemoryTraceRepository,
    NoActiveTraceError,
    SQLiteTraceRepository,
    Status,
    Trace,
    Tracer,
)
from tracehunter.domain.repository import TraceRepository


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest) -> TraceRepository:
    if request.param == "memory":
        return InMemoryTraceRepository()
    repo = SQLiteTraceRepository(":memory:")
    request.addfinalizer(repo.close)
    return repo


@pytest.fixture
def tracer(repository: TraceRepository) -> Tracer:
    return Tracer(repository)


class TestTracer:
    def test_trace_is_saved_and_completed(self, tracer, repository) -> None:
        with tracer.trace("req") as trace:
            pass
        saved = repository.get(trace.trace_id)
        assert saved is not None
        assert saved.status is Status.COMPLETED
        assert tracer.context.current_trace is None

    def test_nested_spans_link_parents(self, tracer) -> None:
        with tracer.trace("req") as trace:
            with tracer.span("outer") as outer:
                with tracer.span("inner") as inner:
                    pass
        assert outer.parent_span_id is None
        assert inner.parent_span_id == outer.span_id
        assert len(trace.spans) == 2
        assert all(s.status is Status.COMPLETED for s in trace.spans)
        assert tracer.context.current_span is None

    def test_span_outside_trace_raises(self, tracer) -> None:
        with pytest.raises(NoActiveTraceError):
            with tracer.span("orphan"):
                pass

    def test_exception_fails_span_and_trace(self, tracer, repository) -> None:
        with pytest.raises(ValueError):
            with tracer.trace("req") as trace:
                with tracer.span("boom") as span:
                    raise ValueError("x")
        assert span.status is Status.FAILED
        assert "ValueError: x" in span.metadata["error"]
        assert repository.get(trace.trace_id).status is Status.FAILED
        assert tracer.context.current_span is None

    def test_span_output_set_by_user_is_kept(self, tracer) -> None:
        with tracer.trace("req"):
            with tracer.span("llm") as span:
                span.complete({"tokens": 10})
        assert span.output_data == {"tokens": 10}

    def test_observe_sync(self, tracer) -> None:
        @tracer.observe()
        def add(a: int, b: int) -> int:
            return a + b

        with tracer.trace("req") as trace:
            assert add(1, b=2) == 3
        span = trace.spans[0]
        assert span.input_data == {"arguments": {"a": "1", "b": "2"}}
        assert span.output_data == {"result": "3"}

    def test_observe_async(self, tracer) -> None:
        @tracer.observe("fetch")
        async def fetch() -> str:
            await asyncio.sleep(0)
            return "ok"

        async def main() -> Trace:
            with tracer.trace("req") as trace:
                await fetch()
            return trace

        trace = asyncio.run(main())
        assert trace.spans[0].name == "fetch"
        assert trace.spans[0].output_data == {"result": "'ok'"}

    def test_observe_records_failure_and_reraises(self, tracer) -> None:
        @tracer.observe()
        def broken() -> None:
            raise RuntimeError("no")

        with pytest.raises(RuntimeError):
            with tracer.trace("req") as trace:
                broken()
        assert trace.spans[0].status is Status.FAILED


class TestRepositories:
    def test_get_missing_returns_none(self, repository) -> None:
        assert repository.get("nope") is None

    def test_save_replaces_existing(self, repository) -> None:
        trace = Trace("t")
        repository.save(trace)
        trace.finish()
        repository.save(trace)
        assert len(repository.list_traces()) == 1
        assert repository.get(trace.trace_id).status is Status.COMPLETED

    def test_list_is_newest_first_and_limited(self, repository) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        traces = [Trace(f"t{i}", start_time=base + timedelta(seconds=i)) for i in range(3)]
        for t in traces:
            repository.save(t)
        names = [t.name for t in repository.list_traces(limit=2)]
        assert names == ["t2", "t1"]

    def test_spans_survive_persistence(self, tracer, repository) -> None:
        with tracer.trace("req") as trace:
            with tracer.span("a", {"q": "hi"}):
                pass
        loaded = repository.get(trace.trace_id)
        assert [s.name for s in loaded.spans] == ["a"]
        assert loaded.spans[0].input_data == {"q": "hi"}
