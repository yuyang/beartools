"""Codex 命令与核心流程测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from beartools.cli import app
from beartools.codex import _CodexStreamEvent, _normalize_stream_event, run_codex_markdown_async
from beartools.config import CodexConfig, Config

runner = CliRunner()


@dataclass
class _FakeStreamRunResult:
    """最小化 streamed 结果替身。"""

    events_factory: Callable[[], AsyncIterator[object]]
    final_output: object | None = None

    def stream_events(self) -> AsyncIterator[object]:
        return self.events_factory()


def _build_fake_config(output_dir: Path) -> Config:
    """构造测试使用的最小 Codex 配置。"""

    return Config(
        codex=CodexConfig(
            base_url="https://example.com/v1",
            api_key="token",
            model="demo-model",
            output_dir=output_dir,
        )
    )


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: Config,
    stream: _FakeStreamRunResult,
) -> None:
    """替换运行时依赖，避免触发真实 SDK。"""

    class FakeRunner:
        @staticmethod
        def run_streamed(agent: object, input: str) -> _FakeStreamRunResult:
            del agent, input
            return stream

    class FakeModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    class FakeAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    monkeypatch.setattr("beartools.codex.get_config", lambda: config)
    monkeypatch.setattr("beartools.codex.Runner", FakeRunner)
    monkeypatch.setattr("beartools.codex.OpenAIResponsesModel", FakeModel)
    monkeypatch.setattr("beartools.codex.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex.Agent", FakeAgent)
    monkeypatch.setattr("beartools.codex.set_tracing_disabled", lambda _value: None)
    monkeypatch.setattr("beartools.codex._normalize_stream_event", lambda event: event)


def test_codex_run_missing_markdown_file_exits_with_error(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.md"

    result = runner.invoke(app, ["codex", "run", str(missing_file)])

    assert result.exit_code == 1
    assert "错误:" in result.stdout
    assert "不存在" in result.stdout


def test_codex_run_prints_final_and_trace_paths(tmp_path: Path) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("hello", encoding="utf-8")
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


def test_execute_shell_commands_passes_cwd_and_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert result.output[0].command == "pwd"
    assert result.output[0].stdout == "ok"


def test_run_codex_markdown_raises_when_config_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(
        "beartools.codex.get_config",
        lambda: Config(codex=CodexConfig(base_url="", api_key="token", model="demo-model")),
    )

    with pytest.raises(RuntimeError, match="base_url"):
        asyncio.run(run_codex_markdown_async(md_file, None, None))


def test_run_codex_markdown_happy_path_writes_trace_and_final_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("请执行", encoding="utf-8")
    config = _build_fake_config(tmp_path / "output")

    async def fake_events() -> AsyncIterator[object]:
        yield _CodexStreamEvent(type="reasoning_item_created", message="思考中", display_text="[thinking] 思考中")
        yield _CodexStreamEvent(type="tool_called", message="shell", display_text="[tool:start] shell")
        yield _CodexStreamEvent(type="response.output_text.delta", message="部分回答", display_text="部分回答")

    stream = _FakeStreamRunResult(events_factory=fake_events, final_output="最终回答")
    _patch_runtime(monkeypatch, config=config, stream=stream)

    result = asyncio.run(run_codex_markdown_async(md_file, None, None))

    assert result.final_text == "最终回答"
    assert result.final_output_file.read_text(encoding="utf-8") == "最终回答"
    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"type": "reasoning_item_created"' in trace_text
    assert '"type": "tool_called"' in trace_text
    assert '"message": "部分回答"' in trace_text


def test_run_codex_markdown_recovers_on_stream_error_and_keeps_final_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("请执行", encoding="utf-8")
    config = _build_fake_config(tmp_path / "output")

    async def fake_events() -> AsyncIterator[object]:
        yield _CodexStreamEvent(type="unknown_event", message="turn.started", display_text="")
        raise RuntimeError("socket error")

    stream = _FakeStreamRunResult(events_factory=fake_events, final_output="保留的最终回答")
    _patch_runtime(monkeypatch, config=config, stream=stream)

    result = asyncio.run(run_codex_markdown_async(md_file, None, None))

    assert result.final_text == "保留的最终回答"
    assert result.final_output_file.read_text(encoding="utf-8") == "保留的最终回答"
    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"type": "unknown_event"' in trace_text
    assert "turn.started" in trace_text
    assert "stream_error: socket error" in trace_text


def test_normalize_stream_event_maps_agent_updated_event() -> None:
    class FakeRuntimeAgentUpdatedStreamEvent:
        def __init__(self) -> None:
            self.type = "agent_updated_stream_event"
            self.new_agent = "Codex Runner"

        def __repr__(self) -> str:
            return "FakeAgentUpdatedEvent(new_agent='Codex Runner')"

    with patch.dict(
        "sys.modules",
        {
            "agents.stream_events": type(
                "FakeModule",
                (),
                {
                    "AgentUpdatedStreamEvent": FakeRuntimeAgentUpdatedStreamEvent,
                    "RawResponsesStreamEvent": type("RawResponsesStreamEvent", (), {}),
                    "RunItemStreamEvent": type("RunItemStreamEvent", (), {}),
                },
            )(),
            "agents.items": type(
                "FakeItemsModule",
                (),
                {
                    "ReasoningItem": type("ReasoningItem", (), {}),
                    "ToolCallItem": type("ToolCallItem", (), {}),
                    "ToolCallOutputItem": type("ToolCallOutputItem", (), {}),
                },
            )(),
        },
    ):
        event = _normalize_stream_event(FakeRuntimeAgentUpdatedStreamEvent())

    assert event == _CodexStreamEvent(
        type="agent_updated_stream_event",
        message="agent_updated_stream_event: FakeAgentUpdatedEvent(new_agent='Codex Runner')",
        display_text="",
    )


def test_normalize_stream_event_maps_raw_response_lifecycle_events() -> None:
    class FakeResponseEvent:
        def __init__(self, event_type: str) -> None:
            self.type = event_type

        def __repr__(self) -> str:
            return f"FakeResponseEvent(type={self.type!r})"

    class FakeRuntimeRawResponsesStreamEvent:
        def __init__(self, event_type: str) -> None:
            self.type = "raw_response_event"
            self.data = FakeResponseEvent(event_type)

    with patch.dict(
        "sys.modules",
        {
            "agents.stream_events": type(
                "FakeModule",
                (),
                {
                    "AgentUpdatedStreamEvent": type("AgentUpdatedStreamEvent", (), {}),
                    "RawResponsesStreamEvent": FakeRuntimeRawResponsesStreamEvent,
                    "RunItemStreamEvent": type("RunItemStreamEvent", (), {}),
                },
            )(),
            "agents.items": type(
                "FakeItemsModule",
                (),
                {
                    "ReasoningItem": type("ReasoningItem", (), {}),
                    "ToolCallItem": type("ToolCallItem", (), {}),
                    "ToolCallOutputItem": type("ToolCallOutputItem", (), {}),
                },
            )(),
        },
    ):
        event = _normalize_stream_event(FakeRuntimeRawResponsesStreamEvent("response.created"))

    assert event == _CodexStreamEvent(
        type="response.lifecycle",
        message="response.created: FakeResponseEvent(type='response.created')",
        display_text="",
    )


def test_normalize_stream_event_maps_raw_response_web_search_call() -> None:
    class FakeResponseEvent:
        def __init__(self) -> None:
            self.type = "response.output_item.done"
            self.item = type(
                "FakeWebSearchItem",
                (),
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "__repr__": lambda _self: "FakeWebSearchItem(type='web_search_call', status='completed')",
                },
            )()

        def __repr__(self) -> str:
            return "FakeResponseEvent(type='response.output_item.done', item=FakeWebSearchItem(type='web_search_call', status='completed'))"

    class FakeRuntimeRawResponsesStreamEvent:
        def __init__(self) -> None:
            self.type = "raw_response_event"
            self.data = FakeResponseEvent()

    with patch.dict(
        "sys.modules",
        {
            "agents.stream_events": type(
                "FakeModule",
                (),
                {
                    "AgentUpdatedStreamEvent": type("AgentUpdatedStreamEvent", (), {}),
                    "RawResponsesStreamEvent": FakeRuntimeRawResponsesStreamEvent,
                    "RunItemStreamEvent": type("RunItemStreamEvent", (), {}),
                },
            )(),
            "agents.items": type(
                "FakeItemsModule",
                (),
                {
                    "ReasoningItem": type("ReasoningItem", (), {}),
                    "ToolCallItem": type("ToolCallItem", (), {}),
                    "ToolCallOutputItem": type("ToolCallOutputItem", (), {}),
                },
            )(),
        },
    ):
        event = _normalize_stream_event(FakeRuntimeRawResponsesStreamEvent())

    assert event == _CodexStreamEvent(
        type="tool_called",
        message="web_search_call",
        display_text="[tool:start] web_search_call",
    )
