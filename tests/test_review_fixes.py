"""Regression tests for the issues found in the pre-release review."""

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from tracehunter import ClaudeCodeCollector, CollectorSync, InMemoryTraceRepository, Tracer
from tracehunter.domain.redaction import redact, safe_text


class TestRedactionFormats:
    def test_compound_env_and_json_keys_are_masked(self) -> None:
        cases = [
            "DB_PASSWORD=abc123",
            "AWS_SECRET_ACCESS_KEY=" + "wJalrX" + "UtnFEMI/K7MDENG",
            "export API_TOKEN=tok_value_here",
            '{"password": "hunter2"}',
            "client_secret: zzz-value",
            "postgres://admin:S3cretPass@db.example/app",
            "HF_TOKEN=" + "hf_" + "a" * 30,
            "key " + "sk" + "_live_" + "A" * 20,
        ]
        for case in cases:
            cleaned = redact(case)
            for leaked in ("abc123", "wJalrX", "tok_value", "hunter2", "zzz-value", "S3cretPass"):
                assert leaked not in cleaned, (case, cleaned)
            assert "***" in cleaned, case

    def test_plain_prose_and_numbers_are_left_alone(self) -> None:
        text = "The token budget is large and the key idea is simple: 42 steps."
        assert redact(text) == text

    def test_huge_input_is_cut_before_the_regexes_run(self) -> None:
        assert len(safe_text("A" * 5_000_000, 400)) <= 401


class TestObserveNeverBreaksTheApp:
    def test_call_outside_a_trace_just_runs(self) -> None:
        tracer = Tracer(InMemoryTraceRepository())

        @tracer.observe()
        def add(a: int, b: int) -> int:
            return a + b

        assert add(1, 2) == 3

    def test_async_call_outside_a_trace_just_runs(self) -> None:
        tracer = Tracer(InMemoryTraceRepository())

        @tracer.observe()
        async def add(a: int, b: int) -> int:
            return a + b

        assert asyncio.run(add(1, 2)) == 3

    def test_call_in_a_new_thread_does_not_raise(self) -> None:
        repo = InMemoryTraceRepository()
        tracer = Tracer(repo)
        outcome: Dict[str, Any] = {}

        @tracer.observe()
        def work() -> str:
            return "done"

        def runner() -> None:
            try:
                outcome["value"] = work()
            except Exception as error:  # noqa: BLE001 - the test asserts nothing is raised
                outcome["error"] = error

        with tracer.trace("t"):
            thread = threading.Thread(target=runner)
            thread.start()
            thread.join()
        assert outcome == {"value": "done"}


def _event(kind: str, uuid: str, second: int, message: Dict[str, Any], **extra: Any) -> str:
    event = {
        "type": kind,
        "uuid": uuid,
        "timestamp": f"2026-01-01T10:00:{second:02d}Z",
        "cwd": "/work/Proj",
        "message": message,
        **extra,
    }
    return json.dumps(event)


def _prompt(second: int = 0) -> str:
    return _event(
        "user", f"u{second}", second, {"role": "user", "content": "do it"}, origin={"kind": "human"}
    )


def _assistant(message_id: str, second: int, tools: List[Dict[str, Any]]) -> str:
    content: List[Dict[str, Any]] = [{"type": "text", "text": "ok"}, *tools]
    return _event(
        "assistant", f"a{second}", second, {"id": message_id, "model": "m", "content": content}
    )


class TestCollectorRobustness:
    def _write(self, tmp_path: Path, name: str, lines: List[str]) -> Path:
        folder = tmp_path / "projects" / name
        folder.mkdir(parents=True)
        session = folder / "s.jsonl"
        session.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(session, (1_600_000_000, 1_600_000_000))
        return tmp_path / "projects"

    def test_repeated_and_missing_tool_ids_do_not_break_collection(self, tmp_path: Path) -> None:
        tool = {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}}
        no_id = {"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}}
        lines = [
            _prompt(),
            _assistant("msg_1", 1, [tool, tool, no_id, dict(no_id)]),
            _assistant("msg_1", 2, []),
        ]
        projects = self._write(tmp_path, "Proj", lines)
        traces = ClaudeCodeCollector(projects).collect()
        assert len(traces) == 1
        ids = [s.span_id for s in traces[0].spans]
        assert len(ids) == len(set(ids))
        assert "toolu_1" in ids and "msg_1:tool2" in ids and "msg_1:tool3" in ids

    def test_prompt_without_uuid_gets_a_usable_trace_id(self, tmp_path: Path) -> None:
        event = json.loads(_prompt())
        del event["uuid"]
        projects = self._write(tmp_path, "Proj", [json.dumps(event)])
        trace = ClaudeCodeCollector(projects).collect()[0]
        assert "None" not in trace.trace_id

    def test_a_bad_session_does_not_stop_the_good_ones(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        projects = self._write(tmp_path, "Good", [_prompt()])
        bad = projects / "Bad"
        bad.mkdir()
        (bad / "s.jsonl").write_text(_prompt() + "\n", encoding="utf-8")
        collector = ClaudeCodeCollector(projects)
        original = collector._parse

        def flaky(path: Path, modified: float) -> Any:
            if path.parent.name == "Bad":
                raise RuntimeError("boom")
            return original(path, modified)

        monkeypatch.setattr(collector, "_parse", flaky)
        assert len(collector.collect()) == 1

    def test_sync_survives_a_failing_collector(self) -> None:
        class Broken(ClaudeCodeCollector):
            def collect(self) -> Any:
                raise RuntimeError("boom")

        sync = CollectorSync(Broken(Path("nowhere")), InMemoryTraceRepository(), interval=0.05)
        sync.start()
        sync.stop()
