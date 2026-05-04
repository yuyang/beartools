"""Codex 业务模块。"""

from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
import base64
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING, Literal, cast

from agents import Agent, OpenAIResponsesModel, Runner, Tool, WebSearchTool, set_tracing_disabled
from agents.items import ReasoningItem, ToolCallItem, ToolCallOutputItem
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from agents.tool import ShellCallOutcome, ShellCommandOutput, ShellCommandRequest, ShellResult
from openai import AsyncOpenAI
from rich.console import Console

from beartools.config import CodexConfig, get_config
from beartools.logger import get_logger

if TYPE_CHECKING:
    from agents.items import ReasoningItem, ToolCallItem, ToolCallOutputItem
    from agents.result import RunResultStreaming
    from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
    from openai.types.images_response import ImagesResponse

    type _OfficialToolEventItem = ReasoningItem | ToolCallItem | ToolCallOutputItem
else:
    type _OfficialToolEventItem = object
    type RunResultStreaming = object
    type RawResponsesStreamEvent = object
    type RunItemStreamEvent = object

console = Console()
logger = get_logger(__name__)
DEFAULT_PIC_REFINE_TIMEOUT_SECONDS = 300
DEFAULT_PIC_IMAGE_TIMEOUT_SECONDS = 600


@dataclass
class CodexRunResult:
    """Codex 执行结果。"""

    final_output_file: Path
    trace_output_file: Path
    final_text: str


@dataclass
class CodexPicResult:
    """Codex 图片任务执行结果。"""

    output_dir: Path
    image_output_file: Path
    trace_output_file: Path


@dataclass(frozen=True)
class _CodexStreamEvent:
    type: Literal[
        "response.output_text.delta",
        "response.lifecycle",
        "agent_updated_stream_event",
        "tool_called",
        "tool_output",
        "reasoning_item_created",
        "unknown_event",
    ]
    message: str
    display_text: str = ""


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


def _resolve_output_paths(
    md_path: Path,
    output_file: Path | None,
    trace_file: Path | None,
    config: CodexConfig,
) -> tuple[Path, Path]:
    base_output_dir = config.output_dir
    final_output_file = output_file or base_output_dir / f"{md_path.stem}.codex.md"
    trace_output_file = trace_file or base_output_dir / f"{md_path.stem}.codex.trace.log"
    final_output_file.parent.mkdir(parents=True, exist_ok=True)
    trace_output_file.parent.mkdir(parents=True, exist_ok=True)
    return final_output_file, trace_output_file


def _resolve_pic_output_paths(md_path: Path, output_format: str) -> tuple[Path, Path, Path]:
    """解析 pic 子命令的固定输出路径。"""

    output_dir = Path("output") / "pic" / md_path.stem
    final_output_file = output_dir / f"{md_path.stem}.{output_format}"
    trace_output_file = output_dir / f"{md_path.stem}.trace.log"
    return output_dir, final_output_file, trace_output_file


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


def _write_pic_trace(trace_output_file: Path, payload: dict[str, object]) -> None:
    """写入图片任务 trace，确保失败场景也有可排查信息。"""

    trace_output_file.parent.mkdir(parents=True, exist_ok=True)
    trace_output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def _refine_pic_prompt_async(prompt: str, config: CodexConfig) -> str:
    """先用文本模型把原始 Markdown 润色成更适合做图的提示词。"""

    set_tracing_disabled(True)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    model = OpenAIResponsesModel(model=config.model, openai_client=client)
    agent = Agent(
        name="Codex Pic Prompt Refiner",
        instructions=(
            "你是图片提示词优化助手。"
            "请把用户给出的 Markdown 内容改写成适合图片生成模型使用的单段提示词，"
            "保留核心主体、场景、风格、构图、光线和质量要求，删除无关说明。"
            "只输出润色后的最终提示词，不要添加标题、解释或 Markdown。"
        ),
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


def _extract_event_type(event: object) -> str:
    """尽量从原始事件中提取事件类型。"""

    if isinstance(event, Mapping):
        event_type = cast(Mapping[str, object], event).get("type")
        if event_type is not None:
            return str(event_type)
    event_type = _safe_getattr(event, "type")
    if event_type is not None:
        return str(event_type)
    return type(event).__name__


def _safe_getattr(obj: object, attr: str) -> object | None:
    """用 object 结果收敛 getattr 返回值，避免 Any 外溢。"""

    return cast(object | None, getattr(obj, attr, None))


def _build_unknown_event(event: object) -> _CodexStreamEvent:
    """把无法识别的事件统一转换为 unknown_event。"""

    event_type = _extract_event_type(event)
    return _CodexStreamEvent(type="unknown_event", message=f"{event_type}: {event}")


def _serialize_event(event: _CodexStreamEvent) -> str:
    payload: dict[str, str] = {"type": event.type, "message": event.message, "display_text": event.display_text}
    return json.dumps(payload, ensure_ascii=False)


async def _execute_shell_commands(commands: list[str], timeout_seconds: int) -> ShellResult:
    """在 output/codex 目录执行 shell 命令。"""

    working_dir = Path.cwd() / "output" / "codex"
    working_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[ShellCommandOutput] = []
    for command in commands:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=working_dir,
            stdout=PIPE,
            stderr=PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await _communicate_process(process.communicate(), timeout_seconds)
            outcome = ShellCallOutcome(type="exit", exit_code=process.returncode)
        except TimeoutError:
            process.kill()
            stdout_bytes, stderr_bytes = await _communicate_process(process.communicate(), timeout_seconds)
            outcome = ShellCallOutcome(type="timeout")

        outputs.append(
            ShellCommandOutput(
                command=command,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                outcome=outcome,
            )
        )

    return ShellResult(output=outputs)


async def _communicate_process(
    communicate_result: Awaitable[tuple[bytes, bytes]],
    timeout_seconds: int,
) -> tuple[bytes, bytes]:
    """为 subprocess communicate 返回值补充静态类型。"""

    return await asyncio.wait_for(communicate_result, timeout=timeout_seconds)


async def _shell_tool_executor(request: ShellCommandRequest) -> str | ShellResult:
    """将 ShellTool 请求转交给本地执行器。"""

    config = get_config().codex
    commands = list(request.data.action.commands)
    return await _execute_shell_commands(commands, timeout_seconds=config.timeout_seconds)


def _build_codex_tools() -> list[Tool]:
    """构建 Codex 运行时可用工具。"""

    return [WebSearchTool()]


def _resolve_official_tool_name(event_item: _OfficialToolEventItem) -> str:
    """尽量从官方工具调用事件里提取工具名。"""

    raw = _safe_getattr(event_item, "raw_item")
    if raw is not None:
        raw_name = _safe_getattr(raw, "name")
        if raw_name is not None:
            return str(raw_name)
        raw_type = _safe_getattr(raw, "type")
        if raw_type is not None:
            return str(raw_type)
    item_type = _safe_getattr(event_item, "type")
    if item_type is not None:
        return str(item_type)
    return "tool"


def _normalize_raw_response_item_event(event_data: object) -> _CodexStreamEvent | None:
    """补充处理 Responses 原始事件里已完成的 item。"""

    item = _safe_getattr(event_data, "item")
    if item is None:
        return None

    item_type = str(_safe_getattr(item, "type") or "")
    if item_type.endswith("_call"):
        return _CodexStreamEvent(type="tool_called", message=item_type, display_text=f"[tool:start] {item_type}")

    if item_type in {"reasoning", "reasoning_item"}:
        text = str(item)
        return _CodexStreamEvent(type="reasoning_item_created", message=text, display_text=f"[thinking] {text}")

    return None


def _normalize_stream_event(event: object) -> _CodexStreamEvent:
    """把官方 stream 事件统一映射为内部事件结构。"""

    # 这些事件类型在运行时必须保证为真实类对象，避免被 TYPE_CHECKING 占位类型污染。
    from agents.items import ReasoningItem as RuntimeReasoningItem
    from agents.items import ToolCallItem as RuntimeToolCallItem
    from agents.items import ToolCallOutputItem as RuntimeToolCallOutputItem
    from agents.stream_events import AgentUpdatedStreamEvent as RuntimeAgentUpdatedStreamEvent
    from agents.stream_events import RawResponsesStreamEvent as RuntimeRawResponsesStreamEvent
    from agents.stream_events import RunItemStreamEvent as RuntimeRunItemStreamEvent

    if isinstance(event, cast(type[object], RuntimeAgentUpdatedStreamEvent)):
        event_type = str(_safe_getattr(event, "type") or "agent_updated_stream_event")
        return _CodexStreamEvent(type="agent_updated_stream_event", message=f"{event_type}: {event}")

    event_data = _safe_getattr(event, "data")
    if (
        isinstance(event, RuntimeRawResponsesStreamEvent)
        and _safe_getattr(event_data, "type") == "response.output_text.delta"
    ):
        delta = str(_safe_getattr(event_data, "delta") or "")
        return _CodexStreamEvent(type="response.output_text.delta", message=delta, display_text=delta)

    if isinstance(event, RuntimeRawResponsesStreamEvent):
        normalized_item_event = _normalize_raw_response_item_event(event_data)
        if normalized_item_event is not None:
            return normalized_item_event

    if isinstance(event, RuntimeRunItemStreamEvent):
        item = _safe_getattr(event, "item")
        if isinstance(item, RuntimeToolCallItem):  # type: ignore[misc]
            tool_name = _resolve_official_tool_name(item)
            return _CodexStreamEvent(type="tool_called", message=tool_name, display_text=f"[tool:start] {tool_name}")
        if isinstance(item, RuntimeToolCallOutputItem):  # type: ignore[misc]
            output = str(_safe_getattr(item, "output") or "")
            return _CodexStreamEvent(type="tool_output", message=output, display_text=f"[tool:output] {output}")
        if isinstance(item, RuntimeReasoningItem):  # type: ignore[misc]
            text = str(_safe_getattr(item, "raw_item") or "")
            return _CodexStreamEvent(type="reasoning_item_created", message=text, display_text=f"[thinking] {text}")

    if isinstance(event, RuntimeRawResponsesStreamEvent) and event_data is not None:
        event_type = str(_safe_getattr(event_data, "type") or "raw_response_event")
        return _CodexStreamEvent(type="response.lifecycle", message=f"{event_type}: {event_data}")

    return _build_unknown_event(event)


async def run_codex_markdown_async(
    md_path: Path,
    output_file: Path | None,
    trace_file: Path | None,
) -> CodexRunResult:
    """执行 Codex Markdown 任务。"""

    if not md_path.exists():
        raise FileNotFoundError(f"Markdown 文件不存在: {md_path}")
    if not md_path.is_file():
        raise ValueError(f"Markdown 路径不是文件: {md_path}")

    prompt = md_path.read_text(encoding="utf-8")
    config = get_config().codex
    _require_codex_config(config)
    final_output_file, trace_output_file = _resolve_output_paths(md_path, output_file, trace_file, config)

    logger.info("开始执行 Codex: md_path=%s model=%s", md_path, config.model)

    set_tracing_disabled(True)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    model = OpenAIResponsesModel(model=config.model, openai_client=client)
    agent = Agent(
        name="Codex Runner",
        instructions=config.instructions,
        model=model,
        tools=_build_codex_tools(),
    )  # type: ignore[misc]

    final_text = ""
    with trace_output_file.open("w", encoding="utf-8") as trace_handle:
        stream = Runner.run_streamed(agent, input=prompt)  # type: ignore[misc]
        try:
            async for raw_event in stream.stream_events():
                try:
                    event = _normalize_stream_event(raw_event)
                    serialized_event = _serialize_event(event)
                    trace_handle.write(serialized_event + "\n")
                    trace_handle.flush()
                    logger.info("Codex stream event: %s", serialized_event)
                    if event.display_text:
                        end = "" if event.type == "response.output_text.delta" else "\n"
                        console.print(event.display_text, end=end)
                except Exception as exc:
                    event_error = _CodexStreamEvent(type="unknown_event", message=f"event_error: {exc}")
                    serialized_event = _serialize_event(event_error)
                    trace_handle.write(serialized_event + "\n")
                    trace_handle.flush()
                    logger.warning("Codex 单个事件处理异常，忽略并继续消费: %s", exc)
        except Exception as exc:
            stream_error_event = _CodexStreamEvent(type="unknown_event", message=f"stream_error: {exc}")
            serialized_event = _serialize_event(stream_error_event)
            trace_handle.write(serialized_event + "\n")
            trace_handle.flush()
            logger.warning("Codex 事件流记录异常，忽略并继续输出最终结果: %s", exc)
        final_output = cast(object | None, stream.final_output)
        if final_output is not None:
            final_text = str(final_output)

    final_output_file.write_text(final_text, encoding="utf-8")
    logger.info("Codex 执行完成: final_output=%s trace_output=%s", final_output_file, trace_output_file)
    return CodexRunResult(
        final_output_file=final_output_file, trace_output_file=trace_output_file, final_text=final_text
    )


def run_codex_markdown(*, md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
    """同步执行 Codex Markdown 任务。"""

    return asyncio.run(run_codex_markdown_async(md_path=md_path, output_file=output_file, trace_file=trace_file))


def run_codex_pic(
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
    refine_timeout_seconds = max(config.timeout_seconds, DEFAULT_PIC_REFINE_TIMEOUT_SECONDS)

    console.print(f"[pic] 开始优化做图提示词（超时 {refine_timeout_seconds}s）...", style="cyan")
    logger.info("开始优化做图提示词: md_path=%s model=%s timeout=%ss", md_path, config.model, refine_timeout_seconds)
    refine_started_at = time.monotonic()
    try:
        refined_prompt = asyncio.run(
            asyncio.wait_for(_refine_pic_prompt_async(prompt, config), timeout=refine_timeout_seconds)
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
    _write_pic_trace(trace_output_file, trace_payload)
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
        response: ImagesResponse = asyncio.run(
            client.with_options(timeout=float(image_timeout_seconds)).images.generate(
                model=config.pic_model,
                prompt=refined_prompt,
                size=pic_size,
                quality=pic_quality,
                output_format=pic_output_format,
                response_format=pic_response_format,
            )
        )
    except Exception as exc:
        trace_payload["status"] = "image_generate_failed"
        trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
        trace_payload["error"] = str(exc)
        _write_pic_trace(trace_output_file, trace_payload)
        logger.exception("生成图片失败: md_path=%s", md_path)
        raise

    image_bytes = base64.b64decode(_extract_image_b64_json(response))
    image_output_file.write_bytes(image_bytes)
    trace_payload["status"] = "completed"
    trace_payload["image_elapsed_seconds"] = round(time.monotonic() - image_started_at, 3)
    trace_payload["image_response"] = str(response)
    trace_payload["image_output_file"] = str(image_output_file)
    _write_pic_trace(trace_output_file, trace_payload)
    console.print("[pic] 图片生成完成，开始写入结果文件...", style="cyan")
    logger.info("图片生成完成: image_output=%s trace_output=%s", image_output_file, trace_output_file)

    return CodexPicResult(
        output_dir=output_dir,
        image_output_file=image_output_file,
        trace_output_file=trace_output_file,
    )
