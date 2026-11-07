"""Property-based tests (Hypothesis) for serialization and the span stack."""

from datetime import datetime, timezone
from typing import Any, Dict, List

from hypothesis import given
from hypothesis import strategies as st

from tracehunter.domain.context import TraceContext
from tracehunter.domain.models import Span, Status, Trace

# JSON-compatible values: this is what persistence actually stores.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-(2**31), 2**31) | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=10), children, max_size=3)
    ),
    max_leaves=8,
)
json_dicts = st.dictionaries(st.text(max_size=10), json_values, max_size=4)
moments = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(timezone.utc)
)


@st.composite
def spans(draw: st.DrawFn) -> Span:
    start = draw(moments)
    ended = draw(st.booleans())
    return Span(
        draw(st.text(min_size=1, max_size=20)),
        input_data=draw(st.none() | json_dicts),
        output_data=draw(st.none() | json_dicts),
        metadata=draw(json_dicts),
        start_time=start,
        end_time=start if ended else None,
        status=draw(st.sampled_from(Status)),
    )


@given(spans())
def test_span_round_trip(span: Span) -> None:
    assert Span.from_dict(span.to_dict()).to_dict() == span.to_dict()


@given(st.text(max_size=20), st.lists(spans(), max_size=5), st.sampled_from(Status))
def test_trace_round_trip(name: str, items: List[Span], status: Status) -> None:
    trace = Trace(name, status=status, spans=items)
    assert Trace.from_dict(trace.to_dict()).to_dict() == trace.to_dict()


@given(json_dicts)
def test_metadata_survives_json_unchanged(metadata: Dict[str, Any]) -> None:
    span = Span("s", metadata=metadata)
    assert Span.from_dict(span.to_dict()).metadata == metadata


@given(st.lists(st.text(min_size=1, max_size=5), max_size=20))
def test_context_stack_pops_in_reverse_order(names: List[str]) -> None:
    context = TraceContext()
    pushed = [Span(n) for n in names]
    for span in pushed:
        context.push_span(span)
    popped = [context.pop_span() for _ in pushed]
    assert popped == list(reversed(pushed))
    assert context.pop_span() is None
