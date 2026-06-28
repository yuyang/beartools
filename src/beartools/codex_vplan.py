"""Codex 火山 Ark 图片业务模块。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import time
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI, OpenAI
from openai.types.images_response import ImagesResponse
from rich.console import Console

from beartools.codex_pic import refine_codex_pic_prompt_async
from beartools.config import CodexConfig, get_config
from beartools.logger import get_logger

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_IMAGE_MODEL = "doubao-seedream-4-5-251128"
DEFAULT_VPLAN_SIZE = "2K"
DEFAULT_VPLAN_IMAGE_TIMEOUT_SECONDS = 600
DEFAULT_VPLAN_REFINE_TIMEOUT_SECONDS = 300
DEFAULT_VPLAN_OUTPUT_EXTENSION = ".png"
_ALLOWED_URL_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

logger = get_logger(__name__)
console = Console()


@dataclass(frozen=True)
class CodexVPlanResult:
    """Codex vplan 图片任务执行结果。"""

    output_dir: Path
    image_output_file: Path
    trace_output_file: Path


@dataclass(frozen=True)
class _UrlExtensionResult:
    """URL 后缀解析结果。"""

    extension: str
    fallback: bool


def _require_codex_refine_config(config: CodexConfig) -> None:
    """校验提示词润色所需配置。"""

    if not config.base_url.strip():
        raise RuntimeError("codex.base_url 必填且必须是非空字符串")
    if not config.api_key.strip():
        raise RuntimeError("codex.api_key 必填且必须是非空字符串")
    if not config.model.strip():
        raise RuntimeError("codex.model 必填且必须是非空字符串")


def _resolve_vplan_output_dir(md_path: Path) -> Path:
    """解析 vplan 输出目录。"""

    return Path("output") / "vplan" / md_path.stem


def _resolve_trace_output_file(output_dir: Path, md_path: Path) -> Path:
    """解析 trace 文件路径。"""

    return output_dir / f"{md_path.stem}.trace.log"


def _resolve_url_extension(url: str) -> _UrlExtensionResult:
    """根据 URL 路径后缀决定本地图片扩展名。"""

    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _ALLOWED_URL_IMAGE_EXTENSIONS:
        return _UrlExtensionResult(extension=suffix, fallback=False)
    return _UrlExtensionResult(extension=DEFAULT_VPLAN_OUTPUT_EXTENSION, fallback=True)


def _resolve_image_output_file(output_dir: Path, md_path: Path, extension: str) -> Path:
    """解析图片输出路径。"""

    return output_dir / f"{md_path.stem}{extension}"


def _require_vplan_key(config: CodexConfig) -> str:
    """读取并校验 codex.vplan.key。"""

    if not config.vplan.key.strip():
        raise RuntimeError("codex.vplan.key 必填且必须是非空字符串")
    return config.vplan.key


def _write_vplan_trace(trace_output_file: Path, payload: dict[str, object]) -> None:
    """写入 vplan trace。"""

    trace_output_file.parent.mkdir(parents=True, exist_ok=True)
    trace_output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_image_url(response: ImagesResponse) -> str:
    """从 Ark 图片响应中提取首张图片 URL。"""

    if not response.data:
        raise RuntimeError("图片生成响应缺少 data")
    image_url = response.data[0].url
    if not image_url or not image_url.strip():
        raise RuntimeError("图片生成响应缺少 url")
    return image_url


def _download_image_bytes(url: str, timeout_seconds: int) -> bytes:
    """下载 Ark 返回 URL 对应的图片字节。"""

    response = httpx.get(url, timeout=float(timeout_seconds), follow_redirects=True)
    response.raise_for_status()
    return response.content


async def run_codex_vplan_async(
    *,
    md_path: Path,
    size: str = DEFAULT_VPLAN_SIZE,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexVPlanResult:
    """执行 vplan 图片生成任务，并写入 output/vplan/<文件名> 目录。"""

    if not md_path.exists():
        raise FileNotFoundError(f"Markdown 文件不存在: {md_path}")
    if not md_path.is_file():
        raise ValueError(f"Markdown 路径不是文件: {md_path}")
    if md_path.suffix.lower() != ".md":
        raise ValueError(f"vplan 输入必须是 Markdown 文件: {md_path}")

    prompt = md_path.read_text(encoding="utf-8")
    output_dir = _resolve_vplan_output_dir(md_path)
    trace_output_file = _resolve_trace_output_file(output_dir, md_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = get_config().codex
    _require_codex_refine_config(config)
    vplan_api_key = _require_vplan_key(config)

    refine_timeout_seconds = max(config.timeout_seconds, DEFAULT_VPLAN_REFINE_TIMEOUT_SECONDS)
    image_timeout_seconds = max(config.timeout_seconds, DEFAULT_VPLAN_IMAGE_TIMEOUT_SECONDS)
    total_started_at = time.monotonic()
    trace_payload: dict[str, object] = {
        "status": "started",
        "provider": "volcengine_ark",
        "original_prompt": prompt,
        "refine_model": config.model,
        "ark_base_url": ARK_BASE_URL,
        "ark_model": ARK_IMAGE_MODEL,
        "size": size,
        "quality": quality,
        "ignored_output_format": output_format,
        "response_format": "url",
        "watermark": False,
        "refine_timeout_seconds": refine_timeout_seconds,
        "image_timeout_seconds": image_timeout_seconds,
    }
    _write_vplan_trace(trace_output_file, trace_payload)

    async with AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=float(refine_timeout_seconds),
    ) as refine_client:
        console.print(f"[vplan] 开始优化做图提示词：{md_path.name}（超时 {refine_timeout_seconds}s）...", style="cyan")
        logger.info(
            "vplan 开始优化做图提示词: md_path=%s model=%s timeout=%ss", md_path, config.model, refine_timeout_seconds
        )
        refine_started_at = time.monotonic()
        try:
            refined_prompt = await refine_codex_pic_prompt_async(prompt, config, refine_client)
        except Exception as exc:
            trace_payload["status"] = "refine_failed"
            trace_payload["refine_elapsed_seconds"] = round(time.monotonic() - refine_started_at, 3)
            trace_payload["error"] = str(exc)
            _write_vplan_trace(trace_output_file, trace_payload)
            logger.exception("vplan 优化做图提示词失败: md_path=%s", md_path)
            raise

    trace_payload["status"] = "refined"
    trace_payload["refined_prompt"] = refined_prompt
    trace_payload["refine_elapsed_seconds"] = round(time.monotonic() - refine_started_at, 3)
    _write_vplan_trace(trace_output_file, trace_payload)
    console.print(
        f"[vplan] 提示词优化完成：{md_path.name}，开始生成图片（超时 {image_timeout_seconds}s）...", style="cyan"
    )
    logger.info(
        "vplan 开始生成图片: md_path=%s ark_model=%s size=%s timeout=%ss",
        md_path,
        ARK_IMAGE_MODEL,
        size,
        image_timeout_seconds,
    )

    image_started_at = time.monotonic()
    try:
        ark_client = OpenAI(api_key=vplan_api_key, base_url=ARK_BASE_URL)
        response: ImagesResponse = ark_client.images.generate(
            model=ARK_IMAGE_MODEL,
            prompt=refined_prompt,
            size=size,
            response_format="url",
            extra_body={"watermark": False},
        )
        image_url = _extract_image_url(response)
        url_extension = _resolve_url_extension(image_url)
        image_output_file = _resolve_image_output_file(output_dir, md_path, url_extension.extension)
        logger.info("vplan 获取图片 URL: md_path=%s image_url=%s output_file=%s", md_path, image_url, image_output_file)
        image_bytes = _download_image_bytes(image_url, image_timeout_seconds)
        console.print(f"[vplan] 图片生成完成，开始写入结果文件：{image_output_file}...", style="cyan")
        image_output_file.write_bytes(image_bytes)
    except Exception as exc:
        trace_payload["status"] = "image_generate_failed"
        trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
        trace_payload["error"] = str(exc)
        _write_vplan_trace(trace_output_file, trace_payload)
        logger.exception("vplan 生成图片失败: md_path=%s", md_path)
        raise

    trace_payload["status"] = "completed"
    trace_payload["image_url"] = image_url
    trace_payload["url_extension"] = url_extension.extension
    trace_payload["url_extension_fallback"] = url_extension.fallback
    trace_payload["image_output_file"] = str(image_output_file)
    trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
    trace_payload["total_elapsed_seconds"] = round(time.monotonic() - total_started_at, 3)
    _write_vplan_trace(trace_output_file, trace_payload)
    logger.info("vplan 图片生成完成: image_output=%s trace_output=%s", image_output_file, trace_output_file)

    return CodexVPlanResult(
        output_dir=output_dir,
        image_output_file=image_output_file,
        trace_output_file=trace_output_file,
    )


def run_codex_vplan(
    *,
    md_path: Path,
    size: str = DEFAULT_VPLAN_SIZE,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexVPlanResult:
    """同步执行 vplan 图片生成任务。"""

    return asyncio.run(run_codex_vplan_async(md_path=md_path, size=size, quality=quality, output_format=output_format))
