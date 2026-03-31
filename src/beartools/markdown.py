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
        raise ValueError(f"在 {src} 中未找到任何 .md 文件")

    await aiofiles.os.makedirs(dst_dir, exist_ok=True)

    tasks = [_process_md_file(md_file, base_dir, dst_dir) for md_file in md_files]
    return await asyncio.gather(*tasks)
