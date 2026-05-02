"""Codex 命令与业务测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from beartools.cli import app

runner = CliRunner()


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
        {"type": "tool_called", "name": "history_fun_fact", "arguments": {}},
        {"type": "tool_output", "name": "history_fun_fact", "output": "工具输出"},
        {"type": "response.output_text.delta", "delta": "最终回答"},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ]

    async def fake_stream_events(prompt: str) -> AsyncIterator[dict[str, object]]:
        assert prompt == "请执行"
        for event in fake_events:
            yield event

    from beartools.codex import run_codex_markdown_async

    monkeypatch.setattr("beartools.codex._stream_codex_events", fake_stream_events)
    monkeypatch.setattr("beartools.codex.console", FakeConsole())
    monkeypatch.setattr("beartools.codex.logger", FakeLogger())

    result = asyncio.run(run_codex_markdown_async(md_file, None, None))

    assert result.final_text == "最终回答"
    assert result.final_output_file.read_text(encoding="utf-8")
    assert result.trace_output_file.read_text(encoding="utf-8")
    assert any("tool:start" in chunk for chunk in final_chunks)
    assert any("thinking" in chunk for chunk in final_chunks)


def test_codex_run_missing_markdown_file_exits_with_error(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.md"

    result = runner.invoke(app, ["codex", "run", str(missing_file)])

    assert result.exit_code == 1
    assert "错误:" in result.stdout
