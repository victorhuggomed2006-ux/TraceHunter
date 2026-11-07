"""Tracer: high-level API to instrument code with traces and spans."""

import functools
import inspect
import logging
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional, Tuple, TypeVar

from tracehunter.domain.context import TraceContext
from tracehunter.domain.models import Span, Status, Trace
from tracehunter.domain.repository import TraceRepository

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger("tracehunter")

_MAX_REPR = 1000
_MASK = "***"
# Arguments whose name contains any of these fragments have their value masked when recorded.
_SENSITIVE_NAMES = (
    "key",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "credential",
    "cookie",
)


class NoActiveTraceError(RuntimeError):
    """Raised when a span is opened outside a trace."""


def _safe_repr(value: Any) -> str:
    """`repr` that never raises and limits the text length."""
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 - a broken __repr__ must not break the user's function
        return f"<{type(value).__name__}: repr failed>"
    return text if len(text) <= _MAX_REPR else text[:_MAX_REPR] + "…"


def _describe_arguments(
    func: Callable[..., Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]
) -> Dict[str, Any]:
    """Describe the call arguments by name, masking those that look like secrets."""
    named: Dict[str, Any] = {}
    try:
        signature = inspect.signature(func)
        for pname, value in signature.bind_partial(*args, **kwargs).arguments.items():
            if signature.parameters[pname].kind is inspect.Parameter.VAR_KEYWORD:
                named.update(value)  # **kwargs: each key becomes a named argument
            else:
                named[pname] = value
    except (TypeError, ValueError):
        named = {f"arg{i}": value for i, value in enumerate(args)}
        named.update(kwargs)
    return {
        name: _MASK if any(s in name.lower() for s in _SENSITIVE_NAMES) else _safe_repr(value)
        for name, value in named.items()
    }


class Tracer:
    """Create traces and spans, keep the context and persist the result."""

    def __init__(self, repository: TraceRepository, context: Optional[TraceContext] = None) -> None:
        self._repository = repository
        self._context = context or TraceContext()

    @property
    def context(self) -> TraceContext:
        """Execution context (active trace and span stack) of this tracer."""
        return self._context

    @contextmanager
    def trace(self, name: str) -> Iterator[Trace]:
        """Open a trace; on exit, finish and persist it (as FAILED if an exception occurred).

        The trace starts with an empty span stack, even when opened inside another trace.
        A failure to save is logged and never hides the user's exception.
        """
        trace = Trace(name)
        tokens = self._context.activate(trace)
        try:
            yield trace
        except BaseException:
            trace.fail()
            raise
        else:
            trace.finish()
        finally:
            self._context.deactivate(tokens)
            self._save_quietly(trace)

    def _save_quietly(self, trace: Trace) -> None:
        try:
            self._repository.save(trace)
        except Exception:  # noqa: BLE001 - observability must not bring the application down
            logger.exception("failed to save trace %s", trace.trace_id)

    @contextmanager
    def span(
        self,
        name: str,
        input_data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Span]:
        """Open a child span of the current span inside the active trace."""
        trace = self._context.current_trace
        if trace is None:
            raise NoActiveTraceError(f"span '{name}' opened outside a trace")
        parent = self._context.current_span
        span = Span(
            name,
            parent_span_id=parent.span_id if parent else None,
            input_data=input_data,
            metadata=metadata,
        )
        trace.add_span(span)
        self._context.push_span(span)
        try:
            yield span
        except BaseException as exc:
            span.fail(f"{type(exc).__name__}: {exc}")
            raise
        else:
            if span.status is Status.RUNNING:
                span.complete()
        finally:
            self._context.pop_span()

    def observe(self, name: Optional[str] = None, *, capture_io: bool = True) -> Callable[[F], F]:
        """Decorator that records each call of the function as a span.

        Arguments are recorded by name (with `repr` limited to 1000 characters) and
        those that look like secrets (key, token, password...) are masked. Use
        `capture_io=False` to record neither arguments nor result.
        Generators are not supported: use `tracer.span()` inside them.

        A call made with no active trace (for example from a new thread, which does not
        inherit the trace) just runs the function untraced; the instrumentation never raises.
        """

        def decorator(func: F) -> F:
            if inspect.isgeneratorfunction(func) or inspect.isasyncgenfunction(func):
                raise TypeError(
                    f"observe() does not support generators ({func.__qualname__}); "
                    "use tracer.span() inside the function"
                )
            span_name = name or func.__qualname__

            def inputs(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                return (
                    {"arguments": _describe_arguments(func, args, kwargs)} if capture_io else None
                )

            def output(result: Any) -> Optional[Dict[str, Any]]:
                return {"result": _safe_repr(result)} if capture_io else None

            if inspect.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    if self._context.current_trace is None:
                        return await func(*args, **kwargs)
                    with self.span(span_name, inputs(args, kwargs)) as span:
                        result = await func(*args, **kwargs)
                        span.complete(output(result))
                        return result

                return async_wrapper  # type: ignore[return-value]

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if self._context.current_trace is None:
                    return func(*args, **kwargs)
                with self.span(span_name, inputs(args, kwargs)) as span:
                    result = func(*args, **kwargs)
                    span.complete(output(result))
                    return result

            return wrapper  # type: ignore[return-value]

        return decorator
