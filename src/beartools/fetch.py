"""URL 抓取模块

提供基于域名分发的 URL 内容下载核心功能。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from urllib.parse import urlparse

import aiofiles.os

from beartools.markdown import EmbedResult, embed_images

# data/ 系列目录基于项目根目录（此文件向上两级）
_DATA_ROOT = Path(__file__).parents[2] / "data"
_DATA_DOWNLOAD = _DATA_ROOT / "download"
_DATA_FORMAT = _DATA_ROOT / "format"


@dataclass
class FetchResult:
    """URL 抓取结果"""

    original_url: str
    """原始 URL"""
    target_dir: Path
    """原始下载目录"""
    markdown_dir: Path
    """最终 Markdown 输出目录"""
    output: str
    """命令输出文本"""
    embed_results: list[EmbedResult]
    """每个 .md 文件的图片内嵌结果列表"""


def url_to_id(url: str) -> str:
    """根据 URL 生成唯一 ID（取 SHA256 前16位）"""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


class BaseFetchHandler(ABC):
    """URL 抓取处理器抽象基类

    定义了所有域名特定处理器必须实现的接口和公共方法。
    """

    url: str
    """原始 URL"""
    url_id: str
    """URL 生成的唯一 ID"""
    download_dir: Path
    """原始内容下载目录"""
    format_dir: Path
    """处理后内容输出目录"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.url_id = url_to_id(url)
        self.download_dir = _DATA_DOWNLOAD / self.url_id
        self.format_dir = _DATA_FORMAT / self.url_id

    @abstractmethod
    async def fetch(self) -> FetchResult:
        """执行抓取操作

        Returns:
            FetchResult 抓取结果
        """
        pass

    async def prepare_directories(self) -> None:
        """准备下载和输出目录，确保目录存在"""
        await aiofiles.os.makedirs(self.download_dir, exist_ok=True)
        await aiofiles.os.makedirs(self.format_dir, exist_ok=True)


class WeixinFetchHandler(BaseFetchHandler):
    """微信公众号文章抓取处理器

    处理 weixin.qq.com 域名的文章，使用 opencli 下载并执行图片内嵌。
    """

    async def fetch(self) -> FetchResult:
        """执行微信文章抓取

        Returns:
            FetchResult 抓取结果

        Raises:
            FileNotFoundError: opencli 命令未安装
            TimeoutError: 命令执行超时
            RuntimeError: 下载失败
        """
        # 准备目录
        await self.prepare_directories()

        try:
            proc = await asyncio.create_subprocess_exec(
                "opencli",
                "weixin",
                "download",
                "--url",
                self.url,
                cwd=str(self.download_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(  # type: ignore[misc]
                    proc.communicate(), timeout=300
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                raise TimeoutError("命令执行超时（超过5分钟）") from None
        except FileNotFoundError:
            raise FileNotFoundError("未找到 opencli 命令，请确认已安装") from None

        output = stdout.decode() + stderr.decode()

        if "success" not in output.lower():
            raise RuntimeError(output)

        # 下载成功后执行图片内嵌
        embed_results = await embed_images(str(self.download_dir), str(self.format_dir))

        return FetchResult(
            original_url=self.url,
            target_dir=self.download_dir,
            markdown_dir=self.format_dir,
            output=output,
            embed_results=embed_results,
        )


class XDotComFetchHandler(BaseFetchHandler):
    """X/Twitter 文章抓取处理器

    处理 x.com 和 twitter.com 域名的推文，使用 opencli 下载为 Markdown 格式。
    """

    async def fetch(self) -> FetchResult:
        """执行X/Twitter推文抓取

        Returns:
            FetchResult 抓取结果

        Raises:
            FileNotFoundError: opencli 命令未安装
            TimeoutError: 命令执行超时
        """
        # 准备目录
        await self.prepare_directories()

        try:
            proc = await asyncio.create_subprocess_exec(
                "opencli",
                "twitter",
                "article",
                "-f",
                "md",
                self.url,
                cwd=str(self.download_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(  # type: ignore[misc]
                    proc.communicate(), timeout=300
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                raise TimeoutError("命令执行超时（超过5分钟）") from None
        except FileNotFoundError:
            raise FileNotFoundError("未找到 opencli 命令，请确认已安装") from None

        stdout_str = stdout.decode()
        stderr_str = stderr.decode()
        output = stdout_str + stderr_str

        if proc.returncode == 0 and stdout_str.strip():
            # 成功场景：用内容前10个字符sanitize作为文件名
            sanitized_name = re.sub(r'[<>:"/\\|?*]', "_", stdout_str[:10])
            file_path = self.format_dir / f"{sanitized_name}.md"
            content = f"{self.url}\n\n{stdout_str}"
            fetch_failed = False
        else:
            # 失败场景：用url_id作为文件名，保存错误信息
            error_msg = stderr_str.strip() if stderr_str.strip() else "未知错误"
            file_path = self.format_dir / f"{self.url_id}.md"
            content = f"{self.url}\n\n下载失败：{error_msg}"
            fetch_failed = True

        # 异步写入文件
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(content)

        if fetch_failed:
            raise RuntimeError(output if output.strip() else content)

        return FetchResult(
            original_url=self.url,
            target_dir=self.download_dir,
            markdown_dir=self.format_dir,
            output=output,
            embed_results=[],
        )


def fetch_handler_factory(url: str) -> BaseFetchHandler:
    """根据URL域名返回对应的抓取处理器实例

    Args:
        url: 要抓取的URL

    Returns:
        BaseFetchHandler 对应域名的处理器实例

    Raises:
        ValueError: 域名暂不支持
    """
    raw = url if "://" in url else f"https://{url}"
    parsed = urlparse(raw)
    hostname = parsed.netloc.lower().split(":")[0]

    if hostname.endswith("weixin.qq.com"):
        return WeixinFetchHandler(url)
    elif hostname in ("x.com", "twitter.com") or hostname.endswith((".x.com", ".twitter.com")):
        return XDotComFetchHandler(url)
    else:
        raise ValueError(f"暂不支持域名: {hostname}")


async def fetch_url(url: str) -> FetchResult:
    """根据 URL 抓取内容，目前支持 weixin.qq.com、x.com 和 twitter.com 域名

    下载成功后自动对下载目录中的 .md 文件执行图片内嵌，结果输出至
    data/format/<url_id>/ 目录。

    Args:
        url: 要抓取的 URL

    Returns:
        FetchResult 包含下载目录、Markdown 输出目录、命令输出和图片内嵌结果

    Raises:
        ValueError: 域名暂不支持
        FileNotFoundError: opencli 命令未安装
        TimeoutError: 命令执行超时
        RuntimeError: 下载失败（output 作为异常消息）
    """
    handler = fetch_handler_factory(url)
    return await handler.fetch()
