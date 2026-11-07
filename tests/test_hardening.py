"""Tests for the defects and security gaps found during review."""

import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from tracehunter import InMemoryTraceRepository, SQLiteTraceRepository, Status, Tracer
from tracehunter.api.app import create_app
from tracehunter.domain.models import Span, Trace, to_jsonable
from tracehunter.domain.repository import TraceRepository


@pytest.fixture(params=["memory", "sqlite"])
def repo(request):
    if request.param == "memory":
        return InMemoryTraceRepository()
    repository = SQLiteTraceRepository(":memory:")
    request.addfinalizer(repository.close)
    return repository


class TestTracerNeverBreaksTheApp:
    def test_nested_trace_has_isolated_span_stack(self, repo) -> None:
        tracer = Tracer(repo)
        with tracer.trace("outer"):
            with tracer.span("s1") as s1:
                with tracer.trace("inner") as inner:
                    with tracer.span("s2") as s2:
                        pass
                assert tracer.context.current_span is s1
        assert s2.parent_span_id is None
        assert s2.trace_id == inner.trace_id != s1.trace_id

    def test_broken_repr_does_not_break_the_user_function(self, repo) -> None:
        class Broken:
            def __repr__(self) -> str:
                raise ValueError("boom")

        tracer = Tracer(repo)

        @tracer.observe()
        def work(x: Any) -> Any:
            return Broken()

        with tracer.trace("t") as trace:
            work(Broken())
        assert trace.status is Status.COMPLETED
        assert "repr failed" in trace.to_dict()["spans"][0]["input_data"]["arguments"]["x"]

    def test_huge_repr_is_truncated(self, repo) -> None:
        tracer = Tracer(repo)

        @tracer.observe()
        def work(x: str) -> str:
            return x

        with tracer.trace("t") as trace:
            work("a" * 50_000)
        assert len(trace.to_dict()["spans"][0]["output_data"]["result"]) <= 1001

    def test_save_failure_does_not_mask_user_exception(self, caplog) -> None:
        class FailingRepo(InMemoryTraceRepository):
            def save(self, trace: Trace) -> None:
                raise OSError("disk full")

        tracer = Tracer(FailingRepo())
        with caplog.at_level(logging.ERROR, logger="tracehunter"):
            with pytest.raises(KeyError):
                with tracer.trace("t"):
                    raise KeyError("original")
        assert "failed to save" in caplog.text

    def test_non_string_dict_keys_and_nan_are_stored(self, repo) -> None:
        tracer = Tracer(repo)
        hostile: Dict[Any, Any] = {(1, 2): 3, "x": math.nan}
        with tracer.trace("t") as trace:
            with tracer.span("s", hostile):
                pass
        loaded = repo.get(trace.trace_id)
        assert loaded is not None
        assert loaded.to_dict()["spans"][0]["input_data"] == {"(1, 2)": 3, "x": "nan"}

    def test_generators_are_rejected_at_decoration(self) -> None:
        tracer = Tracer(InMemoryTraceRepository())
        with pytest.raises(TypeError, match="generators"):

            @tracer.observe()
            def gen():
                yield 1

    def test_sensitive_arguments_are_masked(self, repo) -> None:
        tracer = Tracer(repo)

        @tracer.observe()
        def call(prompt: str, api_key: str, **kwargs: Any) -> None:
            return None

        with tracer.trace("t") as trace:
            call("hi", "sk-secret", auth_token="abc")  # noqa: S106
        arguments = trace.to_dict()["spans"][0]["input_data"]["arguments"]
        assert arguments["prompt"] == "'hi'"
        assert arguments["api_key"] == "***"
        assert "secret" not in str(trace.to_dict())
        assert "abc" not in str(trace.to_dict()["spans"][0]["input_data"])

    def test_capture_io_false_records_nothing(self, repo) -> None:
        tracer = Tracer(repo)

        @tracer.observe(capture_io=False)
        def call(secret_prompt: str) -> str:
            return "answer"

        with tracer.trace("t") as trace:
            call("sensitive data")
        assert trace.spans[0].input_data is None
        assert trace.spans[0].output_data is None


class TestModels:
    def test_duplicate_span_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            Trace("t", spans=[Span("a", span_id="1"), Span("b", span_id="1")])

    def test_naive_datetimes_are_treated_as_utc(self) -> None:
        span = Span("a", start_time=datetime(2026, 1, 1, 12, 0))
        assert span.start_time.tzinfo is timezone.utc

    def test_to_jsonable_handles_hostile_values(self) -> None:
        class BadStr:
            def __str__(self) -> str:
                raise RuntimeError

        deep: Dict[str, Any] = {}
        node = deep
        for _ in range(50):
            node["k"] = {}
            node = node["k"]
        assert to_jsonable(BadStr()) == "<BadStr>"
        assert to_jsonable({1: float("inf"), "s": {1}}) == {"1": "inf", "s": [1]}
        assert "max depth" in str(to_jsonable(deep))


class TestRepositories:
    def test_negative_limit_is_rejected(self, repo: TraceRepository) -> None:
        with pytest.raises(ValueError):
            repo.list_traces(-1)

    def test_order_is_chronological_across_timezones(self, repo: TraceRepository) -> None:
        base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        a = Trace("a", start_time=base - timedelta(hours=3))
        b = Trace("b", start_time=base)
        c = Trace("c", start_time=base + timedelta(microseconds=500_000))
        for trace in (a, b, c):
            repo.save(trace)
        assert [t.name for t in repo.list_traces()] == ["c", "b", "a"]

    def test_sqlite_skips_corrupted_rows(self) -> None:
        repository = SQLiteTraceRepository(":memory:")
        repository.save(Trace("ok"))
        with repository._connection:
            repository._connection.execute(
                "INSERT INTO traces VALUES ('bad', 'bad', 'RUNNING', 0, '{not json')"
            )
        assert [t.name for t in repository.list_traces()] == ["ok"]
        assert repository.get("bad") is None
        repository.close()


class TestApiHardening:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(create_app(InMemoryTraceRepository(), allowed_hosts=("testserver",)))

    def test_limit_is_validated(self, client: TestClient) -> None:
        assert client.get("/api/traces?limit=0").status_code == 422
        assert client.get("/api/traces?limit=-1").status_code == 422
        assert client.get("/api/traces?limit=100000000").status_code == 422
        assert client.get("/api/traces?limit=200").status_code == 200

    def test_unknown_host_is_rejected(self, client: TestClient) -> None:
        response = client.get("/api/traces", headers={"Host": "evil.example"})
        assert response.status_code == 400
        assert "default-src 'none'" in response.headers["content-security-policy"]

    def test_docs_are_disabled(self, client: TestClient) -> None:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404

    def test_static_path_traversal_is_blocked(self, client: TestClient) -> None:
        for path in ("/static/../pyproject.toml", "/static/..%2f..%2fpyproject.toml"):
            assert client.get(path).status_code in (400, 404)


def test_main_explains_missing_web_dependencies(monkeypatch, capsys) -> None:
    import tracehunter.__main__ as entry

    monkeypatch.setitem(sys.modules, "uvicorn", None)  # makes "import uvicorn" raise ImportError
    with pytest.raises(SystemExit) as exit_info:
        entry.main([])
    assert exit_info.value.code == 1
    assert "tracehunter[server]" in capsys.readouterr().err


def test_main_passes_environment_to_uvicorn(monkeypatch, capsys) -> None:
    import uvicorn

    import tracehunter.__main__ as entry

    calls: Dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: calls.update(host=host, port=port))
    monkeypatch.setenv("TRACEHUNTER_HOST", "0.0.0.0")  # noqa: S104 - checking the warning
    monkeypatch.setenv("TRACEHUNTER_PORT", "9999")
    entry.main([":memory:"])
    assert calls == {"host": "0.0.0.0", "port": 9999}  # noqa: S104
    assert "has no login" in capsys.readouterr().err


def test_main_version_and_help_do_not_start_the_server(monkeypatch, capsys) -> None:
    import uvicorn

    import tracehunter
    import tracehunter.__main__ as entry

    started = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(True))
    for flag in ("--version", "--help"):
        with pytest.raises(SystemExit) as exit_info:
            entry.main([flag])
        assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert tracehunter.__version__ in output
    assert "TRACEHUNTER_HOST" in output
    assert started == []
