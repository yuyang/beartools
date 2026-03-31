"""思源笔记模块

封装与思源笔记 API 交互的核心逻辑。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TypedDict, cast
import zipfile

import aiofiles
import aiofiles.os
import aiohttp

from beartools.config import get_config

# 思源笔记 API 基础地址
_BASE_URL = "http://127.0.0.1:6806"


class NotebookInfo(TypedDict):
    """思源笔记本信息"""

    id: str
    name: str
    icon: str
    closed: bool
    sort: int


class _NotebooksData(TypedDict):
    notebooks: list[NotebookInfo]


class _NotebooksApiResponse(TypedDict):
    code: int
    msg: str
    data: _NotebooksData


class _ExportData(TypedDict):
    zip: str


class _ExportApiResponse(TypedDict):
    code: int
    msg: str
    data: _ExportData


class _CreateDocApiResponse(TypedDict):
    code: int
    msg: str
    data: str


def _get_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


class SiyuanError(Exception):
    """思源笔记操作异常"""

    pass


class SiyuanHandler:
    """思源笔记业务处理器"""

    def _get_token(self) -> str:
        config = get_config()
        token = config.siyuan.token
        if not token:
            raise SiyuanError("请先在config/beartools.yaml中配置siyuan.token")
        return token

    async def list_notebooks(self) -> list[NotebookInfo]:
        """获取所有思源笔记本列表"""
        token = self._get_token()
        headers = _get_headers(token)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_BASE_URL}/api/notebook/lsNotebooks",
                    headers=headers,
                    json={},  # type: ignore[misc]
                ) as response:
                    if response.status != 200:
                        raise SiyuanError(f"API请求失败，状态码: {response.status}")

                    result: _NotebooksApiResponse = cast(_NotebooksApiResponse, await response.json())  # type: ignore[misc]
                    if result["code"] != 0:
                        raise SiyuanError(f"操作失败: {result.get('msg', '未知错误')}")

                    return result["data"]["notebooks"]

        except aiohttp.ClientError as e:
            raise SiyuanError(f"连接思源笔记失败: {e}") from e

    async def export_md(self, note_id: str) -> str:
        """导出指定笔记为 Markdown 文本

        Args:
            note_id: 笔记 ID

        Returns:
            str: Markdown 文本内容
        """
        if not note_id:
            raise SiyuanError("请指定noteid参数或在配置文件中设置siyuan.default_note")

        token = self._get_token()
        headers = _get_headers(token)
        payload = {"id": note_id, "mode": 0}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_BASE_URL}/api/export/exportMd",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status != 200:
                        raise SiyuanError(f"API请求失败，状态码: {response.status}")

                    result: _ExportApiResponse = cast(_ExportApiResponse, await response.json())  # type: ignore[misc]
                    if result["code"] != 0:
                        raise SiyuanError(f"导出失败: {result.get('msg', '未知错误')}")

                    zip_path = result["data"]["zip"]
                    if not zip_path:
                        raise SiyuanError("导出失败: 未获取到导出文件路径")

                    zip_url = f"{_BASE_URL}{zip_path}"
                    async with session.get(zip_url) as zip_response:
                        if zip_response.status != 200:
                            raise SiyuanError(f"下载导出文件失败，状态码: {zip_response.status}")

                        zip_content = await zip_response.read()

                        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
                            md_files = [f for f in zf.namelist() if f.endswith(".md")]
                            if not md_files:
                                raise SiyuanError("导出文件中没有找到Markdown内容")

                            with zf.open(md_files[0], "r") as f:
                                return f.read().decode("utf-8")

        except aiohttp.ClientError as e:
            raise SiyuanError(f"连接思源笔记失败: {e}") from e

    async def upload_md(self, md_path: str, notebook: str, path: str) -> str:
        """将本地 Markdown 文件上传到思源笔记

        Args:
            md_path:  本地 .md 文件路径
            notebook: 目标笔记本 ID
            path:     目标路径（含文档名，如 /web资料/标题）

        Returns:
            str: 新建文档的 ID
        """
        token = self._get_token()

        md_file = Path(md_path)
        if not await aiofiles.os.path.exists(md_file):
            raise SiyuanError(f"文件不存在: {md_path}")

        title = md_file.stem
        doc_path = f"{path.rstrip('/')}/{title}"

        async with aiofiles.open(md_file, encoding="utf-8") as f:
            md_content = await f.read()

        headers = _get_headers(token)
        payload = {
            "notebook": notebook,
            "path": doc_path,
            "markdown": md_content,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_BASE_URL}/api/filetree/createDocWithMd",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status != 200:
                        raise SiyuanError(f"API请求失败，状态码: {response.status}")

                    result: _CreateDocApiResponse = cast(_CreateDocApiResponse, await response.json())  # type: ignore[misc]
                    if result["code"] != 0:
                        raise SiyuanError(f"上传失败: {result.get('msg', '未知错误')}")

                    return result["data"]

        except aiohttp.ClientError as e:
            raise SiyuanError(f"连接思源笔记失败: {e}") from e
