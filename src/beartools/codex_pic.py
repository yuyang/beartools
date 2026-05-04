"""Codex 图片业务模块。"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING, Literal, cast

from agents import Agent, OpenAIResponsesModel, Runner, set_tracing_disabled
from openai import AsyncOpenAI
from rich.console import Console

from beartools.config import CodexConfig, get_config
from beartools.logger import get_logger
from beartools.prompt import get_prompt_manager

if TYPE_CHECKING:
    from openai.types.images_response import ImagesResponse

console = Console()
logger = get_logger(__name__)
DEFAULT_PIC_REFINE_TIMEOUT_SECONDS = 300
DEFAULT_PIC_IMAGE_TIMEOUT_SECONDS = 600
_PICEDIT_VERSION_SUFFIX_RE = re.compile(r"^(?P<base>.+?)_version_(?P<version>\d+)$")


@dataclass
class CodexPicResult:
    """Codex 图片任务执行结果。"""

    output_dir: Path
    image_output_file: Path
    trace_output_file: Path


@dataclass
class CodexPicBatchItemResult:
    """批量做图单项结果。"""

    md_path: Path
    succeeded: bool
    image_output_file: Path | None
    trace_output_file: Path | None
    error_message: str | None


@dataclass
class CodexPicBatchResult:
    """批量做图结果。"""

    results: list[CodexPicBatchItemResult]


@dataclass(frozen=True)
class _TokenUsage:
    """统一记录模型调用 token 消耗。"""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


def _require_codex_config(config: CodexConfig) -> None:
    if not config.base_url.strip():
        raise RuntimeError("codex.base_url 必填且必须是非空字符串")
    if not config.api_key.strip():
        raise RuntimeError("codex.api_key 必填且必须是非空字符串")
    if not config.model.strip():
        raise RuntimeError("codex.model 必填且必须是非空字符串")


def _require_codex_pic_config(config: CodexConfig) -> None:
    """校验图片任务所需配置。"""

    _require_codex_config(config)
    if not config.pic_model.strip():
        raise RuntimeError("codex.pic_model 必填且必须是非空字符串")


def _resolve_pic_output_paths(md_path: Path, output_format: str) -> tuple[Path, Path, Path]:
    """解析 pic 子命令的固定输出路径。"""

    output_dir = Path("output") / "pic" / md_path.stem
    final_output_file = output_dir / f"{md_path.stem}.{output_format}"
    trace_output_file = output_dir / f"{md_path.stem}.trace.log"
    return output_dir, final_output_file, trace_output_file


def _resolve_picedit_output_paths(image_path: Path, output_format: str) -> tuple[Path, Path, Path]:
    """解析 picedit 子命令的固定输出路径。"""

    output_dir = image_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    stem_match = _PICEDIT_VERSION_SUFFIX_RE.match(image_path.stem)
    base_stem = stem_match.group("base") if stem_match is not None else image_path.stem
    version = 1
    while True:
        file_stem = f"{base_stem}_version_{version:03d}"
        final_output_file = output_dir / f"{file_stem}.{output_format}"
        trace_output_file = output_dir / f"{file_stem}.trace.log"
        if not final_output_file.exists() and not trace_output_file.exists():
            return output_dir, final_output_file, trace_output_file
        version += 1


def _extract_image_b64_json(response: object) -> str:
    """从图片生成响应中提取首张图片的 base64 内容。"""

    data = _safe_getattr(response, "data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("图片生成响应缺少 data")

    first_item = data[0]
    b64_json = _safe_getattr(first_item, "b64_json")
    if not isinstance(b64_json, str) or not b64_json.strip():
        raise RuntimeError("图片生成响应缺少 b64_json")
    return b64_json


def _normalize_pic_size(
    size: str,
) -> Literal["auto", "1024x1024", "1536x1024", "1024x1536", "256x256", "512x512", "1792x1024", "1024x1792"]:
    """校验并收窄图片尺寸，满足 SDK 的字面量类型要求。"""

    allowed_sizes = {
        "auto",
        "1024x1024",
        "1536x1024",
        "1024x1536",
        "256x256",
        "512x512",
        "1792x1024",
        "1024x1792",
    }
    if size not in allowed_sizes:
        raise ValueError(f"不支持的图片尺寸: {size}")
    return cast(
        Literal["auto", "1024x1024", "1536x1024", "1024x1536", "256x256", "512x512", "1792x1024", "1024x1792"],
        size,
    )


def _normalize_pic_quality(quality: str) -> Literal["standard", "hd", "low", "medium", "high", "auto"]:
    """校验并收窄图片质量。"""

    allowed_qualities = {"standard", "hd", "low", "medium", "high", "auto"}
    if quality not in allowed_qualities:
        raise ValueError(f"不支持的图片质量: {quality}")
    return cast(Literal["standard", "hd", "low", "medium", "high", "auto"], quality)


def _normalize_pic_output_format(output_format: str) -> Literal["png", "jpeg", "webp"]:
    """校验并收窄输出格式。"""

    allowed_formats = {"png", "jpeg", "webp"}
    if output_format not in allowed_formats:
        raise ValueError(f"不支持的图片输出格式: {output_format}")
    return cast(Literal["png", "jpeg", "webp"], output_format)


def _normalize_pic_response_format(response_format: str) -> Literal["url", "b64_json"]:
    """校验并收窄响应格式。"""

    allowed_formats = {"url", "b64_json"}
    if response_format not in allowed_formats:
        raise ValueError(f"不支持的图片响应格式: {response_format}")
    return cast(Literal["url", "b64_json"], response_format)


def _normalize_picedit_size(
    size: str,
) -> Literal["auto", "1024x1024", "1536x1024", "1024x1536", "256x256", "512x512"]:
    """校验图片编辑接口支持的尺寸。"""

    allowed_sizes = {"auto", "1024x1024", "1536x1024", "1024x1536", "256x256", "512x512"}
    if size not in allowed_sizes:
        raise ValueError(f"图片编辑暂不支持该尺寸: {size}")
    return cast(Literal["auto", "1024x1024", "1536x1024", "1024x1536", "256x256", "512x512"], size)


def _normalize_picedit_quality(quality: str) -> Literal["standard", "low", "medium", "high", "auto"]:
    """校验图片编辑接口支持的质量。"""

    allowed_qualities = {"standard", "low", "medium", "high", "auto"}
    if quality not in allowed_qualities:
        raise ValueError(f"图片编辑暂不支持该质量: {quality}")
    return cast(Literal["standard", "low", "medium", "high", "auto"], quality)


def _write_pic_trace(trace_output_file: Path, payload: dict[str, object]) -> None:
    """写入图片任务 trace，确保失败场景也有可排查信息。"""

    trace_output_file.parent.mkdir(parents=True, exist_ok=True)
    trace_output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_refine_instructions(template_name: str) -> str:
    """从 PromptManager 读取提示词优化模板。"""

    return get_prompt_manager().render(template_name)


async def _refine_pic_prompt_async(prompt: str, config: CodexConfig) -> str:
    """先用文本模型把原始 Markdown 润色成更适合做图的提示词。"""

    set_tracing_disabled(True)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    model = OpenAIResponsesModel(model=config.model, openai_client=client)
    agent = Agent(
        name="Codex Pic Prompt Refiner",
        instructions=_build_refine_instructions("codex_pic_refine"),
        model=model,
        tools=[],
    )  # type: ignore[misc]
    result = await Runner.run(agent, input=prompt)  # type: ignore[misc]
    final_output = cast(object | None, result.final_output)
    if final_output is None:
        raise RuntimeError("图片提示词润色失败：未返回结果")
    refined_prompt = str(final_output).strip()
    if not refined_prompt:
        raise RuntimeError("图片提示词润色失败：返回内容为空")
    return refined_prompt


async def _refine_picedit_prompt_async(prompt: str, config: CodexConfig) -> str:
    """把用户编辑意图润色成更适合图片编辑模型的提示词。"""

    set_tracing_disabled(True)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    model = OpenAIResponsesModel(model=config.model, openai_client=client)
    agent = Agent(
        name="Codex Pic Edit Prompt Refiner",
        instructions=_build_refine_instructions("codex_picedit_refine"),
        model=model,
        tools=[],
    )  # type: ignore[misc]
    result = await Runner.run(agent, input=prompt)  # type: ignore[misc]
    final_output = cast(object | None, result.final_output)
    if final_output is None:
        raise RuntimeError("图片编辑提示词润色失败：未返回结果")
    refined_prompt = str(final_output).strip()
    if not refined_prompt:
        raise RuntimeError("图片编辑提示词润色失败：返回内容为空")
    return refined_prompt


def _extract_usage_value(usage: object, field_names: tuple[str, ...]) -> int | None:
    """兼容对象和字典两种 usage 结构。"""

    for field_name in field_names:
        value = (
            cast(Mapping[str, object], usage).get(field_name)
            if isinstance(usage, Mapping)
            else _safe_getattr(usage, field_name)
        )
        if isinstance(value, int):
            return value
    return None


def _extract_usage_tokens(response: object) -> _TokenUsage:
    """尽量从不同 SDK 返回对象中提取 token 使用量。"""

    usage = _safe_getattr(response, "usage")
    if usage is None:
        return _TokenUsage(input_tokens=None, output_tokens=None, total_tokens=None)

    input_tokens = _extract_usage_value(usage, ("input_tokens", "prompt_tokens", "input_tokens_total"))
    output_tokens = _extract_usage_value(usage, ("output_tokens", "completion_tokens", "output_tokens_total"))
    total_tokens = _extract_usage_value(usage, ("total_tokens",))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return _TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens)


def _token_usage_to_payload(token_usage: _TokenUsage) -> dict[str, int | None]:
    """将 token 使用量转换为可序列化结构。"""

    return {
        "input_tokens": token_usage.input_tokens,
        "output_tokens": token_usage.output_tokens,
        "total_tokens": token_usage.total_tokens,
    }


def _log_pic_stage(
    stage: str,
    *,
    source: Path,
    original_prompt: str,
    refined_prompt: str | None = None,
    elapsed_seconds: float | None = None,
    token_usage: _TokenUsage | None = None,
    output_file: Path | None = None,
) -> None:
    """统一记录图片任务日志，便于排查提示词、耗时和 token。"""

    logger.info(
        "图片任务阶段=%s source=%s original_prompt=%s refined_prompt=%s elapsed_seconds=%s token_usage=%s output_file=%s",
        stage,
        source,
        original_prompt,
        refined_prompt,
        elapsed_seconds,
        _token_usage_to_payload(token_usage) if token_usage is not None else None,
        output_file,
    )


def _safe_getattr(obj: object, attr: str) -> object | None:
    """用 object 结果收敛 getattr 返回值，避免 Any 外溢。"""

    return cast(object | None, getattr(obj, attr, None))


async def run_codex_pic_async(
    *,
    md_path: Path,
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexPicResult:
    """执行图片生成任务，并写入 output/pic/<文件名> 目录。"""

    if not md_path.exists():
        raise FileNotFoundError(f"Markdown 文件不存在: {md_path}")
    if not md_path.is_file():
        raise ValueError(f"Markdown 路径不是文件: {md_path}")
    if md_path.suffix.lower() != ".md":
        raise ValueError(f"pic 输入必须是 Markdown 文件: {md_path}")

    prompt = md_path.read_text(encoding="utf-8")
    total_started_at = time.monotonic()
    config = get_config().codex
    _require_codex_pic_config(config)
    pic_size = _normalize_pic_size(size or config.pic_size)
    pic_quality = _normalize_pic_quality(quality or config.pic_quality)
    pic_output_format = _normalize_pic_output_format(output_format or config.pic_output_format)
    pic_response_format = _normalize_pic_response_format(config.pic_response_format)
    output_dir, image_output_file, trace_output_file = _resolve_pic_output_paths(md_path, pic_output_format)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_payload: dict[str, object] = {
        "status": "started",
        "original_prompt": prompt,
        "refine_model": config.model,
        "pic_model": config.pic_model,
        "size": pic_size,
        "quality": pic_quality,
        "output_format": pic_output_format,
        "response_format": pic_response_format,
        "refine_timeout_seconds": max(config.timeout_seconds, DEFAULT_PIC_REFINE_TIMEOUT_SECONDS),
        "image_timeout_seconds": max(config.timeout_seconds, DEFAULT_PIC_IMAGE_TIMEOUT_SECONDS),
    }
    _write_pic_trace(trace_output_file, trace_payload)
    _log_pic_stage("pic_started", source=md_path, original_prompt=prompt)
    refine_timeout_seconds = max(config.timeout_seconds, DEFAULT_PIC_REFINE_TIMEOUT_SECONDS)

    console.print(f"[pic] 开始优化做图提示词（超时 {refine_timeout_seconds}s）...", style="cyan")
    logger.info("开始优化做图提示词: md_path=%s model=%s timeout=%ss", md_path, config.model, refine_timeout_seconds)
    refine_started_at = time.monotonic()
    try:
        refined_prompt = await asyncio.wait_for(
            _refine_pic_prompt_async(prompt, config), timeout=refine_timeout_seconds
        )
    except Exception as exc:
        trace_payload["status"] = "refine_failed"
        trace_payload["refine_elapsed_seconds"] = round(time.monotonic() - refine_started_at, 3)
        trace_payload["error"] = str(exc)
        _write_pic_trace(trace_output_file, trace_payload)
        logger.exception("优化做图提示词失败: md_path=%s", md_path)
        raise

    trace_payload["status"] = "refined"
    trace_payload["refine_elapsed_seconds"] = round(time.monotonic() - refine_started_at, 3)
    trace_payload["refined_prompt"] = refined_prompt
    trace_payload["refine_token_usage"] = _token_usage_to_payload(
        _TokenUsage(input_tokens=None, output_tokens=None, total_tokens=None)
    )
    _write_pic_trace(trace_output_file, trace_payload)
    _log_pic_stage(
        "pic_refined",
        source=md_path,
        original_prompt=prompt,
        refined_prompt=refined_prompt,
        elapsed_seconds=cast(float, trace_payload["refine_elapsed_seconds"]),
        token_usage=_TokenUsage(input_tokens=None, output_tokens=None, total_tokens=None),
    )
    image_timeout_seconds = max(config.timeout_seconds, DEFAULT_PIC_IMAGE_TIMEOUT_SECONDS)
    console.print(f"[pic] 提示词优化完成，开始生成图片（超时 {image_timeout_seconds}s）...", style="cyan")
    logger.info(
        "开始生成图片: md_path=%s pic_model=%s size=%s quality=%s timeout=%ss",
        md_path,
        config.pic_model,
        pic_size,
        pic_quality,
        image_timeout_seconds,
    )

    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url, timeout=float(image_timeout_seconds))
    image_started_at = time.monotonic()
    try:
        response: ImagesResponse = await client.with_options(timeout=float(image_timeout_seconds)).images.generate(
            model=config.pic_model,
            prompt=refined_prompt,
            size=pic_size,
            quality=pic_quality,
            output_format=pic_output_format,
            response_format=pic_response_format,
        )
    except Exception as exc:
        trace_payload["status"] = "image_generate_failed"
        trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
        trace_payload["error"] = str(exc)
        _write_pic_trace(trace_output_file, trace_payload)
        logger.exception("生成图片失败: md_path=%s", md_path)
        raise

    image_token_usage = _extract_usage_tokens(response)
    image_bytes = base64.b64decode(_extract_image_b64_json(response))
    image_output_file.write_bytes(image_bytes)
    trace_payload["status"] = "completed"
    trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
    trace_payload["total_elapsed_seconds"] = round(time.monotonic() - total_started_at, 3)
    trace_payload["image_token_usage"] = _token_usage_to_payload(image_token_usage)
    trace_payload["image_response"] = str(response)
    trace_payload["image_output_file"] = str(image_output_file)
    _write_pic_trace(trace_output_file, trace_payload)
    _log_pic_stage(
        "pic_completed",
        source=md_path,
        original_prompt=prompt,
        refined_prompt=refined_prompt,
        elapsed_seconds=cast(float, trace_payload["total_elapsed_seconds"]),
        token_usage=image_token_usage,
        output_file=image_output_file,
    )
    console.print("[pic] 图片生成完成，开始写入结果文件...", style="cyan")
    logger.info("图片生成完成: image_output=%s trace_output=%s", image_output_file, trace_output_file)

    return CodexPicResult(
        output_dir=output_dir,
        image_output_file=image_output_file,
        trace_output_file=trace_output_file,
    )


def run_codex_pic(
    *,
    md_path: Path,
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexPicResult:
    """同步执行图片生成任务。"""

    return asyncio.run(run_codex_pic_async(md_path=md_path, size=size, quality=quality, output_format=output_format))


async def run_codex_picedit_async(
    *,
    image_path: Path,
    prompt: str,
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexPicResult:
    """执行图片编辑任务，并写入 output/pic/<原文件名>_version_xxx.*。"""

    if not image_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    if not image_path.is_file():
        raise ValueError(f"图片路径不是文件: {image_path}")
    if not prompt.strip():
        raise ValueError("图片编辑提示词不能为空")

    total_started_at = time.monotonic()
    config = get_config().codex
    _require_codex_pic_config(config)
    pic_size = _normalize_picedit_size(size or config.pic_size)
    pic_quality = _normalize_picedit_quality(quality or config.pic_quality)
    pic_output_format = _normalize_pic_output_format(output_format or config.pic_output_format)
    pic_response_format = _normalize_pic_response_format(config.pic_response_format)
    output_dir, image_output_file, trace_output_file = _resolve_picedit_output_paths(image_path, pic_output_format)
    trace_payload: dict[str, object] = {
        "status": "started",
        "source_image": str(image_path),
        "original_prompt": prompt,
        "refine_model": config.model,
        "pic_model": config.pic_model,
        "size": pic_size,
        "quality": pic_quality,
        "output_format": pic_output_format,
        "response_format": pic_response_format,
        "refine_timeout_seconds": max(config.timeout_seconds, DEFAULT_PIC_REFINE_TIMEOUT_SECONDS),
        "image_timeout_seconds": max(config.timeout_seconds, DEFAULT_PIC_IMAGE_TIMEOUT_SECONDS),
    }
    _write_pic_trace(trace_output_file, trace_payload)
    _log_pic_stage("picedit_started", source=image_path, original_prompt=prompt)
    refine_timeout_seconds = max(config.timeout_seconds, DEFAULT_PIC_REFINE_TIMEOUT_SECONDS)

    console.print(f"[picedit] 开始优化改图提示词（超时 {refine_timeout_seconds}s）...", style="cyan")
    logger.info(
        "开始优化改图提示词: image_path=%s model=%s timeout=%ss", image_path, config.model, refine_timeout_seconds
    )
    refine_started_at = time.monotonic()
    try:
        refined_prompt = await asyncio.wait_for(
            _refine_picedit_prompt_async(prompt, config), timeout=refine_timeout_seconds
        )
    except Exception as exc:
        trace_payload["status"] = "refine_failed"
        trace_payload["refine_elapsed_seconds"] = round(time.monotonic() - refine_started_at, 3)
        trace_payload["error"] = str(exc)
        _write_pic_trace(trace_output_file, trace_payload)
        logger.exception("优化改图提示词失败: image_path=%s", image_path)
        raise

    trace_payload["status"] = "refined"
    trace_payload["refine_elapsed_seconds"] = round(time.monotonic() - refine_started_at, 3)
    trace_payload["refined_prompt"] = refined_prompt
    trace_payload["refine_token_usage"] = _token_usage_to_payload(
        _TokenUsage(input_tokens=None, output_tokens=None, total_tokens=None)
    )
    _write_pic_trace(trace_output_file, trace_payload)
    _log_pic_stage(
        "picedit_refined",
        source=image_path,
        original_prompt=prompt,
        refined_prompt=refined_prompt,
        elapsed_seconds=cast(float, trace_payload["refine_elapsed_seconds"]),
        token_usage=_TokenUsage(input_tokens=None, output_tokens=None, total_tokens=None),
    )
    image_timeout_seconds = max(config.timeout_seconds, DEFAULT_PIC_IMAGE_TIMEOUT_SECONDS)
    console.print(f"[picedit] 提示词优化完成，开始修改图片（超时 {image_timeout_seconds}s）...", style="cyan")
    logger.info(
        "开始修改图片: image_path=%s pic_model=%s size=%s quality=%s timeout=%ss",
        image_path,
        config.pic_model,
        pic_size,
        pic_quality,
        image_timeout_seconds,
    )

    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url, timeout=float(image_timeout_seconds))
    image_started_at = time.monotonic()
    try:
        with image_path.open("rb") as image_handle:
            response: ImagesResponse = await client.with_options(timeout=float(image_timeout_seconds)).images.edit(
                model=config.pic_model,
                image=image_handle,
                prompt=refined_prompt,
                size=pic_size,
                quality=pic_quality,
                output_format=pic_output_format,
                response_format=pic_response_format,
            )
    except Exception as exc:
        trace_payload["status"] = "image_edit_failed"
        trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
        trace_payload["error"] = str(exc)
        _write_pic_trace(trace_output_file, trace_payload)
        logger.exception("修改图片失败: image_path=%s", image_path)
        raise

    image_token_usage = _extract_usage_tokens(response)
    image_bytes = base64.b64decode(_extract_image_b64_json(response))
    image_output_file.write_bytes(image_bytes)
    trace_payload["status"] = "completed"
    trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
    trace_payload["total_elapsed_seconds"] = round(time.monotonic() - total_started_at, 3)
    trace_payload["image_token_usage"] = _token_usage_to_payload(image_token_usage)
    trace_payload["image_response"] = str(response)
    trace_payload["image_output_file"] = str(image_output_file)
    _write_pic_trace(trace_output_file, trace_payload)
    _log_pic_stage(
        "picedit_completed",
        source=image_path,
        original_prompt=prompt,
        refined_prompt=refined_prompt,
        elapsed_seconds=cast(float, trace_payload["total_elapsed_seconds"]),
        token_usage=image_token_usage,
        output_file=image_output_file,
    )
    console.print("[picedit] 图片修改完成，开始写入结果文件...", style="cyan")
    logger.info("图片修改完成: image_output=%s trace_output=%s", image_output_file, trace_output_file)

    return CodexPicResult(
        output_dir=output_dir,
        image_output_file=image_output_file,
        trace_output_file=trace_output_file,
    )


def run_codex_picedit(
    *,
    image_path: Path,
    prompt: str,
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexPicResult:
    """同步执行图片编辑任务。"""

    return asyncio.run(
        run_codex_picedit_async(
            image_path=image_path,
            prompt=prompt,
            size=size,
            quality=quality,
            output_format=output_format,
        )
    )


async def _run_codex_pic_single_async(
    md_path: Path,
    semaphore: asyncio.Semaphore,
    size: str | None,
    quality: str | None,
    output_format: str | None,
) -> CodexPicBatchItemResult:
    """受限并发执行单个做图任务。"""

    async with semaphore:
        try:
            result = await run_codex_pic_async(md_path=md_path, size=size, quality=quality, output_format=output_format)
        except Exception as exc:
            trace_output_file: Path | None = None
            resolved_output_format = output_format or get_config().codex.pic_output_format
            try:
                _, _, trace_output_file = _resolve_pic_output_paths(
                    md_path, _normalize_pic_output_format(resolved_output_format)
                )
            except Exception:
                trace_output_file = None
            return CodexPicBatchItemResult(
                md_path=md_path,
                succeeded=False,
                image_output_file=None,
                trace_output_file=trace_output_file,
                error_message=str(exc),
            )

        return CodexPicBatchItemResult(
            md_path=md_path,
            succeeded=True,
            image_output_file=result.image_output_file,
            trace_output_file=result.trace_output_file,
            error_message=None,
        )


async def _run_codex_picbatch_async(
    md_paths: list[Path],
    size: str | None,
    quality: str | None,
    output_format: str | None,
) -> CodexPicBatchResult:
    """批量并发做图，单项失败不影响整体。"""

    semaphore = asyncio.Semaphore(2)
    tasks = [
        _run_codex_pic_single_async(
            md_path=md_path,
            semaphore=semaphore,
            size=size,
            quality=quality,
            output_format=output_format,
        )
        for md_path in md_paths
    ]
    return CodexPicBatchResult(results=list(await asyncio.gather(*tasks)))


def run_codex_picbatch(
    md_paths: list[Path],
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexPicBatchResult:
    """并发处理多个 Markdown 做图。"""

    if not md_paths:
        raise ValueError("md_paths 不能为空")

    return asyncio.run(_run_codex_picbatch_async(md_paths, size, quality, output_format))
