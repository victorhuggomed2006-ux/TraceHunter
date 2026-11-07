"""Tests for the web API."""

import pytest
from fastapi.testclient import TestClient

from tracehunter import InMemoryTraceRepository, Tracer
from tracehunter.api.app import create_app


@pytest.fixture
def client_and_trace():
    repo = InMemoryTraceRepository()
    tracer = Tracer(repo)
    with tracer.trace("question") as trace:
        with tracer.span("llm", {"prompt": "hi"}):
            pass
    return TestClient(create_app(repo, allowed_hosts=("testserver",))), trace


def test_list_traces(client_and_trace) -> None:
    client, trace = client_and_trace
    data = client.get("/api/traces").json()
    assert data[0]["trace_id"] == trace.trace_id
    assert data[0]["span_count"] == 1
    assert "spans" not in data[0]


def test_get_trace_with_spans(client_and_trace) -> None:
    client, trace = client_and_trace
    data = client.get(f"/api/traces/{trace.trace_id}").json()
    assert data["spans"][0]["name"] == "llm"
    assert data["spans"][0]["duration_seconds"] is not None


def test_get_missing_trace_is_404(client_and_trace) -> None:
    client, _ = client_and_trace
    assert client.get("/api/traces/nope").status_code == 404


def test_index_page_is_served(client_and_trace) -> None:
    client, _ = client_and_trace
    response = client.get("/")
    assert response.status_code == 200
    assert "TraceHunter" in response.text


def test_security_headers_on_every_response(client_and_trace) -> None:
    client, _ = client_and_trace
    for path in ("/", "/api/traces", "/static/app.js", "/does-not-exist"):
        headers = client.get(path).headers
        assert "default-src 'none'" in headers["content-security-policy"]
        assert headers["x-frame-options"] == "DENY"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["cache-control"] == "no-store"
        assert headers["cross-origin-embedder-policy"] == "require-corp"


def test_index_has_no_inline_script_or_style(client_and_trace) -> None:
    client, _ = client_and_trace
    html = client.get("/").text
    assert "<style" not in html and "onclick" not in html
    assert '<script src="/static/app.js">' in html


def test_terminal_theme_is_served_and_default(client_and_trace) -> None:
    client, _ = client_and_trace
    html = client.get("/").text
    assert 'data-theme="terminal"' in html
    assert 'id="theme"' in html
    css = client.get("/static/terminal.css")
    assert css.status_code == 200
    assert 'html[data-theme="terminal"]' in css.text
