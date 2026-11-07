"""Execution context: active trace and span stack, isolated per thread/task."""

from contextvars import ContextVar, Token
from typing import Optional, Tuple

from tracehunter.domain.models import Span, Trace

TraceTokens = Tuple["Token[Optional[Trace]]", "Token[Tuple[Span, ...]]"]


class TraceContext:
    """
    Manage the active trace and the stack of running spans.

    The state lives in `ContextVar`s, so each thread and each asyncio task
    sees its own stack without affecting the others.
    """

    def __init__(self) -> None:
        self._current_trace: ContextVar[Optional[Trace]] = ContextVar(
            "tracehunter_current_trace", default=None
        )
        self._span_stack: ContextVar[Tuple[Span, ...]] = ContextVar(
            "tracehunter_span_stack", default=()
        )

    @property
    def current_trace(self) -> Optional[Trace]:
        """Return the currently active trace."""
        return self._current_trace.get()

    @property
    def current_span(self) -> Optional[Span]:
        """Return the span on top of the stack without removing it."""
        stack = self._span_stack.get()
        return stack[-1] if stack else None

    def set_active_trace(self, trace: Optional[Trace]) -> None:
        """Set the active trace; None deactivates it."""
        self._current_trace.set(trace)

    def activate(self, trace: Trace) -> TraceTokens:
        """Activate the trace with an empty span stack (isolated from any outer trace).

        Return the tokens that `deactivate` uses to restore the previous state.
        """
        return self._current_trace.set(trace), self._span_stack.set(())

    def deactivate(self, tokens: TraceTokens) -> None:
        """Restore the trace and stack that existed before `activate`."""
        trace_token, stack_token = tokens
        try:
            self._current_trace.reset(trace_token)
            self._span_stack.reset(stack_token)
        except ValueError:
            # Token created in another context (e.g. closed by another task): deactivate everything.
            self._current_trace.set(None)
            self._span_stack.set(())

    def push_span(self, span: Span) -> None:
        """Push a span, making it the currently active span."""
        self._span_stack.set(self._span_stack.get() + (span,))

    def pop_span(self) -> Optional[Span]:
        """Remove and return the span on top of the stack, or None if it is empty."""
        stack = self._span_stack.get()
        if not stack:
            return None
        self._span_stack.set(stack[:-1])
        return stack[-1]
