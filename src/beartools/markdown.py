"""Markdown 处理模块

提供 Markdown 文件的图片内嵌等核心处理功能。
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import mimetypes
from pathlib import Path
import re

import aiofiles
import aiofiles.os

# 匹配 Markdown 图片语法：![alt](path)
_IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


@dataclass
class EmbedResult:
    """单个文件的图片内嵌处理结果"""

    out_file: Path
    """写入的输出文件路径"""
    missing: list[str] = field(default_factory=list)
    """未找到的图片引用列表"""


async def _to_base64_data_uri(img_path: Path) -> str:
    """异步将本地图片文件转换为 base64 内嵌 data URI

    Args:
        img_path: 图片文件的绝对路径

    Returns:
        data URI 字符串，格式为 data:<mime>;base64,<data>
    """
    async with aiofiles.open(img_path, "rb") as f:
        raw = await f.read()

    mime_type, _ = mimetypes.guess_type(str(img_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


async def _process_md_file(md_file: Path, file_base_dir: Path, dst_dir: Path) -> EmbedResult:
    """异步处理单个 .md 文件，将图片引用替换为 base64 内嵌

    先扫描全部本地图片引用，并发 async 读取转换，再统一做文本替换。

    Args:
        md_file:       源 .md 文件路径
        file_base_dir: 解析相对图片路径的基准目录
        dst_dir:       输出目录

    Returns:
        EmbedResult 包含输出路径和缺失图片列表
    """
    async with aiofiles.open(md_file, encoding="utf-8") as f:
        content = await f.read()

    # 第一遍：收集所有需要转换的本地图片路径（去重）
    missing: list[str] = []
    local_imgs: dict[str, Path] = {}  # img_ref -> 绝对路径
    for m in _IMG_PATTERN.finditer(content):
        img_ref: str = m.group(2)
        if img_ref.startswith(("data:", "http://", "https://")):
            continue
        img_abs = (file_base_dir / img_ref).resolve()
        if not await aiofiles.os.path.exists(img_abs):
            if img_ref not in missing:
                missing.append(img_ref)
        else:
            local_imgs[img_ref] = img_abs

    # 第二遍：并发读取所有图片，构建 img_ref -> data_uri 缓存
    data_uri_cache: dict[str, str] = {}
    if local_imgs:
        uris = await asyncio.gather(*[_to_base64_data_uri(p) for p in local_imgs.values()])
        data_uri_cache = dict(zip(local_imgs.keys(), uris, strict=True))

    # 第三遍：同步替换
    def _replace(m: re.Match[str]) -> str:
        alt, img_ref = m.group(1), m.group(2)
        if img_ref not in data_uri_cache:
            return m.group(0)
        return f"![{alt}]({data_uri_cache[img_ref]})"

    new_content = _IMG_PATTERN.sub(_replace, content)

    out_file = dst_dir / md_file.name
    async with aiofiles.open(out_file, "w", encoding="utf-8") as f:
        await f.write(new_content)

    return EmbedResult(out_file=out_file, missing=missing)


async def embed_images(input_path: str, output_path: str) -> list[EmbedResult]:
    """读取目录中的 .md 文件，将图片引用替换为 base64 内嵌，输出到指定目录

    多个文件并发处理。

    - 图片路径相对于 .md 文件所在目录解析
    - 找不到的图片保留原始引用，记录在返回结果的 missing 字段中
    - 输出文件名与源文件相同

    Args:
        input_path:  包含 .md 文件的输入目录（或直接是 .md 文件路径）
        output_path: 处理结果写入的输出目录

    Returns:
        每个处理文件对应一个 EmbedResult，包含输出路径和缺失图片列表

    Raises:
        ValueError: 输入路径不存在、不是目录/md文件，或目录中没有 .md 文件
    """
    src = Path(input_path)
    dst_dir = Path(output_path)

    if await aiofiles.os.path.isfile(src) and src.suffix == ".md":
        md_files = [src]
        base_dir = src.parent
    elif await aiofiles.os.path.isdir(src):
        md_files = await asyncio.to_thread(lambda: list(src.glob("*.md")))
        base_dir = src
    else:
        raise ValueError(f"输入路径不存在或不是目录/md文件: {src}")

    if not md_files:
        # 列出目录下的所有文件帮助排查
        error_msg = f"在 {src} 中未找到任何 .md 文件"
        if await aiofiles.os.path.isdir(src):
            files = await asyncio.to_thread(lambda: list(src.iterdir()))
            if files:
                file_list = "\n  - ".join([f.name for f in files])
                error_msg += f"\n目录下现有文件:\n  - {file_list}"
            else:
                error_msg += "\n目录为空"
        # 增加可能的错误原因
        error_msg += "\n可能原因：\n  1. 下载工具未正确生成 Markdown 文件\n  2. 目标页面内容格式不支持转换为 Markdown\n  3. 下载过程中出现了未捕获的错误"
        raise ValueError(error_msg)

    await aiofiles.os.makedirs(dst_dir, exist_ok=True)

    tasks = [_process_md_file(md_file, base_dir, dst_dir) for md_file in md_files]
    return await asyncio.gather(*tasks)


# 匹配Markdown中所有URL形式的正则列表
_URL_PATTERNS = [
    # 普通链接和图片链接：[text](url) / ![alt](url)
    re.compile(r"\[.*?\]\(([^)]+)\)"),
    # 参考式链接：[ref]: url
    re.compile(r"^\s*\[.*?\]:\s*(.+)$", re.MULTILINE),
    # 尖括号链接：<url>
    re.compile(r"<([^>]+)>"),
    # 裸链：独立存在的URL，支持http/https/ftp/mailto协议
    re.compile(r"((https?|ftp):\/\/[^\s,;!)\]'\"<>]+|mailto:[^\s,;!)\]'\"<>]+)"),
]


def extract_urls_from_markdown(text: str) -> list[str]:
    """从 Markdown 文本中提取所有 URL，返回去重后的列表。

    支持提取的URL形式：
    1. 普通链接：[链接文本](https://example.com)
    2. 图片链接：![替代文本](https://example.com/img.png)
    3. 参考式链接：[ref]: https://example.com
    4. 尖括号链接：<https://example.com>
    5. 裸链：https://example.com（文本中独立存在的URL）

    处理规则：
    - 自动移除URL首尾空白字符
    - 自动移除URL末尾的标点符号（. , ! ? ; : ) ] > " '）
    - 对结果去重，保持首次出现的顺序
    - 仅提取包含合法协议前缀的URL（http:// / https:// / ftp:// / mailto:）

    Args:
        text: 输入的 Markdown 文本

    Returns:
        提取到的 URL 列表，去重后按首次出现顺序排列
    """
    urls: set[str] = set()
    url_list: list[str] = []

    def _clean_url(url: str) -> str | None:
        """清理URL，移除首尾空白和末尾标点，验证协议前缀"""
        url = url.strip()
        # 移除末尾标点
        while url and url[-1] in {".", ",", "!", "?", ";", ":", ")", "]", ">", '"', "'"}:
            url = url[:-1]
        # 验证协议前缀
        if url.startswith(("http://", "https://", "ftp://", "mailto:")):
            return url
        return None

    # 遍历所有正则模式匹配URL
    for pattern in _URL_PATTERNS:
        for match in pattern.finditer(text):
            url = _clean_url(match.group(1))
            if url and url not in urls:
                urls.add(url)
                url_list.append(url)

    return url_list
