"""Codex 命令与业务测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import patch

from agents import Agent, RunContextWrapper
from agents.items import ReasoningItem, ToolCallItem, ToolCallOutputItem
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from agents.tool import ShellActionRequest, ShellCallData, ShellCommandRequest
from openai.types.responses import ResponseTextDeltaEvent
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_reasoning_item import ResponseReasoningItem
import pytest
from typer.testing import CliRunner

from beartools.cli import app
from beartools.config import CodexConfig, Config

runner = CliRunner()


@dataclass
class _FakeRunAgent:
    """测试用的弱引用友好 agent 占位对象。"""


_EMPTY_LOGPROBS: list[object] = []
_REASONING_SUMMARY: list[dict[str, str]] = [{"text": "思考中", "type": "summary_text"}]


def _build_fake_codex_config() -> Config:
    return Config(codex=CodexConfig(base_url="https://example.com/v1", api_key="token", model="demo-model"))


def _patch_codex_stream_dependencies(monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]) -> None:
    class FakeAgent:
        def __init__(self, *, name: str, instructions: str, model: object, tools: list[object]) -> None:
            captured["name"] = name
            captured["instructions"] = instructions
            captured["model"] = model
            captured["tools"] = tools

    class FakeResult:
        def stream_events(self) -> AsyncIterator[dict[str, object]]:
            async def _empty() -> AsyncIterator[dict[str, object]]:
                if False:
                    yield {"type": "noop"}

            return _empty()

    class FakeRunner:
        @staticmethod
        def run_streamed(agent: object, input: str) -> FakeResult:
            captured["runner_agent"] = agent
            captured["input"] = input
            return FakeResult()

    class FakeModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args
            captured["model_kwargs"] = kwargs

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            captured["client"] = self

    def fake_set_tracing_disabled(_value: bool) -> None:
        return None

    monkeypatch.setattr("agents.Agent", FakeAgent)
    monkeypatch.setattr("agents.Runner", FakeRunner)
    monkeypatch.setattr("agents.OpenAIResponsesModel", FakeModel)
    monkeypatch.setattr("agents.set_tracing_disabled", fake_set_tracing_disabled)
    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex.get_config", _build_fake_codex_config)


def test_codex_run_reads_markdown_and_writes_default_outputs(tmp_path: Path) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("# 标题\n\n请总结这段内容", encoding="utf-8")

    output_dir = tmp_path / "codex-output"

    from beartools.codex import CodexRunResult

    def fake_run_codex_markdown(*, md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
        assert md_path == md_file
        assert output_file is None
        assert trace_file is None
        final_file = output_dir / "prompt.codex.md"
        trace_out = output_dir / "prompt.codex.trace.log"
        final_file.parent.mkdir(parents=True, exist_ok=True)
        final_file.write_text("最终回答", encoding="utf-8")
        trace_out.write_text("trace", encoding="utf-8")
        return CodexRunResult(final_output_file=final_file, trace_output_file=trace_out, final_text="最终回答")

    with patch("beartools.commands.codex.command.run_codex_markdown", side_effect=fake_run_codex_markdown):
        result = runner.invoke(app, ["codex", "run", str(md_file)])

    assert result.exit_code == 0
    assert "prompt.codex.md" in result.stdout
    assert "prompt.codex.trace.log" in result.stdout


def test_run_codex_markdown_streams_events_and_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("请执行", encoding="utf-8")

    final_chunks: list[str] = []

    class FakeConsole:
        def print(self, message: str = "", end: str = "\n", style: str | None = None) -> None:
            del style
            final_chunks.append(message + end)

    class FakeLogger:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, message: str, *args: object) -> None:
            self.messages.append(message % args if args else message)

        def error(self, message: str, *args: object) -> None:
            self.messages.append(message % args if args else message)

    fake_events = [
        {"type": "reasoning_item_created", "text": "思考中"},
        {"type": "tool_called", "name": "shell", "arguments": {}},
        {"type": "tool_output", "name": "shell", "output": '{"stdout": "ok", "stderr": "", "exit_code": 0}'},
        {"type": "response.output_text.delta", "delta": "最终回答"},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ]

    async def fake_stream_events(prompt: str) -> AsyncIterator[dict[str, object]]:
        assert prompt == "请执行"
        for event in fake_events:
            yield cast(dict[str, object], event)

    from beartools.codex import run_codex_markdown_async

    monkeypatch.setattr("beartools.codex._stream_codex_events", fake_stream_events)
    monkeypatch.setattr("beartools.codex.console", FakeConsole())
    monkeypatch.setattr("beartools.codex.logger", FakeLogger())

    result = asyncio.run(run_codex_markdown_async(md_file, None, None))

    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert result.final_text == "最终回答"
    assert result.final_output_file.read_text(encoding="utf-8")
    assert trace_text
    assert any("tool:start" in chunk for chunk in final_chunks)
    assert any("shell" in chunk for chunk in final_chunks)
    assert any("thinking" in chunk for chunk in final_chunks)
    assert "tool_output" in trace_text
    assert "shell" in trace_text


def test_codex_run_missing_markdown_file_exits_with_error(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.md"

    result = runner.invoke(app, ["codex", "run", str(missing_file)])

    assert result.exit_code == 1
    assert "错误:" in result.stdout


def test_shell_executor_runs_in_output_codex_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"ok", b"")

    async def fake_create_subprocess_shell(
        command: str,
        *,
        cwd: Path,
        stdout: object,
        stderr: object,
    ) -> FakeProcess:
        executed["command"] = command
        executed["cwd"] = cwd
        executed["stdout"] = stdout
        executed["stderr"] = stderr
        return FakeProcess()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_create_subprocess_shell)

    from beartools.codex import _execute_shell_commands

    result = asyncio.run(_execute_shell_commands(["pwd"], timeout_seconds=5))

    assert executed["command"] == "pwd"
    assert executed["cwd"] == tmp_path / "output" / "codex"
    assert result.output[0].stdout == "ok"


def test_shell_tool_executor_uses_request_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_execute_shell_commands(commands: list[str], timeout_seconds: int) -> str:
        captured["commands"] = commands
        captured["timeout_seconds"] = timeout_seconds
        return "done"

    monkeypatch.setattr("beartools.codex._execute_shell_commands", fake_execute_shell_commands)

    from beartools.codex import _shell_tool_executor

    request = ShellCommandRequest(
        ctx_wrapper=cast(RunContextWrapper[object], None),
        data=ShellCallData(
            call_id="call-1",
            action=ShellActionRequest(commands=["ls", "pwd"]),
        ),
    )

    result = asyncio.run(_shell_tool_executor(request))

    assert captured["commands"] == ["ls", "pwd"]
    assert captured["timeout_seconds"] == 60
    assert result == "done"


def test_stream_codex_events_builds_agent_with_responses_model_and_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    _patch_codex_stream_dependencies(monkeypatch, captured)

    from beartools.codex import _stream_codex_events

    async def collect_events() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in _stream_codex_events("hello"):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    del events
    assert captured["model_kwargs"] == {"model": "demo-model", "openai_client": captured["client"]}
    tools = cast(list[object], captured["tools"])
    tool_classes = {tool.__class__.__name__ for tool in tools}
    assert "WebSearchTool" in tool_classes
    assert "ShellTool" in tool_classes


def test_stream_codex_events_consumes_official_response_events(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    _patch_codex_stream_dependencies(monkeypatch, captured)

    from beartools.codex import _stream_codex_events

    fake_run_agent = cast(Agent[object], _FakeRunAgent())

    raw_text_event = RawResponsesStreamEvent(
        data=ResponseTextDeltaEvent(
            content_index=0,
            delta="最终回答",
            item_id="msg_1",
            logprobs=_EMPTY_LOGPROBS,
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        )
    )
    tool_call_event = RunItemStreamEvent(
        name="tool_called",
        item=ToolCallItem(
            agent=fake_run_agent,
            raw_item=ResponseFunctionToolCall(
                arguments='{"query": "harry potter"}',
                call_id="call_1",
                name="web_search",
                type="function_call",
                id="fc_1",
                status="completed",
            ),
        ),
    )
    tool_output_event = RunItemStreamEvent(
        name="tool_output",
        item=ToolCallOutputItem(
            agent=fake_run_agent,
            raw_item={"type": "function_call_output", "call_id": "call_1", "output": "ok"},
            output='{"stdout": "ok"}',
        ),
    )
    reasoning_event = RunItemStreamEvent(
        name="reasoning_item_created",
        item=ReasoningItem(
            agent=fake_run_agent,
            raw_item=ResponseReasoningItem(
                id="rs_1",
                summary=_REASONING_SUMMARY,
                type="reasoning",
                content=None,
                encrypted_content=None,
                status=None,
            ),
        ),
    )

    class FakeResult:
        def stream_events(self) -> AsyncIterator[object]:
            async def _events() -> AsyncIterator[object]:
                yield reasoning_event
                yield tool_call_event
                yield tool_output_event
                yield raw_text_event

            return _events()

    class FakeRunner:
        @staticmethod
        def run_streamed(agent: object, input: str) -> FakeResult:
            captured["runner_agent"] = agent
            captured["input"] = input
            return FakeResult()

    monkeypatch.setattr("agents.Runner", FakeRunner)

    async def collect_events() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in _stream_codex_events("hello"):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert events == [
        {"type": "reasoning_item_created", "text": str(reasoning_event.item.raw_item)},
        {"type": "tool_called", "name": "web_search"},
        {"type": "tool_output", "output": '{"stdout": "ok"}'},
        {"type": "response.output_text.delta", "delta": "最终回答"},
    ]
