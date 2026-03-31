"""思源笔记命令模块

提供思源笔记相关的命令行操作。
"""

from __future__ import annotations

import asyncio
import io
from typing import TypedDict, cast
import zipfile

import aiohttp
from rich.console import Console
import typer

from beartools.config import get_config

console = Console()
app = typer.Typer(help="思源笔记相关操作")


class _NotebookInfo(TypedDict):
    """思源笔记本信息"""

    id: str
    name: str
    icon: str
    closed: bool
    sort: int


class _NotebooksData(TypedDict):
    """lsNotebooks data 字段"""

    notebooks: list[_NotebookInfo]


class _NotebooksApiResponse(TypedDict):
    """lsNotebooks API 响应"""

    code: int
    msg: str
    data: _NotebooksData


class _ExportData(TypedDict):
    """exportMd data 字段"""

    zip: str


class _ExportApiResponse(TypedDict):
    """exportMd API 响应"""

    code: int
    msg: str
    data: _ExportData


async def _list_notebooks_async() -> list[_NotebookInfo]:
    """异步获取所有思源笔记本列表

    Returns:
        list[dict]: 笔记本列表
    """
    config = get_config()
    token = config.siyuan.token

    if not token:
        console.print("❌ 请先在config/beartools.yaml中配置siyuan.token", style="red")
        raise typer.Exit(1)

    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://127.0.0.1:6806/api/notebook/lsNotebooks",
                headers=headers,
                json={},  # type: ignore[misc]
            ) as response:
                if response.status != 200:
                    console.print(f"❌ API请求失败，状态码: {response.status}", style="red")
                    raise typer.Exit(1)

                result: _NotebooksApiResponse = cast(_NotebooksApiResponse, await response.json())  # type: ignore[misc]
                if result["code"] != 0:
                    console.print(f"❌ 操作失败: {result.get('msg', '未知错误')}", style="red")
                    raise typer.Exit(1)

                return result["data"]["notebooks"]

    except aiohttp.ClientError as e:
        console.print(f"❌ 连接思源笔记失败: {str(e)}", style="red")
        console.print("请检查思源笔记是否已启动，且API服务已开启", style="yellow")
        raise typer.Exit(1) from None


@app.command(name="ls-notebooks", help="列出所有思源笔记本")  # type: ignore
def ls_notebooks() -> None:
    """列出所有思源笔记本，每行一个"""
    notebooks = asyncio.run(_list_notebooks_async())

    for nb in notebooks:
        name = nb.get("name", "")
        id_ = nb.get("id", "")
        icon = nb.get("icon", "📓")
        closed = " 🔒" if nb.get("closed", False) else ""
        console.print(f"{icon} {name}{closed} [{id_}]")


async def _export_md_async(note_id: str) -> str:
    """异步导出指定笔记为Markdown文本

    Args:
        note_id: 笔记ID

    Returns:
        str: Markdown文本内容
    """
    config = get_config()
    token = config.siyuan.token

    if not token:
        console.print("❌ 请先在config/beartools.yaml中配置siyuan.token", style="red")
        raise typer.Exit(1)

    if not note_id:
        console.print("❌ 请指定noteid参数或在配置文件中设置siyuan.default_note", style="red")
        raise typer.Exit(1)

    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}

    payload = {"id": note_id, "mode": 0}

    try:
        async with aiohttp.ClientSession() as session:
            # 第一步：调用exportMd获取导出包地址
            async with session.post(
                "http://127.0.0.1:6806/api/export/exportMd", headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    console.print(f"❌ API请求失败，状态码: {response.status}", style="red")
                    raise typer.Exit(1)

                result: _ExportApiResponse = cast(_ExportApiResponse, await response.json())  # type: ignore[misc]
                if result["code"] != 0:
                    console.print(f"❌ 导出失败: {result.get('msg', '未知错误')}", style="red")
                    raise typer.Exit(1)

                zip_path = result["data"]["zip"]
                if not zip_path:
                    console.print("❌ 导出失败: 未获取到导出文件路径", style="red")
                    raise typer.Exit(1)

                # 第二步：下载zip文件
                zip_url = f"http://127.0.0.1:6806{zip_path}"
                async with session.get(zip_url) as zip_response:
                    if zip_response.status != 200:
                        console.print(f"❌ 下载导出文件失败，状态码: {zip_response.status}", style="red")
                        raise typer.Exit(1)

                    zip_content = await zip_response.read()

                    # 第三步：解压zip文件，读取markdown内容
                    with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
                        # 找到所有.md文件
                        md_files = [f for f in zf.namelist() if f.endswith(".md")]
                        if not md_files:
                            console.print("❌ 导出文件中没有找到Markdown内容", style="red")
                            raise typer.Exit(1)

                        # 读取第一个md文件内容
                        with zf.open(md_files[0], "r") as f:
                            return f.read().decode("utf-8")

    except aiohttp.ClientError as e:
        console.print(f"❌ 连接思源笔记失败: {str(e)}", style="red")
        console.print("请检查思源笔记是否已启动，且API服务已开启", style="yellow")
        raise typer.Exit(1) from None


@app.command(name="export-md", help="导出指定笔记为Markdown文本")  # type: ignore
def export_md(
    noteid: str = typer.Option("", help="笔记ID，不指定则使用配置文件中的default_note"),
    output: str = typer.Option("", help="输出文件路径，不指定则打印到控制台"),
) -> None:
    """导出指定笔记为Markdown文本，可输出到文件或控制台"""
    config = get_config()
    # 优先使用命令行参数的noteid，没有则使用配置的default_note
    target_note_id = noteid if noteid else config.siyuan.default_note

    md_content = asyncio.run(_export_md_async(target_note_id))

    if output:
        # 输出到文件
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(md_content)
            console.print(f"✅ 导出成功，已保存到: {output}", style="green")
        except Exception as e:
            console.print(f"❌ 写入文件失败: {str(e)}", style="red")
            raise typer.Exit(1) from None
    else:
        # 打印到控制台
        console.print(md_content)
