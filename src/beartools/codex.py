"""Codex 业务模块。"""

from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
from collections.abc import AsyncIterator, Awaitable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol, TypeGuard, cast

from agents import ShellTool, Tool, WebSearchTool
from agents.tool import ShellCallOutcome, ShellCommandOutput, ShellCommandRequest, ShellResult
from rich.console import Console

from beartools.config import CodexConfig, get_config
from beartools.logger import get_logger

console = Console()
logger = get_logger(__name__)


@dataclass
class CodexRunResult:
    """Codex 执行结果。"""

    final_output_file: Path
    trace_output_file: Path
    final_text: str


class _CommunicateResult(Protocol):
    def __await__(self) -> object: ...


class _HasData(Protocol):
    data: object


class _HasItem(Protocol):
    item: object


class _HasName(Protocol):
    name: object


class _HasRawItem(Protocol):
    raw_item: object


class _HasOutput(Protocol):
    output: object


class _HasDelta(Protocol):
    delta: object


class _HasEventType(Protocol):
    type: object


def _has_data(value: object) -> TypeGuard[_HasData]:
    return hasattr(value, "data")


def _has_item(value: object) -> TypeGuard[_HasItem]:
    return hasattr(value, "item")


def _has_name(value: object) -> TypeGuard[_HasName]:
    return hasattr(value, "name")


def _has_raw_item(value: object) -> TypeGuard[_HasRawItem]:
    return hasattr(value, "raw_item")


def _has_output(value: object) -> TypeGuard[_HasOutput]:
    return hasattr(value, "output")


def _has_delta(value: object) -> TypeGuard[_HasDelta]:
    return hasattr(value, "delta")


def _has_event_type(value: object) -> TypeGuard[_HasEventType]:
    return hasattr(value, "type")


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


def _map_to_json(m: Mapping[str, object]) -> str:
    """把 Mapping 转为 JSON 字符串，保证键为 str。"""
    safe_map: dict[str, object] = {str(k): v for k, v in m.items()}
    return json.dumps(safe_map, ensure_ascii=False)


def _normalize_obj(obj: object) -> dict[str, object]:
    """把常见的 stream event 对象转换为简单 dict 表示。"""
    normalized: dict[str, object] = {}
    if _has_event_type(obj):
        normalized["type"] = str(obj.type)
    if _has_data(obj):
        normalized["data"] = str(obj.data)
    if _has_item(obj):
        itm = obj.item
        if isinstance(itm, Mapping):
            # 将 Mapping 映射为 dict[str, object]，避免 mypy 将 key/value 推断为 Any
            normalized["item"] = {str(key): value for key, value in cast(Mapping[str, object], itm).items()}
        else:
            normalized["item"] = str(itm)
    if _has_raw_item(obj):
        normalized["raw_item"] = str(obj.raw_item)
    if _has_output(obj):
        normalized["output"] = str(obj.output)
    if _has_delta(obj):
        normalized["delta"] = str(obj.delta)
    if _has_name(obj):
        normalized["name"] = str(obj.name)
    return normalized


def _normalize_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    """显式把 Mapping 规范化为 dict[str, object]。"""

    return {str(key): value for key, value in mapping.items()}


def _item_tool_called_name(it: object) -> str | None:
    """从 item 上提取工具名（兼容旧协议）。"""
    item_type = str(it.type) if _has_event_type(it) else ""
    if item_type != "tool_call_item":
        return None
    name = "tool"
    if _has_raw_item(it):
        raw = it.raw_item
        if _has_name(raw):
            return str(raw.name)
        if _has_event_type(raw):
            return str(raw.type)
    if _has_event_type(it):
        return str(it.type)
    return name


def _serialize_event(event: object) -> str:
    try:
        if isinstance(event, Mapping):
            return _map_to_json(cast(Mapping[str, object], event))
        return json.dumps(event, ensure_ascii=False)
    except TypeError:
        # 抽离规范化逻辑到独立函数以降低复杂度
        try:
            normalized = _serialize_event_normalize(event)
        except Exception:
            fallback_event: dict[str, object] = {"raw": str(event)}
            return json.dumps(fallback_event, ensure_ascii=False)

        return json.dumps(normalized, ensure_ascii=False)


def _serialize_event_normalize(event: object) -> dict[str, object]:
    """把 event 规范化为 dict[str, object]，用于 _serialize_event 的兜底分支。"""
    if isinstance(event, Mapping):
        return _normalize_mapping(cast(Mapping[str, object], event))

    normalized: dict[str, object] = {}
    if _has_event_type(event):
        normalized["type"] = str(event.type)
    if _has_data(event):
        normalized["data"] = str(event.data)
    if _has_item(event):
        itm = event.item
        if isinstance(itm, Mapping):
            normalized["item"] = {str(k): v for k, v in cast(Mapping[str, object], itm).items()}
        else:
            normalized["item"] = str(itm)
    if _has_raw_item(event):
        normalized["raw_item"] = str(event.raw_item)
    if _has_output(event):
        normalized["output"] = str(event.output)
    if _has_delta(event):
        normalized["delta"] = str(event.delta)
    if _has_name(event):
        normalized["name"] = str(event.name)
    return normalized


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
    communicate_result: Awaitable[tuple[bytes, bytes]] | _CommunicateResult,
    timeout_seconds: int,
) -> tuple[bytes, bytes]:
    """为 subprocess communicate 返回值补充静态类型。"""

    return cast(
        tuple[bytes, bytes],
        await asyncio.wait_for(communicate_result, timeout=timeout_seconds),  # type: ignore[arg-type,misc]
    )


async def _shell_tool_executor(request: ShellCommandRequest) -> str | ShellResult:
    """将 ShellTool 请求转交给本地执行器。"""

    config = get_config().codex
    commands = list(request.data.action.commands)
    return await _execute_shell_commands(commands, timeout_seconds=config.timeout_seconds)


def _build_codex_tools() -> list[Tool]:
    """构建 Codex 运行时可用工具。"""

    return [WebSearchTool(), ShellTool(executor=_shell_tool_executor)]


def _extract_official_stream_event(event: object) -> dict[str, object] | None:
    """优先解析官方 stream event / item 类型。"""

    from agents.items import ReasoningItem, ToolCallItem, ToolCallOutputItem
    from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
    from openai.types.responses import ResponseTextDeltaEvent

    if isinstance(event, RawResponsesStreamEvent) and isinstance(event.data, ResponseTextDeltaEvent):  # type: ignore[misc]
        return {"type": "response.output_text.delta", "delta": str(event.data.delta)}

    if not isinstance(event, RunItemStreamEvent):
        return None

    if isinstance(event.item, ToolCallItem):  # type: ignore[misc]
        # 尽量从官方 raw_item 中提取真实工具名，优先顺序：raw_item.name -> raw_item.type -> item.type -> "tool"
        tool_name = "tool"
        if _has_raw_item(event.item):
            raw = event.item.raw_item
            if _has_name(raw):
                tool_name = str(raw.name)
            elif _has_event_type(raw):
                tool_name = str(raw.type)
        elif _has_event_type(event.item):
            tool_name = str(event.item.type)
        return {"type": "tool_called", "name": tool_name}

    if isinstance(event.item, ToolCallOutputItem):  # type: ignore[misc]
        tool_output = cast(object, event.item.output)
        return {"type": "tool_output", "output": str(tool_output)}

    if isinstance(event.item, ReasoningItem):  # type: ignore[misc]
        return {"type": "reasoning_item_created", "text": str(event.item.raw_item)}

    return None


def _extract_fallback_stream_event(event: object) -> dict[str, object] | None:
    """兼容旧的字符串协议事件。"""
    # 简化为调用子函数以降低复杂度，行为保持不变
    if not _has_event_type(event):
        return None

    # raw_response_event 分支
    if _has_event_type(event) and str(event.type) == "raw_response_event":
        if _has_data(event) and _has_delta(event.data):
            return {"type": "response.output_text.delta", "delta": str(event.data.delta)}
        return None

    # run_item_stream_event 及其子分支
    if str(event.type) != "run_item_stream_event" or not _has_item(event):
        return None

    item = event.item
    tool_name = _item_tool_called_name(item)
    if tool_name is not None:
        return {"type": "tool_called", "name": tool_name}

    if _has_event_type(item) and str(item.type) == "tool_call_output_item" and _has_output(item):
        return {"type": "tool_output", "output": str(item.output)}

    if _has_name(event) and str(event.name) == "reasoning_item_created":
        return {"type": "reasoning_item_created", "text": str(item)}

    return None


async def _stream_codex_events(prompt: str) -> AsyncIterator[dict[str, object]]:
    from agents import Agent, OpenAIResponsesModel, Runner, set_tracing_disabled
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
    result = Runner.run_streamed(agent, input=prompt)  # type: ignore[misc]
    stream_events = result.stream_events

    async for event in stream_events():
        official_event = _extract_official_stream_event(event)
        if official_event is not None:
            yield official_event
            continue

        fallback_event = _extract_fallback_stream_event(event)
        if fallback_event is not None:
            yield fallback_event


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

    final_text_parts: list[str] = []
    with trace_output_file.open("w", encoding="utf-8") as trace_handle:
        try:
            async for event in _stream_codex_events(prompt):
                serialized_event = _serialize_event(event)
                trace_handle.write(serialized_event + "\n")
                trace_handle.flush()
                logger.info("Codex stream event: %s", serialized_event)

                event_type = str(event.get("type", ""))
                if event_type == "reasoning_item_created":
                    text = str(event.get("text", ""))
                    console.print(f"[thinking] {text}")
                elif event_type == "tool_called":
                    tool_name = str(event.get("name", "tool"))
                    console.print(f"[tool:start] {tool_name}")
                elif event_type == "tool_output":
                    output = str(event.get("output", ""))
                    console.print(f"[tool:output] {output}")
                elif event_type == "response.output_text.delta":
                    delta = str(event.get("delta", ""))
                    final_text_parts.append(delta)
                    console.print(delta, end="")
        except Exception as exc:
            partial_text = "".join(final_text_parts)
            final_output_file.write_text(f"[未完成]\n\n{partial_text}", encoding="utf-8")
            error_event = {"type": "error", "message": str(exc)}
            trace_handle.write(_serialize_event(error_event) + "\n")
            logger.error("Codex 执行失败: %s", exc)
            raise RuntimeError(f"Codex 执行失败: {exc}") from exc

    final_text = "".join(final_text_parts)
    final_output_file.write_text(final_text, encoding="utf-8")
    logger.info("Codex 执行完成: final_output=%s trace_output=%s", final_output_file, trace_output_file)
    return CodexRunResult(
        final_output_file=final_output_file, trace_output_file=trace_output_file, final_text=final_text
    )


def run_codex_markdown(*, md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
    """同步执行 Codex Markdown 任务。"""

    return asyncio.run(run_codex_markdown_async(md_path=md_path, output_file=output_file, trace_file=trace_file))
