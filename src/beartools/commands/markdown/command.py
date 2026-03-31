"""Markdown 工具命令模块

提供 Markdown 文件处理相关的命令行操作。
"""

from __future__ import annotations

import asyncio

from rich.console import Console
import typer

from beartools.markdown import embed_images

console = Console()
app = typer.Typer(help="Markdown 文件处理相关操作")


@app.command(name="embed-images", help="将 Markdown 中的本地图片替换为 base64 内嵌")  # type: ignore
def embed_images_cmd(
    input_path: str = typer.Argument(..., help="输入目录或 .md 文件路径"),
    output_path: str = typer.Argument(..., help="输出目录路径"),
) -> None:
    """将 Markdown 文件中的本地图片引用转换为 base64 内嵌格式"""
    try:
        results = asyncio.run(embed_images(input_path, output_path))
    except ValueError as e:
        console.print(f"❌ {e}", style="red")
        raise typer.Exit(1) from e

    for result in results:
        for ref in result.missing:
            console.print(f"  ⚠️  未找到图片（已保留原引用）: {ref}", style="yellow")
        console.print(f"✅ 已生成: {result.out_file}", style="green")
