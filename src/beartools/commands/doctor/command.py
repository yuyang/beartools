"""Doctor 健康检查命令主模块

执行所有配置启用的健康检查项，并以彩色格式输出检查结果。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import time

from rich.console import Console
from rich.text import Text

from beartools.commands.doctor.base import (
    CheckRegistry,
    CheckResult,
    CheckStatus,
    auto_discover_checks,
)
from beartools.config import get_config
from beartools.logger import get_logger

# 初始化控制台和日志
console = Console()
logger = get_logger(__name__)


def print_result(result: CheckResult) -> None:
    """打印单个检查结果，使用彩色输出

    Args:
        result: 检查结果对象
    """
    if result.status == CheckStatus.SUCCESS:
        # 绿色 ✅ 成功输出
        status_mark = Text("✅ ", style="green")
        name_text = Text(result.name, style="bold green")
        message_text = Text(f"{result.message}", style="green")
        duration_text = Text(f" [{result.duration:.2f}s]", style="yellow")
        line = Text.assemble(status_mark, name_text, ": ", message_text, duration_text)
        console.print(line)
        # 如果有详细信息，以灰色打印
        if result.detail:
            detail_lines = result.detail.split("\n")
            for detail_line in detail_lines:
                console.print(Text(f"  {detail_line}", style="dim gray"))

    elif result.status == CheckStatus.FAILURE:
        # 红色 ❌ 失败输出
        status_mark = Text("❌ ", style="red")
        name_text = Text(result.name, style="bold red")
        message_text = Text(f"{result.message}", style="red")
        line = Text.assemble(status_mark, name_text, ": ", message_text)
        console.print(line)
        # 如果有详细信息，以灰色打印
        if result.detail:
            detail_lines = result.detail.split("\n")
            for detail_line in detail_lines:
                console.print(Text(f"  {detail_line}", style="dim gray"))

    elif result.status == CheckStatus.WARNING:
        # 黄色 ⚠️ 警告输出
        status_mark = Text("⚠️  ", style="yellow")
        name_text = Text(result.name, style="bold yellow")
        message_text = Text(f"{result.message}", style="yellow")
        duration_text = Text(f" [{result.duration:.2f}s]", style="dim")
        result_line = Text.assemble(status_mark, name_text, ": ", message_text, duration_text)
        console.print(result_line)
        # 如果有详细信息，以灰色打印
        if result.detail:
            detail_lines = result.detail.split("\n")
            for detail_line in detail_lines:
                console.print(Text(f"  {detail_line}", style="dim gray"))


async def _run_single_check(check_name: str) -> CheckResult:
    """运行单个检查项

    Args:
        check_name: 检查项名称

    Returns:
        CheckResult: 检查结果
    """
    check = CheckRegistry.get_check(check_name)
    if check is None:
        return CheckResult(
            name=check_name,
            status=CheckStatus.FAILURE,
            message=f"未找到检查项 {check_name}，请检查配置是否正确",
            duration=0.0,
            detail=None,
        )

    start_time = time.time()
    try:
        result = await check.run()
        result.duration = time.time() - start_time
        return result
    except Exception as e:
        duration = time.time() - start_time
        return CheckResult(
            name=check_name,
            status=CheckStatus.FAILURE,
            message=f"检查执行时发生未捕获异常: {str(e)}",
            duration=duration,
            detail=str(e),
        )


async def run_checks_stream() -> AsyncGenerator[CheckResult]:
    """流式并发运行所有启用的检查项，每完成一个就返回一个结果

    Yields:
        CheckResult: 单个检查项的执行结果
    """
    config = get_config()
    auto_discover_checks()

    enabled_checks = config.doctor.enabled_checks

    # 创建所有任务
    tasks = [asyncio.create_task(_run_single_check(check_name)) for check_name in enabled_checks]

    # 按完成顺序返回结果
    for task in asyncio.as_completed(tasks):
        result = await task
        yield result


async def run_checks() -> list[CheckResult]:
    """并发运行所有启用的检查项，返回所有结果列表（兼容原有接口）

    Returns:
        list[CheckResult]: 所有检查项的执行结果列表
    """
    return [result async for result in run_checks_stream()]


def print_summary(success_count: int, failure_count: int, warning_count: int) -> None:
    """打印检查结果汇总

    Args:
        success_count: 成功数量
        failure_count: 失败数量
        warning_count: 警告数量
    """
    console.print()
    total = success_count + failure_count + warning_count
    summary_text = f"检查完成: 共 {total} 项检查"

    parts: list[Text] = []
    parts.append(Text("🏁 ", style="bold blue"))
    parts.append(Text(summary_text, style="bold blue"))

    if success_count > 0:
        parts.append(Text(f" ✓ {success_count} 成功", style="green"))
    if failure_count > 0:
        parts.append(Text(f" ✗ {failure_count} 失败", style="red"))
    if warning_count > 0:
        parts.append(Text(f" ⚠ {warning_count} 警告", style="yellow"))

    console.print(Text.assemble(*parts))


async def _doctor_command_async() -> None:
    """异步执行doctor命令，流式输出检查结果"""
    console.print("🏥 运行环境检查中...\n", style="bold blue")

    success_count = 0
    failure_count = 0
    warning_count = 0

    # 流式遍历检查结果，完成一个打印一个
    async for result in run_checks_stream():
        print_result(result)
        # 记录到日志
        logger.info(
            "检查完成: %s - %s - %.2fs",
            result.name,
            result.status.value,
            result.duration,
            extra={"detail": result.detail},
        )

        if result.status == CheckStatus.SUCCESS:
            success_count += 1
        elif result.status == CheckStatus.FAILURE:
            failure_count += 1
        elif result.status == CheckStatus.WARNING:
            warning_count += 1

    print_summary(success_count, failure_count, warning_count)

    # 记录汇总信息到日志
    total = success_count + failure_count + warning_count
    logger.info(
        "🏁 检查完成: 共 %d 项检查 ✓ %d 成功 ✗ %d 失败 ⚠ %d 警告", total, success_count, failure_count, warning_count
    )


def doctor_command() -> None:
    """Doctor 健康检查命令入口

    执行所有配置启用的健康检查，并输出彩色结果和汇总统计。
    """
    asyncio.run(_doctor_command_async())
