"""URL 抓取模块

提供基于域名分发的 URL 内容下载核心功能。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
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

    target_dir: Path
    """原始下载目录"""
    output: str
    """命令输出文本"""
    embed_results: list[EmbedResult]
    """每个 .md 文件的图片内嵌结果列表"""


def url_to_id(url: str) -> str:
    """根据 URL 生成唯一 ID（取 SHA256 前16位）"""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


async def fetch_url(url: str) -> FetchResult:
    """根据 URL 抓取内容，目前支持 weixin.qq.com 域名

    下载成功后自动对下载目录中的 .md 文件执行图片内嵌，结果输出至
    data/format/<url_id>/ 目录。

    Args:
        url: 要抓取的 URL

    Returns:
        FetchResult 包含下载目录、命令输出和图片内嵌结果

    Raises:
        ValueError: 域名暂不支持
        FileNotFoundError: opencli 命令未安装
        TimeoutError: 命令执行超时
        RuntimeError: 下载失败（output 作为异常消息）
    """
    raw = url if "://" in url else f"https://{url}"
    parsed = urlparse(raw)
    hostname = parsed.netloc.lower().split(":")[0]

    if not hostname.endswith("weixin.qq.com"):
        raise ValueError(f"暂不支持域名: {hostname}")

    uid = url_to_id(url)
    target_dir = _DATA_DOWNLOAD / uid
    await aiofiles.os.makedirs(target_dir, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            "opencli",
            "weixin",
            "download",
            "--url",
            url,
            cwd=str(target_dir),
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

    # 下载成功后，将目录中的 .md 文件图片内嵌，输出到 data/format/<uid>/
    format_dir = _DATA_FORMAT / uid
    embed_results = await embed_images(str(target_dir), str(format_dir))

    return FetchResult(target_dir=target_dir, output=output, embed_results=embed_results)
