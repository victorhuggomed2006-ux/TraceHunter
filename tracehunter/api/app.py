"""FastAPI app that exposes the saved traces and serves the web interface."""

from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tracehunter.domain.models import Trace
from tracehunter.domain.pricing import PriceTable
from tracehunter.domain.repository import TraceRepository

_STATIC_DIR = Path(__file__).parent / "static"

# The API has no login: it only answers to these hosts, which blocks DNS rebinding.
DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")

# Security headers on every response (the UI uses no inline scripts or styles).
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _cost(prices: PriceTable, trace: Trace) -> Optional[float]:
    """Estimated cost in USD (4 decimals) or None when no span could be priced."""
    cost = prices.trace_cost(trace)
    return None if cost is None else round(cost, 4)


def _tokens(trace: Trace) -> Dict[str, int]:
    """Token totals of a trace for the API: {"input": n, "output": n}."""
    total_in, total_out = trace.token_usage
    return {"input": total_in, "output": total_out}


def create_app(
    repository: TraceRepository, allowed_hosts: Sequence[str] = DEFAULT_ALLOWED_HOSTS
) -> FastAPI:
    """Create the read-only web application on top of the given repository.

    `allowed_hosts` lists the values accepted in the Host header (without the port).
    """
    # No /docs, /redoc or /openapi.json: the exposed surface is only the UI and the read API.
    app = FastAPI(title="TraceHunter", docs_url=None, redoc_url=None, openapi_url=None)
    prices = PriceTable.load()

    # Added before the headers middleware so that 400 responses also get the headers.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        return response

    @app.get("/api/traces")
    def list_traces(limit: int = Query(50, ge=1, le=200)) -> List[Dict[str, Any]]:
        summaries = []
        for trace in repository.list_traces(limit):
            data = trace.to_dict()
            data["span_count"] = len(data.pop("spans"))
            data["duration_seconds"] = trace.duration_seconds
            data["tokens"] = _tokens(trace)
            data["cost_usd"] = _cost(prices, trace)
            summaries.append(data)
        return summaries

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str) -> Dict[str, Any]:
        trace = repository.get(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        data = trace.to_dict()
        data["duration_seconds"] = trace.duration_seconds
        data["tokens"] = _tokens(trace)
        data["cost_usd"] = _cost(prices, trace)
        for raw, span in zip(data["spans"], trace.spans, strict=False):
            raw["duration_seconds"] = span.duration_seconds
        return data

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    return app
