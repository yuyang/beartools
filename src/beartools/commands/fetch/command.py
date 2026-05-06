"""fetch 命令模块

根据 URL 域名分发下载任务。
"""

from __future__ import annotations

import asyncio

from rich.console import Console
import typer

from beartools.config import get_config
from beartools.fetch import fetch_url
from beartools.markdown import EmbedResult
from beartools.siyuan import SiyuanError, SiyuanHandler

console = Console()
_siyuan_handler = SiyuanHandler()


def _upload_to_siyuan(embed_results: list[EmbedResult]) -> None:
    """将生成的 Markdown 文件上传到思源笔记"""
    config = get_config()
    target_notebook = config.siyuan.notebook
    target_path = config.siyuan.path

    if not target_notebook or not target_path:
        console.print("⚠️  思源笔记配置不完整，跳过自动上传", style="yellow")
        console.print("请在配置文件中设置 `siyuan.notebook` 和 `siyuan.path`", style="dim")
        return

    try:
        for embed in embed_results:
            doc_id = asyncio.run(_siyuan_handler.upload_md(str(embed.out_file), target_notebook, target_path))
            console.print(f"✅ 已上传到思源笔记，文档 ID: {doc_id}", style="green")
    except SiyuanError as e:
        console.print(f"❌ 上传到思源笔记失败: {e}", style="red")
        if "连接" in str(e):
            console.print("请检查思源笔记是否已启动，且API服务已开启", style="yellow")
        raise typer.Exit(1) from e


def fetch(
    url: str = typer.Argument(..., help="要抓取的 URL"),
    upload: bool = typer.Option(True, help="是否自动上传到思源笔记，默认开启"),
) -> None:
    """根据 URL 抓取内容，目前支持 weixin.qq.com、x.com 和 twitter.com。"""
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
    console.print(f"Markdown 输出目录: {result.markdown_dir}", style="dim")
    console.print(f"原始 URL: {result.original_url}", style="dim")
    console.print(result.output)
    console.print("✅ 下载成功", style="green")

    for embed in result.embed_results:
        for ref in embed.missing:
            console.print(f"  ⚠️  未找到图片（已保留原引用）: {ref}", style="yellow")
        console.print(f"✅ 已生成: {embed.out_file}", style="green")

    # 自动上传到思源笔记
    if upload:
        _upload_to_siyuan(result.embed_results)
