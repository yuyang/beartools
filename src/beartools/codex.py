"""Codex 业务模块。"""

from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
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

    type _OfficialToolEventItem = ReasoningItem | ToolCallItem | ToolCallOutputItem
else:
    type _OfficialToolEventItem = object
    type RunResultStreaming = object
    type RawResponsesStreamEvent = object
    type RunItemStreamEvent = object

console = Console()
logger = get_logger(__name__)


@dataclass
class CodexRunResult:
    """Codex 执行结果。"""

    final_output_file: Path
    trace_output_file: Path
    final_text: str


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
