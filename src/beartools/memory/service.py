"""记忆系统业务逻辑。"""

from __future__ import annotations

import asyncio
import calendar
from dataclasses import replace
from datetime import date, timedelta
import os
from pathlib import Path
import re

from openai import AsyncOpenAI
from pydantic_ai import Agent

from beartools.llm.factory import LLFactory
from beartools.llm.pydantic_openai import create_openai_responses_model
from beartools.llm.runtime import get_openai_compatible_node
from beartools.memory.models import CommandMemoryInput, CommandSummarizer, DailySummarizer
from beartools.memory.prompts import build_command_memory_prompt, build_daily_summary_prompt

MAX_CAPTURE_CHARS = 4000
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")


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
    try:
        summary = summarizer.summarize_command(safe_input).strip()
    except Exception as exc:
        # 摘要模型失败不能影响原命令结果；这里保留 fallback 记忆。
        summary = f"- 目的：记录 beartools 命令执行\n- 结果：LLM 总结失败：{exc}"

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
    return day_path


def generate_daily_summary(*, memory_root: Path, target_date: date, summarizer: DailySummarizer) -> Path:
    """根据 day 记忆生成或覆盖当天 summary。"""

    day_path = memory_root / "day" / f"{target_date.isoformat()}.md"
    if not day_path.exists():
        raise FileNotFoundError(f"day 记忆不存在: {day_path}")

    day_content = day_path.read_text(encoding="utf-8")
    summary = summarizer.summarize_day(day_content).strip()
    summary_path = memory_root / "summary" / f"{target_date.isoformat()}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(f"# {target_date.isoformat()}\n\n{summary}\n", encoding="utf-8")
    return summary_path


def append_missing_daily_summaries(
    *,
    memory_root: Path,
    month: str,
    today: date,
    summarizer: DailySummarizer,
) -> list[Path]:
    """补齐指定月份中已有 day 但缺失的 summary。"""

    year, month_number = parse_month(month)
    if (year, month_number) > (today.year, today.month):
        raise ValueError("不能处理未来月份")

    last_day = _resolve_append_last_day(year=year, month_number=month_number, today=today)
    created: list[Path] = []
    current = date(year, month_number, 1)
    while current <= last_day:
        day_path = memory_root / "day" / f"{current.isoformat()}.md"
        summary_path = memory_root / "summary" / f"{current.isoformat()}.md"
        if day_path.exists() and not summary_path.exists():
            created.append(generate_daily_summary(memory_root=memory_root, target_date=current, summarizer=summarizer))
        current += timedelta(days=1)
    return created


def parse_month(month: str) -> tuple[int, int]:
    """解析 YYYY-MM 月份。"""

    if re.fullmatch(r"\d{4}-\d{2}", month) is None:
        raise ValueError("月份格式必须是 YYYY-MM")
    year_text, month_text = month.split("-", maxsplit=1)
    year = int(year_text)
    month_number = int(month_text)
    if month_number < 1 or month_number > 12:
        raise ValueError("月份格式必须是 YYYY-MM")
    return year, month_number


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


def _resolve_append_last_day(*, year: int, month_number: int, today: date) -> date:
    """计算 append 处理到哪一天。"""

    if year == today.year and month_number == today.month:
        return today - timedelta(days=1)
    _, last_day_number = calendar.monthrange(year, month_number)
    return date(year, month_number, last_day_number)


def _first_line(text: str) -> str:
    """提取 help 第一行。"""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "无"


class _StaticCommandSummarizer:
    def __init__(self, summary: str) -> None:
        self._summary = summary

    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        return self._summary


class _StaticDailySummarizer:
    def __init__(self, summary: str) -> None:
        self._summary = summary

    def summarize_day(self, day_content: str) -> str:
        return self._summary


class _LLMCommandSummarizer:
    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        return asyncio.run(_summarize_command_async(memory_input))


async def _summarize_command_async(memory_input: CommandMemoryInput) -> str:
    """在同一事件循环内运行命令摘要并关闭模型客户端。"""

    node = get_openai_compatible_node("small")
    client = await LLFactory().create_async_client_for_node(node)
    if not isinstance(client, AsyncOpenAI):
        raise RuntimeError("命令记忆摘要当前只支持 OpenAI 兼容 client")
    async with client:
        model = create_openai_responses_model(
            client,
            model_name=node.model,
            timeout_seconds=float(node.timeout_seconds),
        )
        agent: Agent[None, str] = Agent(model=model, output_type=str)
        result = await agent.run(build_command_memory_prompt(memory_input))
        return str(result.output)


class _LLMDailySummarizer:
    def summarize_day(self, day_content: str) -> str:
        return asyncio.run(_summarize_day_async(day_content))


async def _summarize_day_async(day_content: str) -> str:
    """在同一事件循环内运行日总结并关闭模型客户端。"""

    node = get_openai_compatible_node("large")
    client = await LLFactory().create_async_client_for_node(node)
    if not isinstance(client, AsyncOpenAI):
        raise RuntimeError("日记忆摘要当前只支持 OpenAI 兼容 client")
    async with client:
        model = create_openai_responses_model(
            client,
            model_name=node.model,
            timeout_seconds=float(node.timeout_seconds),
        )
        agent: Agent[None, str] = Agent(model=model, output_type=str)
        result = await agent.run(build_daily_summary_prompt(day_content))
        return str(result.output)
