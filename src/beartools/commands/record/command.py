"""记录管理命令模块

提供记录管理相关的命令行操作。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from beartools.record import record_manager, Record

console = Console()
app = typer.Typer(help="记录管理相关操作")


async def _get_all_async() -> list[Record]:
    """异步执行初始化和查询"""
    await record_manager.init()
    return await record_manager.get_all()


@app.command(name="getall", help="列出所有记录（最近100条，按更新时间倒序）")  # type: ignore
def get_all() -> None:
    """列出所有记录，最多显示最近100条，按更新时间从新到旧排序"""
    records = asyncio.run(_get_all_async())

    if not records:
        console.print("ℹ️ 暂无记录", style="yellow")
        return

    # 创建表格输出
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("序号", width=4)
    table.add_column("ID", width=20)
    table.add_column("名称", width=30)
    table.add_column("URL", width=50, overflow="fold")
    table.add_column("更新时间", width=20)

    for idx, record in enumerate(records, 1):
        time_str = record.update_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        table.add_row(str(idx), record.id, record.name, record.url, time_str)

    console.print(table)
    console.print(f"\n总计: {len(records)} 条记录", style="dim")
