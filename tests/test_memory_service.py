from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest import MonkeyPatch

from beartools.memory.models import CommandMemoryInput
from beartools.memory.prompts import build_command_memory_prompt, build_daily_summary_prompt
import beartools.memory.service as memory_service
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
        self.memory_model_info = memory_service._MemoryModelInfo(
            tier="small",
            provider="openai",
            model="small-model",
        )

    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        self.calls.append(memory_input)
        return "- 目的：查看 doctor 状态\n- 结果：doctor 已输出健康检查"


class _FailingCommandSummarizer:
    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        raise RuntimeError("模型不可用")


class _FakeDailySummarizer:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.memory_model_info = memory_service._MemoryModelInfo(
            tier="large",
            provider="openai",
            model="large-model",
        )

    def summarize_day(self, day_content: str) -> str:
        self.calls.append(day_content)
        return "- 今天主要在做：验证记忆系统\n- 关键结果：summary 已生成\n- 未完成/后续：继续测试"


def _fake_openai_responses_model(client: object, **kwargs: object) -> str:
    return "fake-model"


def _fake_anthropic_model(model_name: str, **kwargs: object) -> str:
    del kwargs
    return f"anthropic-model:{model_name}"


class _FakeAnthropicProvider:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _FakeAsyncClient:
    def __init__(self, close_calls: list[str]) -> None:
        self._close_calls = close_calls

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        self._close_calls.append("closed")


class _FakeLLFactory:
    requested_tiers: list[str] = []
    requested_types: list[str] = []
    close_calls: list[str] = []
    provider = "openai"

    def list_candidates(self, *, type: str, model_size: str) -> list[SimpleNamespace]:
        self.requested_types.append(type)
        return [
            SimpleNamespace(
                name=f"{model_size}-name",
                tier=model_size,
                provider=self.provider,
                model=f"{model_size}-model",
                timeout_seconds=30,
            )
        ]

    async def create_async_client(self, *, name: str, type: str, model_size: str) -> _FakeAsyncClient:
        del name
        self.requested_types.append(type)
        self.requested_tiers.append(model_size)
        return _FakeAsyncClient(self.close_calls)


class _FakeMemoryAgent:
    created_models: list[object] = []
    prompt_inputs: list[str] = []
    output = "命令总结"

    def __init__(self, *, model: object, output_type: type[str]) -> None:
        del output_type
        self.created_models.append(model)

    async def run(self, prompt: str) -> SimpleNamespace:
        self.prompt_inputs.append(prompt)
        return SimpleNamespace(output=self.output)


class _FakeLogger:
    messages: list[tuple[str, tuple[object, ...]]] = []

    def info(self, message: str, *args: object) -> None:
        self.messages.append((message, args))


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


def test_append_command_memory_creates_day_file_and_uses_small_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summarizer = _FakeCommandSummarizer()
    _FakeLogger.messages = []
    monkeypatch.setattr(memory_service, "_get_logger", lambda: _FakeLogger())

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
    assert _FakeLogger.messages == [
        (
            "memory 写入完成: type=%s path=%s tier=%s provider=%s model=%s length=%s",
            ("command", output_path, "small", "openai", "small-model", len(text)),
        )
    ]


def test_append_command_memory_uses_help_summary_without_llm_for_help_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summarizer = _FakeCommandSummarizer()
    _FakeLogger.messages = []
    monkeypatch.setattr(memory_service, "_get_logger", lambda: _FakeLogger())
    memory_input = CommandMemoryInput(
        command="beartools doctor --help",
        help_text="运行环境健康检查",
        stdout="Usage: doctor [OPTIONS]\n\n运行环境健康检查\n",
        stderr="",
        exit_code=0,
        started_at=datetime(2026, 5, 13, 9, 30, 0),
        duration_seconds=0.1,
    )

    output_path = append_command_memory(memory_root=tmp_path, memory_input=memory_input, summarizer=summarizer)

    text = output_path.read_text(encoding="utf-8")
    assert "- 目的：查看 beartools 命令帮助" in text
    assert "- 结果：已输出帮助信息：运行环境健康检查" in text
    assert summarizer.calls == []
    assert _FakeLogger.messages == [
        (
            "memory 写入完成: type=%s path=%s tier=%s provider=%s model=%s length=%s",
            ("command", output_path, "none", "none", "help", len(text)),
        )
    ]


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


def test_append_command_memory_writes_fallback_when_summarizer_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeLogger.messages = []
    monkeypatch.setattr(memory_service, "_get_logger", lambda: _FakeLogger())

    output_path = append_command_memory(
        memory_root=tmp_path,
        memory_input=_build_memory_input(),
        summarizer=_FailingCommandSummarizer(),
    )

    text = output_path.read_text(encoding="utf-8")
    assert "LLM 总结失败：模型不可用" in text
    assert "- 退出码：0" in text
    assert _FakeLogger.messages == [
        (
            "memory 写入完成: type=%s path=%s tier=%s provider=%s model=%s length=%s",
            ("command", output_path, "unknown", "fallback", "summarizer-error", len(text)),
        )
    ]


def test_generate_daily_summary_uses_large_summarizer_and_overwrites_day_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeLogger.messages = []
    monkeypatch.setattr(memory_service, "_get_logger", lambda: _FakeLogger())
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
    assert _FakeLogger.messages == [
        (
            "memory 写入完成: type=%s path=%s tier=%s provider=%s model=%s length=%s",
            ("daily-summary", output_path, "large", "openai", "large-model", len(text)),
        )
    ]


def test_generate_daily_summary_errors_when_day_file_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="day 记忆不存在"):
        generate_daily_summary(
            memory_root=tmp_path,
            target_date=date(2026, 5, 10),
            summarizer=_FakeDailySummarizer(),
        )


def test_generate_daily_summary_rejects_today_or_future_date(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    day_dir = tmp_path / "day"
    day_dir.mkdir(parents=True)
    (day_dir / "2026-05-13.md").write_text("today day", encoding="utf-8")
    (day_dir / "2026-05-14.md").write_text("future day", encoding="utf-8")
    monkeypatch.setattr(memory_service, "today", lambda: date(2026, 5, 13))

    with pytest.raises(ValueError, match="不能处理今天或未来日期"):
        generate_daily_summary(
            memory_root=tmp_path,
            target_date=date(2026, 5, 13),
            summarizer=_FakeDailySummarizer(),
        )
    with pytest.raises(ValueError, match="不能处理今天或未来日期"):
        generate_daily_summary(
            memory_root=tmp_path,
            target_date=date(2026, 5, 14),
            summarizer=_FakeDailySummarizer(),
        )


def test_append_missing_daily_summaries_fills_only_existing_day_without_overwrite(tmp_path: Path) -> None:
    day_dir = tmp_path / "day"
    day_dir.mkdir(parents=True)
    (day_dir / "2026-04-30.md").write_text("outside range", encoding="utf-8")
    (day_dir / "2026-05-01.md").write_text("day one", encoding="utf-8")
    (day_dir / "2026-05-03.md").write_text("day three", encoding="utf-8")
    (day_dir / "2026-05-04.md").write_text("today day", encoding="utf-8")
    summary_dir = tmp_path / "summary"
    summary_dir.mkdir(parents=True)
    existing_summary = summary_dir / "2026-05-03.md"
    existing_summary.write_text("保留旧 summary", encoding="utf-8")
    summarizer = _FakeDailySummarizer()

    created = append_missing_daily_summaries(
        memory_root=tmp_path,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        today=date(2026, 5, 4),
        summarizer=summarizer,
    )

    assert created == [tmp_path / "summary" / "2026-05-01.md"]
    assert not (tmp_path / "summary" / "2026-04-30.md").exists()
    assert (tmp_path / "summary" / "2026-05-01.md").exists()
    assert not (tmp_path / "summary" / "2026-05-04.md").exists()
    assert existing_summary.read_text(encoding="utf-8") == "保留旧 summary"
    assert summarizer.calls == ["day one"]


def test_append_missing_daily_summaries_rejects_today_or_future_end_date(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不能处理今天或未来日期"):
        append_missing_daily_summaries(
            memory_root=tmp_path,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 4),
            today=date(2026, 5, 4),
            summarizer=_FakeDailySummarizer(),
        )


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


def test_llm_command_summarizer_closes_model_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeLLFactory.requested_tiers = []
    _FakeLLFactory.requested_types = []
    _FakeLLFactory.close_calls = []
    _FakeLLFactory.provider = "openai"
    _FakeMemoryAgent.created_models = []
    _FakeMemoryAgent.prompt_inputs = []
    _FakeMemoryAgent.output = "命令总结"

    monkeypatch.setattr(memory_service, "LLFactory", _FakeLLFactory)
    monkeypatch.setattr(memory_service, "AsyncOpenAI", _FakeAsyncClient)
    monkeypatch.setattr(memory_service, "create_openai_responses_model", _fake_openai_responses_model)
    monkeypatch.setattr(memory_service, "Agent", _FakeMemoryAgent)

    summarizer = memory_service._LLMCommandSummarizer()
    summary = summarizer.summarize_command(_build_memory_input())

    assert summary == "命令总结"
    assert _FakeLLFactory.requested_tiers == ["small"]
    assert _FakeLLFactory.requested_types == ["any", "any"]
    assert _FakeMemoryAgent.created_models == ["fake-model"]
    assert "beartools doctor" in _FakeMemoryAgent.prompt_inputs[0]
    assert _FakeLLFactory.close_calls == ["closed"]
    assert summarizer.memory_model_info == memory_service._MemoryModelInfo(
        tier="small",
        provider="openai",
        model="small-model",
    )


def test_llm_command_summarizer_supports_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeLLFactory.requested_tiers = []
    _FakeLLFactory.requested_types = []
    _FakeLLFactory.close_calls = []
    _FakeLLFactory.provider = "anthropic"
    _FakeMemoryAgent.created_models = []
    _FakeMemoryAgent.prompt_inputs = []
    _FakeMemoryAgent.output = "命令总结"

    monkeypatch.setattr(memory_service, "LLFactory", _FakeLLFactory)
    monkeypatch.setattr(
        memory_service,
        "_is_memory_async_anthropic_client",
        lambda client: isinstance(client, _FakeAsyncClient),
    )
    monkeypatch.setattr(memory_service, "AnthropicModel", _fake_anthropic_model)
    monkeypatch.setattr(memory_service, "AnthropicProvider", _FakeAnthropicProvider)
    monkeypatch.setattr(memory_service, "Agent", _FakeMemoryAgent)

    summarizer = memory_service._LLMCommandSummarizer()
    summary = summarizer.summarize_command(_build_memory_input())

    assert summary == "命令总结"
    assert _FakeLLFactory.requested_tiers == ["small"]
    assert _FakeLLFactory.requested_types == ["any", "any"]
    assert _FakeMemoryAgent.created_models == ["anthropic-model:small-model"]
    assert "beartools doctor" in _FakeMemoryAgent.prompt_inputs[0]
    assert _FakeLLFactory.close_calls == ["closed"]
    assert summarizer.memory_model_info == memory_service._MemoryModelInfo(
        tier="small",
        provider="anthropic",
        model="small-model",
    )


def test_llm_daily_summarizer_closes_model_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeLLFactory.requested_tiers = []
    _FakeLLFactory.requested_types = []
    _FakeLLFactory.close_calls = []
    _FakeLLFactory.provider = "openai"
    _FakeMemoryAgent.created_models = []
    _FakeMemoryAgent.prompt_inputs = []
    _FakeMemoryAgent.output = "日总结"

    monkeypatch.setattr(memory_service, "LLFactory", _FakeLLFactory)
    monkeypatch.setattr(memory_service, "AsyncOpenAI", _FakeAsyncClient)
    monkeypatch.setattr(memory_service, "create_openai_responses_model", _fake_openai_responses_model)
    monkeypatch.setattr(memory_service, "Agent", _FakeMemoryAgent)

    summarizer = memory_service._LLMDailySummarizer()
    summary = summarizer.summarize_day("day content")

    assert summary == "日总结"
    assert _FakeLLFactory.requested_tiers == ["large"]
    assert _FakeLLFactory.requested_types == ["any", "any"]
    assert _FakeMemoryAgent.created_models == ["fake-model"]
    assert _FakeMemoryAgent.prompt_inputs == [build_daily_summary_prompt("day content")]
    assert _FakeLLFactory.close_calls == ["closed"]
    assert summarizer.memory_model_info == memory_service._MemoryModelInfo(
        tier="large",
        provider="openai",
        model="large-model",
    )


def test_llm_daily_summarizer_supports_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeLLFactory.requested_tiers = []
    _FakeLLFactory.requested_types = []
    _FakeLLFactory.close_calls = []
    _FakeLLFactory.provider = "anthropic"
    _FakeMemoryAgent.created_models = []
    _FakeMemoryAgent.prompt_inputs = []
    _FakeMemoryAgent.output = "日总结"

    monkeypatch.setattr(memory_service, "LLFactory", _FakeLLFactory)
    monkeypatch.setattr(
        memory_service,
        "_is_memory_async_anthropic_client",
        lambda client: isinstance(client, _FakeAsyncClient),
    )
    monkeypatch.setattr(memory_service, "AnthropicModel", _fake_anthropic_model)
    monkeypatch.setattr(memory_service, "AnthropicProvider", _FakeAnthropicProvider)
    monkeypatch.setattr(memory_service, "Agent", _FakeMemoryAgent)

    summarizer = memory_service._LLMDailySummarizer()
    summary = summarizer.summarize_day("day content")

    assert summary == "日总结"
    assert _FakeLLFactory.requested_tiers == ["large"]
    assert _FakeLLFactory.requested_types == ["any", "any"]
    assert _FakeMemoryAgent.created_models == ["anthropic-model:large-model"]
    assert _FakeMemoryAgent.prompt_inputs == [build_daily_summary_prompt("day content")]
    assert _FakeLLFactory.close_calls == ["closed"]
    assert summarizer.memory_model_info == memory_service._MemoryModelInfo(
        tier="large",
        provider="anthropic",
        model="large-model",
    )
