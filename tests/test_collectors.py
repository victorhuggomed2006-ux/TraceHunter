"""Tests for the Claude Code collector, synchronization and secret masking."""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tracehunter import InMemoryTraceRepository, Status, Trace
from tracehunter.application.collector_sync import CollectorSync
from tracehunter.domain.redaction import clip, redact, safe_text
from tracehunter.infrastructure.claude_code_collector import ClaudeCodeCollector

STATIC = Path(__file__).resolve().parent.parent / "tracehunter" / "api" / "static"


def _line(kind: str, uuid: str, second: int, message: Dict[str, Any], **extra: Any) -> str:
    event = {
        "type": kind,
        "uuid": uuid,
        "timestamp": f"2026-01-01T10:00:{second:02d}Z",
        "cwd": "/work/MyProj",
        "message": message,
        **extra,
    }
    return json.dumps(event)


def _session_lines() -> List[str]:
    return [
        _line(
            "user",
            "u1",
            0,
            {"role": "user", "content": "Fix the bug\nkey sk-ABCDEFGHIJKLMNOPQRSTUV"},
            origin={"kind": "human"},
        ),
        _line(
            "assistant",
            "a1",
            1,
            {
                "id": "msg_1",
                "model": "claude-x",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Looking"},
                    {"type": "thinking", "thinking": "private reasoning"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    },
                ],
            },
        ),
        _line(
            "user",
            "r1",
            3,
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "file.txt"}
                ],
            },
        ),
        _line(
            "assistant",
            "a2",
            4,
            {"id": "msg_2", "model": "claude-x", "content": [{"type": "text", "text": "Done"}]},
        ),
        _line(
            "user", "p1", 5, {"role": "user", "content": "from a subagent"}, origin={"kind": "peer"}
        ),
        _line(
            "user", "u2", 6, {"role": "user", "content": "Run the tests"}, origin={"kind": "human"}
        ),
        _line(
            "assistant",
            "a3",
            7,
            {
                "id": "msg_3",
                "model": "claude-x",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "Read",
                        "input": {"file_path": "/a/b.py"},
                    }
                ],
            },
        ),
        _line(
            "user",
            "r2",
            8,
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_2",
                        "content": "boom",
                        "is_error": True,
                    }
                ],
            },
        ),
        "{ broken line that must be ignored",
    ]


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    folder = tmp_path / "projects" / "MyProj"
    folder.mkdir(parents=True)
    session = folder / "session-1.jsonl"
    session.write_text("\n".join(_session_lines()) + "\n", encoding="utf-8")
    os.utime(session, (1_600_000_000, 1_600_000_000))  # old file: no turn is left "running"
    return tmp_path / "projects"


def _by_name(traces: List[Trace]) -> Dict[str, Trace]:
    return {t.name: t for t in traces}


class TestClaudeCodeCollector:
    def test_each_human_prompt_becomes_a_trace_and_others_are_ignored(self, projects: Path) -> None:
        traces = ClaudeCodeCollector(projects).collect()
        assert len(traces) == 2
        assert all(t.trace_id.startswith("claude-code:session-1:") for t in traces)
        assert all(t.status is Status.COMPLETED for t in traces)

    def test_secrets_are_masked_in_the_trace_name(self, projects: Path) -> None:
        first = ClaudeCodeCollector(projects).collect()[0]
        assert first.name.startswith("[MyProj] Fix the bug")
        assert "sk-ABCDEFGHIJ" not in str(first.to_dict())

    def test_spans_have_llm_calls_and_nested_tools(self, projects: Path) -> None:
        first = ClaudeCodeCollector(projects).collect()[0]
        spans = {s.span_id: s for s in first.spans}
        assert set(spans) == {"msg_1", "toolu_1", "msg_2"}
        tool = spans["toolu_1"]
        assert tool.parent_span_id == "msg_1"
        assert tool.name == "Bash: ls"
        assert tool.status is Status.COMPLETED
        assert tool.output_data == {"result": "file.txt"}
        assert spans["msg_1"].metadata["input_tokens"] == 10

    def test_private_reasoning_is_never_copied(self, projects: Path) -> None:
        dump = json.dumps([t.to_dict() for t in ClaudeCodeCollector(projects).collect()])
        assert "private reasoning" not in dump

    def test_failed_tool_marks_the_span_as_failed(self, projects: Path) -> None:
        second = [t for t in ClaudeCodeCollector(projects).collect() if "Run the tests" in t.name][
            0
        ]
        failed = [s for s in second.spans if s.status is Status.FAILED]
        assert len(failed) == 1
        assert failed[0].metadata["error"] == "boom"

    def test_unchanged_files_are_not_read_again(self, projects: Path) -> None:
        collector = ClaudeCodeCollector(projects)
        assert len(collector.collect()) == 2
        assert collector.collect() == []

    def test_a_fresh_file_marks_the_last_turn_as_running(self, projects: Path) -> None:
        os.utime(projects / "MyProj" / "session-1.jsonl")  # touched just now
        traces = ClaudeCodeCollector(projects).collect()
        by_name = _by_name(traces)
        assert by_name[[n for n in by_name if "Run the tests" in n][0]].status is Status.RUNNING
        assert by_name[[n for n in by_name if "Fix the bug" in n][0]].status is Status.COMPLETED

    def test_missing_folder_gives_no_traces(self, tmp_path: Path) -> None:
        assert ClaudeCodeCollector(tmp_path / "does-not-exist").collect() == []

    def test_max_files_limits_the_sessions_read(self, projects: Path) -> None:
        extra = projects / "Other" / "session-2.jsonl"
        extra.parent.mkdir()
        extra.write_text(_session_lines()[0] + "\n", encoding="utf-8")
        assert len(ClaudeCodeCollector(projects, max_files=1).collect()) in (1, 2)
        names = {p.parent.name for p in ClaudeCodeCollector(projects, max_files=1)._recent_files()}
        assert len(names) == 1


class TestCollectorSync:
    def test_saves_only_what_changed(self, projects: Path) -> None:
        repository = InMemoryTraceRepository()
        sync = CollectorSync(ClaudeCodeCollector(projects), repository)
        assert sync.sync_once() == 2
        assert len(repository.list_traces()) == 2
        assert sync.sync_once() == 0

    def test_new_prompt_in_the_session_is_picked_up(self, projects: Path) -> None:
        repository = InMemoryTraceRepository()
        sync = CollectorSync(ClaudeCodeCollector(projects), repository)
        sync.sync_once()
        session = projects / "MyProj" / "session-1.jsonl"
        with session.open("a", encoding="utf-8") as handle:
            handle.write(
                _line(
                    "user",
                    "u3",
                    9,
                    {"role": "user", "content": "One more"},
                    origin={"kind": "human"},
                )
                + "\n"
            )
        os.utime(session, (1_600_000_100, 1_600_000_100))
        assert sync.sync_once() == 1  # only the new prompt; the other traces did not change
        assert len(repository.list_traces()) == 3

    def test_background_thread_starts_and_stops(self, projects: Path) -> None:
        sync = CollectorSync(
            ClaudeCodeCollector(projects), InMemoryTraceRepository(), interval=0.05
        )
        sync.start()
        sync.start()  # idempotent
        sync.stop()


class TestRedaction:
    def test_known_secret_shapes_are_masked(self) -> None:
        # Made-up values, built at runtime so they do not look like secrets in the code.
        aws_like = "AKIA" + "ABCDEFGHIJKLMNOP"
        text = "k=sk-" + "A" * 24 + " g=ghp_" + "a" * 30 + f" password: hunter2 {aws_like}"
        cleaned = redact(text)
        for secret in ("sk-AAAA", "ghp_aaaa", "hunter2", aws_like):
            assert secret not in cleaned
        assert "***" in cleaned

    def test_clip_marks_truncation(self) -> None:
        assert clip("abc", 5) == "abc"
        assert clip("abcdef", 3) == "abc…"

    def test_safe_text_never_raises(self) -> None:
        class Bad:
            def __str__(self) -> str:
                raise RuntimeError

        assert safe_text(Bad()) == "<Bad>"


class TestI18n:
    """The interface language dictionary must have the same keys in every language."""

    @staticmethod
    def _languages() -> Dict[str, List[str]]:
        text = (STATIC / "i18n.js").read_text(encoding="utf-8")
        blocks = re.findall(r"^  (\w+): \{\n(.*?)^  \},?$", text, re.M | re.S)
        return {code: re.findall(r"^    (\w+): ", body, re.M) for code, body in blocks}

    def test_all_languages_have_the_same_keys_as_english(self) -> None:
        languages = self._languages()
        assert len(languages) >= 18
        reference = set(languages["en"])
        for code, keys in languages.items():
            assert set(keys) == reference, code
            assert len(keys) == len(set(keys)), f"duplicate key in {code}"

    def test_index_loads_the_dictionary_before_the_app(self) -> None:
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        assert html.index("i18n.js") < html.index("app.js")
        assert 'id="lang"' in html
