"""fetch 命令模块

根据 URL 域名分发下载任务。
"""

from __future__ import annotations

import asyncio

from rich.console import Console
import typer

from beartools.fetch import fetch_url

console = Console()


def fetch(
    url: str = typer.Argument(..., help="要抓取的 URL"),
) -> None:
    """根据URL抓取内容，目前支持 weixin.qq.com 域名"""
    try:
        result = asyncio.run(fetch_url(url))
    except ValueError as e:
        console.print(str(e), style="yellow")
        raise typer.Exit(1) from e
    except FileNotFoundError as e:
        console.print(f"错误: {e}", style="red")
        raise typer.Exit(1) from e
    except TimeoutError as e:
        console.print(f"错误: {e}", style="red")
        raise typer.Exit(1) from e
    except RuntimeError as e:
        console.print(str(e))
        console.print("❌ 下载失败", style="red")
        raise typer.Exit(1) from e

    console.print(f"下载目录: {result.target_dir}", style="dim")
    console.print(result.output)
    console.print("✅ 下载成功", style="green")

    for embed in result.embed_results:
        for ref in embed.missing:
            console.print(f"  ⚠️  未找到图片（已保留原引用）: {ref}", style="yellow")
        console.print(f"✅ 已生成: {embed.out_file}", style="green")
