"""记忆系统业务逻辑。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import date, timedelta
import os
from pathlib import Path
import re
import shlex
from typing import Protocol, cast, runtime_checkable

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from beartools.llm.factory import LLFactory
from beartools.llm.pydantic_openai import create_openai_responses_model
from beartools.llm.runtime import _is_async_anthropic_client
from beartools.logger import get_logger
from beartools.memory.models import CommandMemoryInput, CommandSummarizer, DailySummarizer
from beartools.memory.prompts import build_command_memory_prompt, build_daily_summary_prompt

MAX_CAPTURE_CHARS = 4000
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")


class _LoggerProtocol(Protocol):
    def info(self, msg: str, *args: object) -> None: ...


@runtime_checkable
class _MemoryModelInfoCarrier(Protocol):
    memory_model_info: _MemoryModelInfo


@dataclass(frozen=True, slots=True)
class _MemoryModelInfo:
    """记录写入 memory 时使用的模型信息。"""

    tier: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class _LLMSummaryResult:
    """LLM 摘要文本与模型信息。"""

    text: str
    model_info: _MemoryModelInfo


_UNKNOWN_MEMORY_MODEL_INFO = _MemoryModelInfo(tier="unknown", provider="unknown", model="unknown")
_HELP_MEMORY_MODEL_INFO = _MemoryModelInfo(tier="none", provider="none", model="help")
_FALLBACK_MEMORY_MODEL_INFO = _MemoryModelInfo(tier="unknown", provider="fallback", model="summarizer-error")


def _get_logger() -> _LoggerProtocol:
    """返回 memory 模块日志器。"""

    return get_logger(__name__)


def get_memory_root() -> Path:
    """读取记忆根目录。"""

    return Path(os.environ.get("BEARTOOLS_MEMORY_ROOT", "memory"))


def truncate_text(text: str, limit: int = MAX_CAPTURE_CHARS) -> str:
    """截断命令输出，避免记忆 prompt 和文件过大。"""

    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[已截断 {len(text) - limit} 字符]"


def sanitize_console_text(text: str) -> str:
    """清理终端控制字符，保留适合写入 Markdown 的可读输出。"""

    return ANSI_ESCAPE_PATTERN.sub("", text)


def append_command_memory(
    *,
    memory_root: Path,
    memory_input: CommandMemoryInput,
    summarizer: CommandSummarizer,
) -> Path:
    """追加单次命令记忆。"""

    safe_input = replace(
        memory_input,
        stdout=truncate_text(sanitize_console_text(memory_input.stdout)),
        stderr=truncate_text(sanitize_console_text(memory_input.stderr)),
        help_text=truncate_text(memory_input.help_text, limit=1000),
    )
    day_path = memory_root / "day" / f"{safe_input.started_at.date().isoformat()}.md"
    day_path.parent.mkdir(parents=True, exist_ok=True)
    if _is_help_command(safe_input.command):
        summary = _build_help_command_summary(safe_input.help_text)
        model_info = _HELP_MEMORY_MODEL_INFO
    else:
        try:
            summary = summarizer.summarize_command(safe_input).strip()
            model_info = _extract_memory_model_info(summarizer, fallback=_UNKNOWN_MEMORY_MODEL_INFO)
        except Exception as exc:
            # 摘要模型失败不能影响原命令结果；这里保留 fallback 记忆。
            summary = f"- 目的：记录 beartools 命令执行\n- 结果：LLM 总结失败：{exc}"
            model_info = _FALLBACK_MEMORY_MODEL_INFO

    entry = "\n".join(
        [
            f"## {safe_input.started_at:%H:%M:%S} {safe_input.command}",
            "",
            summary,
            f"- 退出码：{safe_input.exit_code}",
            f"- help：{_first_line(safe_input.help_text)}",
            "",
            "### console stdout",
            "",
            "```text",
            safe_input.stdout.strip() or "无",
            "```",
            "",
            "### console stderr",
            "",
            "```text",
            safe_input.stderr.strip() or "无",
            "```",
            "",
        ]
    )
    with day_path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(entry)
    _log_memory_written(kind="command", path=day_path, model_info=model_info, length=len(entry))
    return day_path


def generate_daily_summary(
    *,
    memory_root: Path,
    target_date: date,
    summarizer: DailySummarizer,
    current_day: date | None = None,
) -> Path:
    """根据 day 记忆生成或覆盖当天 summary。"""

    resolved_current_day = current_day or today()
    if target_date >= resolved_current_day:
        raise ValueError("不能处理今天或未来日期")

    day_path = memory_root / "day" / f"{target_date.isoformat()}.md"
    if not day_path.exists():
        raise FileNotFoundError(f"day 记忆不存在: {day_path}")

    day_content = day_path.read_text(encoding="utf-8")
    summary = summarizer.summarize_day(day_content).strip()
    summary_path = memory_root / "summary" / f"{target_date.isoformat()}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = f"# {target_date.isoformat()}\n\n{summary}\n"
    summary_path.write_text(output_text, encoding="utf-8")
    _log_memory_written(
        kind="daily-summary",
        path=summary_path,
        model_info=_extract_memory_model_info(summarizer, fallback=_UNKNOWN_MEMORY_MODEL_INFO),
        length=len(output_text),
    )
    return summary_path


def append_missing_daily_summaries(
    *,
    memory_root: Path,
    start_date: date,
    end_date: date,
    today: date,
    summarizer: DailySummarizer,
) -> list[Path]:
    """补齐日期范围内已有 day 但缺失的 summary。"""

    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")
    if end_date >= today:
        raise ValueError("不能处理今天或未来日期")

    created: list[Path] = []
    current = start_date
    while current <= end_date:
        day_path = memory_root / "day" / f"{current.isoformat()}.md"
        summary_path = memory_root / "summary" / f"{current.isoformat()}.md"
        if day_path.exists() and not summary_path.exists():
            created.append(
                generate_daily_summary(
                    memory_root=memory_root,
                    target_date=current,
                    summarizer=summarizer,
                    current_day=today,
                )
            )
        current += timedelta(days=1)
    return created


def today() -> date:
    """返回当前日期，便于测试替换。"""

    return date.today()


def create_command_summarizer() -> CommandSummarizer:
    """创建 small 单次命令摘要器。"""

    fake_summary = os.environ.get("BEARTOOLS_MEMORY_FAKE_SUMMARY")
    if fake_summary is not None:
        return _StaticCommandSummarizer(fake_summary)
    return _LLMCommandSummarizer()


def create_daily_summarizer() -> DailySummarizer:
    """创建 large 日总结摘要器。"""

    fake_summary = os.environ.get("BEARTOOLS_DAILY_MEMORY_FAKE_SUMMARY")
    if fake_summary is not None:
        return _StaticDailySummarizer(fake_summary)
    return _LLMDailySummarizer()


def _first_line(text: str) -> str:
    """提取 help 第一行。"""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "无"


def _is_help_command(command: str) -> bool:
    """判断命令是否在请求帮助信息。"""

    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()
    return "--help" in args or "-h" in args


def _build_help_command_summary(help_text: str) -> str:
    """直接用 help 信息生成单次命令摘要，避免额外请求模型。"""

    help_summary = _first_line(help_text)
    return f"- 目的：查看 beartools 命令帮助\n- 结果：已输出帮助信息：{help_summary}"


class _StaticCommandSummarizer:
    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.memory_model_info = _MemoryModelInfo(tier="small", provider="static", model="fake-summary")

    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        return self._summary


class _StaticDailySummarizer:
    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.memory_model_info = _MemoryModelInfo(tier="large", provider="static", model="fake-summary")

    def summarize_day(self, day_content: str) -> str:
        return self._summary


class _LLMCommandSummarizer:
    def __init__(self) -> None:
        self.memory_model_info = _UNKNOWN_MEMORY_MODEL_INFO

    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        result = asyncio.run(_summarize_command_async(memory_input))
        self.memory_model_info = result.model_info
        return result.text


async def _summarize_command_async(memory_input: CommandMemoryInput) -> _LLMSummaryResult:
    """在同一事件循环内运行命令摘要并关闭模型客户端。"""

    factory = LLFactory()
    node = factory.list_candidates(type="any", model_size="small")[0]
    client = await factory.create_async_client(name=node.name, type="any", model_size=node.tier)
    model_info = _MemoryModelInfo(tier=node.tier, provider=node.provider, model=node.model)
    async with client:
        model = _build_pydantic_model(client, node.model, float(node.timeout_seconds))
        agent: Agent[None, str] = Agent(model=model, output_type=str)
        result = await agent.run(build_command_memory_prompt(memory_input))
        return _LLMSummaryResult(text=str(result.output), model_info=model_info)


class _LLMDailySummarizer:
    def __init__(self) -> None:
        self.memory_model_info = _UNKNOWN_MEMORY_MODEL_INFO

    def summarize_day(self, day_content: str) -> str:
        result = asyncio.run(_summarize_day_async(day_content))
        self.memory_model_info = result.model_info
        return result.text


async def _summarize_day_async(day_content: str) -> _LLMSummaryResult:
    """在同一事件循环内运行日总结并关闭模型客户端。"""

    factory = LLFactory()
    node = factory.list_candidates(type="any", model_size="large")[0]
    client = await factory.create_async_client(name=node.name, type="any", model_size=node.tier)
    model_info = _MemoryModelInfo(tier=node.tier, provider=node.provider, model=node.model)
    async with client:
        model = _build_pydantic_model(client, node.model, float(node.timeout_seconds))
        agent: Agent[None, str] = Agent(model=model, output_type=str)
        result = await agent.run(build_daily_summary_prompt(day_content))
        return _LLMSummaryResult(text=str(result.output), model_info=model_info)


def _build_pydantic_model(
    client: object, model_name: str, timeout_seconds: float
) -> OpenAIResponsesModel | AnthropicModel:
    """根据 SDK client 构建 PydanticAI model。"""

    if isinstance(client, AsyncOpenAI):
        return create_openai_responses_model(
            client,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
        )
    if _is_memory_async_anthropic_client(client):
        return AnthropicModel(
            model_name,
            provider=AnthropicProvider(anthropic_client=cast(AsyncAnthropic, client)),
        )
    raise RuntimeError("命令记忆摘要只支持 OpenAI 或 Anthropic async client")


def _is_memory_async_anthropic_client(client: object) -> bool:
    """兼容真实 Anthropic client 与测试中的 monkeypatch fake class。"""

    return _is_async_anthropic_client(client)


def _extract_memory_model_info(summarizer: object, *, fallback: _MemoryModelInfo) -> _MemoryModelInfo:
    """从摘要器读取模型信息，兼容普通测试摘要器。"""

    if isinstance(summarizer, _MemoryModelInfoCarrier):
        return summarizer.memory_model_info
    return fallback


def _log_memory_written(*, kind: str, path: Path, model_info: _MemoryModelInfo, length: int) -> None:
    """记录 memory 写入后的模型和长度。"""

    _get_logger().info(
        "memory 写入完成: type=%s path=%s tier=%s provider=%s model=%s length=%s",
        kind,
        path,
        model_info.tier,
        model_info.provider,
        model_info.model,
        length,
    )
