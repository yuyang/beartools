from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from beartools.memory.models import CommandMemoryInput
from beartools.memory.prompts import build_command_memory_prompt, build_daily_summary_prompt
from beartools.memory.service import (
    append_command_memory,
    append_missing_daily_summaries,
    generate_daily_summary,
    sanitize_console_text,
)
from beartools.prompt import PromptManager


class _FakeCommandSummarizer:
    def __init__(self) -> None:
        self.calls: list[CommandMemoryInput] = []

    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        self.calls.append(memory_input)
        return "- 目的：查看 doctor 状态\n- 结果：doctor 已输出健康检查"


class _FailingCommandSummarizer:
    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        raise RuntimeError("模型不可用")


class _FakeDailySummarizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def summarize_day(self, day_content: str) -> str:
        self.calls.append(day_content)
        return "- 今天主要在做：验证记忆系统\n- 关键结果：summary 已生成\n- 未完成/后续：继续测试"


def _build_memory_input() -> CommandMemoryInput:
    return CommandMemoryInput(
        command="beartools doctor",
        help_text="运行环境健康检查",
        stdout="doctor ok",
        stderr="",
        exit_code=0,
        started_at=datetime(2026, 5, 13, 9, 30, 0),
        duration_seconds=1.25,
    )


def test_append_command_memory_creates_day_file_and_uses_small_summary(tmp_path: Path) -> None:
    summarizer = _FakeCommandSummarizer()

    output_path = append_command_memory(
        memory_root=tmp_path,
        memory_input=_build_memory_input(),
        summarizer=summarizer,
    )

    assert output_path == tmp_path / "day" / "2026-05-13.md"
    text = output_path.read_text(encoding="utf-8")
    assert "## 09:30:00 beartools doctor" in text
    assert "- 目的：查看 doctor 状态" in text
    assert "- 退出码：0" in text
    assert "- help：运行环境健康检查" in text
    assert summarizer.calls[0].stdout == "doctor ok"


def test_append_command_memory_strips_ansi_escape_from_console_output(tmp_path: Path) -> None:
    summarizer = _FakeCommandSummarizer()
    memory_input = CommandMemoryInput(
        command="beartools prompt check",
        help_text="检查 prompt",
        stdout="\x1b[3mPrompt Check\x1b[0m\n\x1b[32mpass\x1b[0m\n",
        stderr="\x1b[31mwarning\x1b[0m\n",
        exit_code=0,
        started_at=datetime(2026, 5, 13, 9, 30, 0),
        duration_seconds=1.25,
    )

    output_path = append_command_memory(memory_root=tmp_path, memory_input=memory_input, summarizer=summarizer)

    text = output_path.read_text(encoding="utf-8")
    assert "\x1b" not in text
    assert "Prompt Check" in text
    assert "pass" in text
    assert summarizer.calls[0].stdout == "Prompt Check\npass\n"
    assert summarizer.calls[0].stderr == "warning\n"


def test_sanitize_console_text_strips_common_escape_sequences() -> None:
    assert sanitize_console_text("a\x1b[32mz\x1b[0m\x1b]0;title\x07b") == "azb"


def test_append_command_memory_appends_without_overwriting(tmp_path: Path) -> None:
    summarizer = _FakeCommandSummarizer()
    first = _build_memory_input()
    second = CommandMemoryInput(
        command="beartools diary summary --date 2026-05-10",
        help_text="总结某一天",
        stdout="summary ok",
        stderr="",
        exit_code=0,
        started_at=datetime(2026, 5, 13, 10, 0, 0),
        duration_seconds=0.5,
    )

    append_command_memory(memory_root=tmp_path, memory_input=first, summarizer=summarizer)
    append_command_memory(memory_root=tmp_path, memory_input=second, summarizer=summarizer)

    text = (tmp_path / "day" / "2026-05-13.md").read_text(encoding="utf-8")
    assert text.startswith("## 09:30:00")
    assert text.count("\n## ") == 1
    assert "beartools doctor" in text
    assert "beartools diary summary --date 2026-05-10" in text


def test_append_command_memory_writes_fallback_when_summarizer_fails(tmp_path: Path) -> None:
    output_path = append_command_memory(
        memory_root=tmp_path,
        memory_input=_build_memory_input(),
        summarizer=_FailingCommandSummarizer(),
    )

    text = output_path.read_text(encoding="utf-8")
    assert "LLM 总结失败：模型不可用" in text
    assert "- 退出码：0" in text


def test_generate_daily_summary_uses_large_summarizer_and_overwrites_day_summary(tmp_path: Path) -> None:
    day_file = tmp_path / "day" / "2026-05-10.md"
    day_file.parent.mkdir(parents=True)
    day_file.write_text("## 09:00:00 beartools doctor\n\n- 结果：doctor 已运行\n", encoding="utf-8")
    summary_file = tmp_path / "summary" / "2026-05-10.md"
    summary_file.parent.mkdir(parents=True)
    summary_file.write_text("旧总结", encoding="utf-8")
    summarizer = _FakeDailySummarizer()

    output_path = generate_daily_summary(
        memory_root=tmp_path,
        target_date=date(2026, 5, 10),
        summarizer=summarizer,
    )

    assert output_path == summary_file
    text = summary_file.read_text(encoding="utf-8")
    assert text.startswith("# 2026-05-10")
    assert "今天主要在做：验证记忆系统" in text
    assert summarizer.calls == ["## 09:00:00 beartools doctor\n\n- 结果：doctor 已运行\n"]


def test_generate_daily_summary_errors_when_day_file_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="day 记忆不存在"):
        generate_daily_summary(
            memory_root=tmp_path,
            target_date=date(2026, 5, 10),
            summarizer=_FakeDailySummarizer(),
        )


def test_append_missing_daily_summaries_fills_only_existing_day_without_overwrite(tmp_path: Path) -> None:
    day_dir = tmp_path / "day"
    day_dir.mkdir(parents=True)
    (day_dir / "2026-05-01.md").write_text("day one", encoding="utf-8")
    (day_dir / "2026-05-03.md").write_text("day three", encoding="utf-8")
    summary_dir = tmp_path / "summary"
    summary_dir.mkdir(parents=True)
    existing_summary = summary_dir / "2026-05-03.md"
    existing_summary.write_text("保留旧 summary", encoding="utf-8")
    summarizer = _FakeDailySummarizer()

    created = append_missing_daily_summaries(
        memory_root=tmp_path,
        month="2026-05",
        today=date(2026, 5, 4),
        summarizer=summarizer,
    )

    assert created == [tmp_path / "summary" / "2026-05-01.md"]
    assert (tmp_path / "summary" / "2026-05-01.md").exists()
    assert existing_summary.read_text(encoding="utf-8") == "保留旧 summary"
    assert summarizer.calls == ["day one"]


def test_memory_prompts_are_managed_in_prompt_directory() -> None:
    manager = PromptManager()

    assert "cli_command_memory" in manager.list_templates()
    assert "cli_daily_summary" in manager.list_templates()
    command_prompt = build_command_memory_prompt(_build_memory_input())
    daily_prompt = build_daily_summary_prompt("## 09:00:00 beartools doctor")

    assert "beartools doctor" in command_prompt
    assert "CLI/console 输出" in command_prompt
    assert "## 09:00:00 beartools doctor" in daily_prompt
    assert "今天主要在做" in daily_prompt
