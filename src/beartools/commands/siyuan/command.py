"""思源笔记命令模块

提供思源笔记相关的命令行操作。
"""

from __future__ import annotations

import asyncio

from rich.console import Console
import typer

from beartools.config import get_config
from beartools.siyuan import SiyuanError, SiyuanHandler

console = Console()
app = typer.Typer(help="思源笔记相关操作")

_handler = SiyuanHandler()


@app.command(name="ls-notebooks", help="列出所有思源笔记本")  # type: ignore
def ls_notebooks() -> None:
    """列出所有思源笔记本，每行一个"""
    try:
        notebooks = asyncio.run(_handler.list_notebooks())
    except SiyuanError as e:
        console.print(f"❌ {e}", style="red")
        if "连接" in str(e):
            console.print("请检查思源笔记是否已启动，且API服务已开启", style="yellow")
        raise typer.Exit(1) from e

    for nb in notebooks:
        name = nb.get("name", "")
        id_ = nb.get("id", "")
        icon = nb.get("icon", "📓")
        closed = " 🔒" if nb.get("closed", False) else ""
        console.print(f"{icon} {name}{closed} [{id_}]")


@app.command(name="export-md", help="导出指定笔记为Markdown文本")  # type: ignore
def export_md(
    noteid: str = typer.Option("", help="笔记ID，不指定则使用配置文件中的default_note"),
    output: str = typer.Option("", help="输出文件路径，不指定则打印到控制台"),
) -> None:
    """导出指定笔记为Markdown文本，可输出到文件或控制台"""
    config = get_config()
    target_note_id = noteid if noteid else config.siyuan.default_note

    try:
        md_content = asyncio.run(_handler.export_md(target_note_id))
    except SiyuanError as e:
        console.print(f"❌ {e}", style="red")
        if "连接" in str(e):
            console.print("请检查思源笔记是否已启动，且API服务已开启", style="yellow")
        raise typer.Exit(1) from e

    if output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(md_content)
            console.print(f"✅ 导出成功，已保存到: {output}", style="green")
        except Exception as e:
            console.print(f"❌ 写入文件失败: {str(e)}", style="red")
            raise typer.Exit(1) from None
    else:
        console.print(md_content)


@app.command(name="upload-md", help="将本地 Markdown 文件上传到思源笔记")  # type: ignore
def upload_md(
    md_path: str = typer.Argument(..., help="本地 .md 文件路径"),
    notebook: str = typer.Option("", help="目标笔记本ID，不指定则使用配置文件中的notebook"),
    path: str = typer.Option("", help="目标路径，不指定则使用配置文件中的path"),
) -> None:
    """将本地 Markdown 文件上传到思源笔记，notebook 和 path 默认读取配置文件"""
    config = get_config()
    target_notebook = notebook if notebook else config.siyuan.notebook
    target_path = path if path else config.siyuan.path

    if not target_notebook:
        console.print("❌ 未指定笔记本ID，请通过参数或配置文件siyuan.notebook设置", style="red")
        raise typer.Exit(1)
    if not target_path:
        console.print("❌ 未指定目标路径，请通过参数或配置文件siyuan.path设置", style="red")
        raise typer.Exit(1)

    try:
        doc_id = asyncio.run(_handler.upload_md(md_path, target_notebook, target_path))
    except SiyuanError as e:
        console.print(f"❌ {e}", style="red")
        if "连接" in str(e):
            console.print("请检查思源笔记是否已启动，且API服务已开启", style="yellow")
        raise typer.Exit(1) from e

    console.print(f"✅ 上传成功，文档ID: {doc_id}", style="green")
