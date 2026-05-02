"""Codex 业务模块。"""

from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import cast

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


def _serialize_event(event: Mapping[str, object]) -> str:
    return json.dumps(event, ensure_ascii=False)


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


async def _communicate_process(communicate_result: object, timeout_seconds: int) -> tuple[bytes, bytes]:
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


async def _stream_codex_events(prompt: str) -> AsyncIterator[dict[str, object]]:
    from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
    from openai import AsyncOpenAI
    from openai.types.responses import ResponseTextDeltaEvent

    config = get_config().codex
    _require_codex_config(config)

    set_tracing_disabled(True)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    model = OpenAIChatCompletionsModel(model=config.model, openai_client=client)
    agent = Agent(
        name="Codex Runner",
        instructions=config.instructions,
        model=model,
        tools=_build_codex_tools(),
    )  # type: ignore[misc]
    result = Runner.run_streamed(agent, input=prompt)  # type: ignore[misc]
    stream_events = result.stream_events

    async for event in stream_events():
        event_type = str(getattr(event, "type", ""))  # type: ignore[misc]
        if event_type == "raw_response_event":
            data = getattr(event, "data", None)  # type: ignore[misc]
            if isinstance(data, ResponseTextDeltaEvent):  # type: ignore[misc]
                yield {"type": "response.output_text.delta", "delta": str(data.delta)}
        elif event_type == "run_item_stream_event":
            item = getattr(event, "item", None)  # type: ignore[misc]
            item_type = str(getattr(item, "type", ""))  # type: ignore[misc]
            event_name = str(getattr(event, "name", ""))  # type: ignore[misc]
            if item_type == "tool_call_item":
                raw_item = getattr(item, "raw_item", None)  # type: ignore[misc]
                tool_name = str(getattr(raw_item, "name", getattr(item, "name", "tool")))  # type: ignore[misc]
                yield {"type": "tool_called", "name": tool_name}
            elif item_type == "tool_call_output_item":
                tool_output = str(getattr(item, "output", ""))  # type: ignore[misc]
                yield {"type": "tool_output", "output": tool_output}
            elif event_name == "reasoning_item_created":
                yield {"type": "reasoning_item_created", "text": str(item)}  # type: ignore[misc]


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
