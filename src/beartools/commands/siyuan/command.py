"""思源笔记命令模块

提供思源笔记相关的命令行操作。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path

from rich.console import Console
import typer

from beartools.config import get_config
from beartools.siyuan import SiyuanError, SiyuanHandler

console = Console()
app = typer.Typer(help="思源笔记管理")

_handler = SiyuanHandler()


def _option_or_config(option_value: str, config_value: str) -> str:
    """优先使用命令行参数，否则退回配置值。"""

    return option_value if option_value else config_value


def _print_siyuan_error(error: SiyuanError) -> None:
    """统一展示思源错误和连接提示。"""

    console.print(f"❌ {error}", style="red")
    if "连接" in str(error):
        console.print("请检查思源笔记是否已启动，且API服务已开启", style="yellow")


def _run_siyuan_task[T](task: Coroutine[object, object, T]) -> T:
    """同步执行思源异步任务，并统一转换命令退出。"""

    try:
        return asyncio.run(task)
    except SiyuanError as e:
        _print_siyuan_error(e)
        raise typer.Exit(1) from e


@app.command(name="ls-notebooks", help="列出所有笔记本")  # type: ignore
def ls_notebooks() -> None:
    """列出所有思源笔记本，每行一个"""
    notebooks = _run_siyuan_task(_handler.list_notebooks())

    for nb in notebooks:
        name = nb.get("name", "")
        id_ = nb.get("id", "")
        icon = nb.get("icon", "📓")
        closed = " 🔒" if nb.get("closed", False) else ""
        console.print(f"{icon} {name}{closed} [{id_}]", markup=False)


@app.command(name="export-md", help="导出指定笔记为 Markdown 文本")  # type: ignore
def export_md(
    noteid: str = typer.Option("", help="笔记 ID，不指定时使用配置文件中的 default_note"),
    output: str = typer.Option("", help="输出文件路径，不指定则打印到控制台"),
) -> None:
    """导出指定笔记为 Markdown 文本，可输出到文件或控制台"""
    config = get_config()
    target_note_id = _option_or_config(noteid, config.siyuan.default_note)

    md_content = _run_siyuan_task(_handler.export_md(target_note_id))

    if output:
        try:
            Path(output).write_text(md_content, encoding="utf-8")
            console.print(f"✅ 导出成功，已保存到: {output}", style="green")
        except OSError as e:
            console.print(f"❌ 写入文件失败: {str(e)}", style="red")
            raise typer.Exit(1) from e
    else:
        console.print(md_content)


@app.command(name="upload-md", help="将本地 Markdown 文件上传到思源笔记")  # type: ignore
def upload_md(
    md_path: str = typer.Argument(..., help="本地 .md 文件路径"),
    notebook: str = typer.Option("", help="目标笔记本 ID，不指定时使用配置文件中的 notebook"),
    path: str = typer.Option("", help="目标路径，不指定时使用配置文件中的 path"),
) -> None:
    """将本地 Markdown 文件上传到思源笔记，notebook 和 path 默认读取配置文件"""
    config = get_config()
    target_notebook = _option_or_config(notebook, config.siyuan.notebook)
    target_path = _option_or_config(path, config.siyuan.path)

    if not target_notebook:
        console.print("❌ 未指定笔记本 ID，请通过参数或配置文件 `siyuan.notebook` 设置", style="red")
        raise typer.Exit(1)
    if not target_path:
        console.print("❌ 未指定目标路径，请通过参数或配置文件 `siyuan.path` 设置", style="red")
        raise typer.Exit(1)

    doc_id = _run_siyuan_task(_handler.upload_md(md_path, target_notebook, target_path))

    console.print(f"✅ 上传成功，文档 ID: {doc_id}", style="green")
