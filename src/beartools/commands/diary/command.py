"""Diary 记忆命令。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from rich.console import Console
import typer

from beartools.memory.service import (
    append_missing_daily_summaries,
    create_daily_summarizer,
    generate_daily_summary,
    get_memory_root,
    parse_month,
    today,
)

diary_app = typer.Typer(help="命令记忆日记", add_completion=False)
console = Console()


@diary_app.command("summary", help="总结某一天的命令记忆")  # type: ignore[misc]
def summary(
    target_date: str | None = typer.Option(None, "--date", help="要总结的日期，格式 YYYY-MM-DD"),
    memory_root: Path | None = typer.Option(None, "--memory-root", help="记忆根目录"),  # noqa: B008
) -> None:
    """使用 large 模型总结某一天。"""

    try:
        resolved_date = _parse_date_option(target_date) if target_date is not None else today()
    except ValueError as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc
    resolved_root = memory_root or get_memory_root()
    try:
        output_path = generate_daily_summary(
            memory_root=resolved_root,
            target_date=resolved_date,
            summarizer=create_daily_summarizer(),
        )
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"summary 已写入: {output_path}", style="green")


@diary_app.command("append", help="补齐本月缺失的每日总结")  # type: ignore[misc]
def append(
    month: str | None = typer.Option(None, "--month", help="要补齐的月份，格式 YYYY-MM"),  # noqa: B008
    memory_root: Path | None = typer.Option(None, "--memory-root", help="记忆根目录"),  # noqa: B008
) -> None:
    """补齐指定月份已存在 day 记忆但缺失的 summary。"""

    current_day = today()
    resolved_month = month or current_day.strftime("%Y-%m")
    resolved_root = memory_root or get_memory_root()
    try:
        parse_month(resolved_month)
        created = append_missing_daily_summaries(
            memory_root=resolved_root,
            month=resolved_month,
            today=current_day,
            summarizer=create_daily_summarizer(),
        )
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"补齐 {len(created)} 天 summary", style="green")
    for path in created:
        console.print(f"- {path}")


def _parse_date_option(value: str) -> date:
    """解析 YYYY-MM-DD 日期选项。"""

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期格式必须是 YYYY-MM-DD") from exc
