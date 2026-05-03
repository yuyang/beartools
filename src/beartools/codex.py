"""Codex 业务模块。"""

from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
from collections.abc import AsyncIterator, Awaitable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from agents import ShellTool, Tool, WebSearchTool
from agents.tool import ShellCallOutcome, ShellCommandOutput, ShellCommandRequest, ShellResult
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


@dataclass
class _InternalRunResult:
    """内部运行结果，统一承载事件流和最终文本。"""

    events: AsyncIterator[_CodexStreamEvent]
    final_text: str


@dataclass(frozen=True)
class _CodexStreamEvent:
    type: Literal[
        "response.output_text.delta",
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


def _stream_final_text(stream: RunResultStreaming) -> str:
    """显式收敛官方 stream.final_output 的类型。"""

    final_output = _safe_getattr(stream, "final_output")
    return "" if final_output is None else str(final_output)


def _to_safe_jsonable(value: object) -> object:
    """尽量把对象转成安全可序列化的结构。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _to_safe_jsonable(item) for key, item in cast(Mapping[str, object], value).items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_safe_jsonable(item) for item in value]

    normalized: dict[str, object] = {}
    value_type = _safe_getattr(value, "type")
    if value_type is not None:
        normalized["type"] = str(value_type)
    value_name = _safe_getattr(value, "name")
    if value_name is not None:
        normalized["name"] = str(value_name)
    if normalized:
        return {key: _to_safe_jsonable(item) for key, item in normalized.items()}
    return str(value)


def _build_unknown_event(event: object) -> _CodexStreamEvent:
    """把无法识别的事件统一转换为 unknown_event。"""

    event_type = _extract_event_type(event)
    raw = _to_safe_jsonable(event)
    return _CodexStreamEvent(type="unknown_event", message=f"{event_type}: {raw}")


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

    return [WebSearchTool(), ShellTool(executor=_shell_tool_executor)]


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


async def _run_codex_stream(prompt: str) -> _InternalRunResult:
    from agents import Agent, OpenAIResponsesModel, Runner, set_tracing_disabled
    from agents.items import ReasoningItem, ToolCallItem, ToolCallOutputItem
    from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
    from openai import AsyncOpenAI

    config = get_config().codex
    _require_codex_config(config)

    set_tracing_disabled(True)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    model = OpenAIResponsesModel(model=config.model, openai_client=client)
    agent = Agent(
        name="Codex Runner",
        instructions=config.instructions,
        model=model,
        tools=_build_codex_tools(),
    )  # type: ignore[misc]
    stream = Runner.run_streamed(agent, input=prompt)  # type: ignore[misc]

    async def _iter_events() -> AsyncIterator[_CodexStreamEvent]:
        try:
            async for event in stream.stream_events():
                if (
                    isinstance(event, RawResponsesStreamEvent)
                    and _safe_getattr(event.data, "type") == "response.output_text.delta"
                ):
                    delta = str(_safe_getattr(event.data, "delta") or "")
                    yield _CodexStreamEvent(type="response.output_text.delta", message=delta, display_text=delta)
                    continue

                if isinstance(event, RunItemStreamEvent):
                    item = event.item
                    if isinstance(item, ToolCallItem):  # type: ignore[misc]
                        tool_name = _resolve_official_tool_name(item)
                        yield _CodexStreamEvent(
                            type="tool_called", message=tool_name, display_text=f"[tool:start] {tool_name}"
                        )
                        continue
                    if isinstance(item, ToolCallOutputItem):  # type: ignore[misc]
                        output = str(_safe_getattr(item, "output") or "")
                        yield _CodexStreamEvent(
                            type="tool_output", message=output, display_text=f"[tool:output] {output}"
                        )
                        continue
                    if isinstance(item, ReasoningItem):  # type: ignore[misc]
                        text = str(_safe_getattr(item, "raw_item") or "")
                        yield _CodexStreamEvent(
                            type="reasoning_item_created", message=text, display_text=f"[thinking] {text}"
                        )
                        continue

                yield _build_unknown_event(event)
        except Exception as exc:
            # 事件流仅用于记录，不应影响最终输出。
            yield _CodexStreamEvent(type="unknown_event", message=f"stream_error: {exc}")

    final_text = _stream_final_text(stream)
    return _InternalRunResult(events=_iter_events(), final_text=final_text)


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
    final_output_file, trace_output_file = _resolve_output_paths(md_path, output_file, trace_file, config)

    logger.info("开始执行 Codex: md_path=%s model=%s", md_path, config.model)

    run = _InternalRunResult(events=_empty_event_iterator(), final_text="")
    with trace_output_file.open("w", encoding="utf-8") as trace_handle:
        try:
            run = await _run_codex_stream(prompt)
            async for event in run.events:
                serialized_event = _serialize_event(event)
                trace_handle.write(serialized_event + "\n")
                trace_handle.flush()
                logger.info("Codex stream event: %s", serialized_event)
                if event.display_text:
                    end = "" if event.type == "response.output_text.delta" else "\n"
                    console.print(event.display_text, end=end)
        except Exception as exc:
            stream_error_event = _CodexStreamEvent(type="unknown_event", message=f"stream_error: {exc}")
            serialized_event = _serialize_event(stream_error_event)
            trace_handle.write(serialized_event + "\n")
            trace_handle.flush()
            logger.warning("Codex 事件流记录异常，忽略并继续输出最终结果: %s", exc)

    final_text = run.final_text
    final_output_file.write_text(final_text, encoding="utf-8")
    logger.info("Codex 执行完成: final_output=%s trace_output=%s", final_output_file, trace_output_file)
    return CodexRunResult(
        final_output_file=final_output_file, trace_output_file=trace_output_file, final_text=final_text
    )


def run_codex_markdown(*, md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
    """同步执行 Codex Markdown 任务。"""

    return asyncio.run(run_codex_markdown_async(md_path=md_path, output_file=output_file, trace_file=trace_file))


async def _empty_event_iterator() -> AsyncIterator[_CodexStreamEvent]:
    """为异常兜底提供空事件流。"""

    if False:
        yield {}
