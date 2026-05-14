"""Codex 小说转图片业务模块。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import cast

from agents import Agent, OpenAIResponsesModel, Runner, set_tracing_disabled
from openai import AsyncOpenAI
from rich.console import Console

from beartools.codex_pic import run_codex_pic_async
from beartools.config import CodexConfig, get_config
from beartools.logger import get_logger
from beartools.prompt import get_prompt_manager

logger = get_logger(__name__)
console = Console()
MAX_NOVEL_INPUT_CHARS = 30000
MIN_NOVEL_SCENE_COUNT = 1
MAX_NOVEL_SCENE_COUNT = 12
NOVEL_OUTPUT_ROOT = Path("output") / "novel"
NOVEL_SCENE_TEMPLATE_NAME = "codex_novel_scene_select"
SCENE_SELECTION_RETRY_COUNT = 1
DEFAULT_NOVEL_IMAGE_CONCURRENCY = 2
NOVEL_REQUEST_FILE_NAME = "request.md"


@dataclass(frozen=True)
class CodexNovelScene:
    """小说场景抽取结果。"""

    title: str
    source_summary: str
    visual_moment: str
    characters: str
    environment: str
    composition: str
    mood: str
    pic_prompt: str


@dataclass(frozen=True)
class CodexNovelSceneResult:
    """小说单场景图片生成结果。"""

    scene_index: int
    title: str
    scene_prompt_file: Path
    image_output_file: Path | None
    trace_output_file: Path | None
    succeeded: bool
    error_message: str | None


@dataclass(frozen=True)
class CodexNovelResult:
    """小说转图片执行结果。"""

    output_dir: Path
    summary_file: Path
    trace_output_file: Path
    requested_count: int
    selected_count: int
    results: list[CodexNovelSceneResult]

    @property
    def has_failures(self) -> bool:
        """是否存在抽取不足或单图生成失败。"""

        return self.selected_count < self.requested_count or any(not item.succeeded for item in self.results)

    @property
    def success_count(self) -> int:
        """成功生成图片数量。"""

        return sum(1 for item in self.results if item.succeeded)

    @property
    def failure_count(self) -> int:
        """失败场景数量，包含抽取不足缺口。"""

        return (self.requested_count - self.selected_count) + sum(1 for item in self.results if not item.succeeded)


def _require_codex_config(config: CodexConfig) -> None:
    """校验小说场景抽取所需配置。"""

    if not config.base_url.strip():
        raise RuntimeError("codex.base_url 必填且必须是非空字符串")
    if not config.api_key.strip():
        raise RuntimeError("codex.api_key 必填且必须是非空字符串")
    if not config.model.strip():
        raise RuntimeError("codex.model 必填且必须是非空字符串")
    if not config.pic_model.strip():
        raise RuntimeError("codex.pic_model 必填且必须是非空字符串")


def _validate_input_path(input_path: Path) -> None:
    """校验小说输入文件。"""

    if not input_path.exists():
        raise FileNotFoundError(f"小说文件不存在: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"小说路径不是文件: {input_path}")
    if input_path.suffix.lower() not in {".txt", ".md"}:
        raise ValueError(f"novel 输入必须是 txt 或 md 文件: {input_path}")


def _validate_request_path(request_path: Path) -> None:
    """校验场景拆分补充指示文件。"""

    if not request_path.exists():
        raise FileNotFoundError(f"request 文件不存在: {request_path}")
    if not request_path.is_file():
        raise ValueError(f"request 路径不是文件: {request_path}")
    if request_path.suffix.lower() != ".md":
        raise ValueError(f"request 文件必须是 md 文件: {request_path}")


def _resolve_request_path(input_path: Path, request_path: Path | None) -> Path | None:
    """解析可选 request.md 补充指示文件。"""

    if request_path is not None:
        _validate_request_path(request_path)
        return request_path

    candidate = input_path.parent / NOVEL_REQUEST_FILE_NAME
    if not candidate.exists():
        return None
    _validate_request_path(candidate)
    return candidate


def _validate_scene_count(n: int) -> None:
    """校验场景数量。"""

    if n < MIN_NOVEL_SCENE_COUNT or n > MAX_NOVEL_SCENE_COUNT:
        raise ValueError(f"n 必须在 {MIN_NOVEL_SCENE_COUNT} 到 {MAX_NOVEL_SCENE_COUNT} 之间")


def _resolve_novel_output_dir(input_path: Path) -> Path:
    """解析小说任务输出目录。"""

    return NOVEL_OUTPUT_ROOT / f"stem_{input_path.stem}"


def _scene_file_stem(scene_index: int) -> str:
    """生成场景文件名前缀。"""

    return f"scene_{scene_index:03d}"


def _cleanup_managed_outputs(output_dir: Path) -> None:
    """清理本命令管理的输出文件，避免旧结果干扰。"""

    if not output_dir.exists():
        return
    for path in output_dir.iterdir():
        if path.name == "summary.md" or path.name == "novel.trace.log" or path.name.startswith("scene_"):
            if path.is_file():
                path.unlink()


def _write_novel_trace(trace_output_file: Path, payload: dict[str, object]) -> None:
    """写入小说任务总 trace。"""

    trace_output_file.parent.mkdir(parents=True, exist_ok=True)
    trace_output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _scene_to_payload(scene: CodexNovelScene) -> dict[str, str]:
    """将场景对象转换为 trace 字典。"""

    return {
        "title": scene.title,
        "source_summary": scene.source_summary,
        "visual_moment": scene.visual_moment,
        "characters": scene.characters,
        "environment": scene.environment,
        "composition": scene.composition,
        "mood": scene.mood,
        "pic_prompt": scene.pic_prompt,
    }


def _result_to_payload(result: CodexNovelSceneResult) -> dict[str, object]:
    """将单场景结果转换为 trace 字典。"""

    return {
        "scene_index": result.scene_index,
        "title": result.title,
        "scene_prompt_file": str(result.scene_prompt_file),
        "image_output_file": str(result.image_output_file) if result.image_output_file is not None else None,
        "trace_output_file": str(result.trace_output_file) if result.trace_output_file is not None else None,
        "succeeded": result.succeeded,
        "error_message": result.error_message,
    }


def _strip_json_code_fence(text: str) -> str:
    """剥离模型可能返回的 JSON 代码块。"""

    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_scene_items(raw_output: str) -> list[CodexNovelScene]:
    """解析模型返回的场景 JSON。"""

    try:
        parsed: object = json.loads(_strip_json_code_fence(raw_output))
    except json.JSONDecodeError as exc:
        raise ValueError(f"小说场景 JSON 解析失败: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("小说场景 JSON 必须是数组")

    parsed_items = cast(list[object], parsed)
    scenes: list[CodexNovelScene] = []
    for index, item in enumerate(parsed_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个场景不是对象")
        item_mapping = cast(dict[object, object], item)
        scenes.append(_parse_scene_mapping(item_mapping, index))
    if not scenes:
        raise ValueError("小说场景抽取结果为空")
    return scenes


def _parse_scene_mapping(item: dict[object, object], index: int) -> CodexNovelScene:
    """解析单个场景对象。"""

    def get_required(field_name: str) -> str:
        value = item.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"第 {index} 个场景缺少字段: {field_name}")
        return value.strip()

    return CodexNovelScene(
        title=get_required("title"),
        source_summary=get_required("source_summary"),
        visual_moment=get_required("visual_moment"),
        characters=get_required("characters"),
        environment=get_required("environment"),
        composition=get_required("composition"),
        mood=get_required("mood"),
        pic_prompt=get_required("pic_prompt"),
    )


async def _select_novel_scenes_async(
    *,
    text: str,
    n: int,
    source_name: str,
    config: CodexConfig,
) -> list[dict[str, str]]:
    """调用文本模型抽取适合做图的小说场景。"""

    set_tracing_disabled(True)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    model = OpenAIResponsesModel(model=config.model, openai_client=client)
    instructions = get_prompt_manager().render(NOVEL_SCENE_TEMPLATE_NAME, {"n": n, "source_name": source_name})
    agent = Agent(
        name="Codex Novel Scene Selector",
        instructions=instructions,
        model=model,
        tools=[],
    )  # type: ignore[misc]
    result = await Runner.run(agent, input=text)  # type: ignore[misc]
    final_output = cast(object | None, result.final_output)
    if final_output is None:
        raise ValueError("小说场景抽取失败：未返回结果")
    scenes = _parse_scene_items(str(final_output))
    return [_scene_to_payload(scene) for scene in scenes]


def _build_scene_selection_input(source_text: str, request_text: str | None) -> str:
    """构造场景拆分模型输入。"""

    if request_text is None or not request_text.strip():
        return source_text
    return "\n\n".join(
        [
            "## 用户补充指示 request.md",
            request_text.strip(),
            "## 小说正文",
            source_text,
        ]
    )


async def _select_novel_scenes_with_retry_async(
    *,
    text: str,
    n: int,
    source_name: str,
    config: CodexConfig,
    trace_payload: dict[str, object],
    trace_output_file: Path,
) -> list[CodexNovelScene]:
    """抽取场景，JSON 解析失败时重试一次。"""

    errors: list[str] = []
    for attempt in range(SCENE_SELECTION_RETRY_COUNT + 1):
        try:
            raw_scenes = await _select_novel_scenes_async(text=text, n=n, source_name=source_name, config=config)
            scenes = [
                _parse_scene_mapping(cast(dict[object, object], item), index)
                for index, item in enumerate(raw_scenes, 1)
            ]
            trace_payload["scene_select_attempts"] = attempt + 1
            trace_payload["scene_select_errors"] = errors
            return scenes
        except ValueError as exc:
            errors.append(str(exc))
            trace_payload["status"] = "scene_select_retrying" if attempt < SCENE_SELECTION_RETRY_COUNT else "failed"
            trace_payload["scene_select_attempts"] = attempt + 1
            trace_payload["scene_select_errors"] = errors
            _write_novel_trace(trace_output_file, trace_payload)
            if attempt >= SCENE_SELECTION_RETRY_COUNT:
                raise
    raise RuntimeError("不可达的小说场景抽取状态")


def _write_summary(result: CodexNovelResult, scenes: list[CodexNovelScene]) -> None:
    """写入面向人工检查的 summary.md。"""

    lines = [
        "# Codex Novel Summary",
        "",
        f"- 输出目录: {result.output_dir}",
        f"- 请求场景数: {result.requested_count}",
        f"- 抽取场景数: {result.selected_count}",
        f"- 成功: {result.success_count}",
        f"- 失败: {result.failure_count}",
        "",
    ]
    if result.selected_count < result.requested_count:
        lines.extend([f"> 只抽取到 {result.selected_count}/{result.requested_count} 个场景。", ""])

    scene_by_index = dict(enumerate(scenes, start=1))
    for item in result.results:
        scene = scene_by_index.get(item.scene_index)
        lines.extend(
            [
                f"## scene_{item.scene_index:03d}",
                "",
                f"- 标题: {item.title}",
                f"- 状态: {'成功' if item.succeeded else '失败'}",
                f"- Prompt: {item.scene_prompt_file.name}",
                f"- Trace: {item.trace_output_file.name if item.trace_output_file is not None else '无'}",
            ]
        )
        if scene is not None:
            lines.extend(
                [
                    f"- 摘要: {scene.source_summary}",
                    f"- 画面: {scene.visual_moment}",
                    f"- 图片提示词: {scene.pic_prompt}",
                ]
            )
        if item.succeeded and item.image_output_file is not None:
            image_name = item.image_output_file.name
            lines.extend([f"- 图片: {image_name}", "", f"![scene_{item.scene_index:03d}]({image_name})"])
        if not item.succeeded and item.error_message is not None:
            lines.append(f"- 错误: {item.error_message}")
        lines.append("")

    result.summary_file.write_text("\n".join(lines), encoding="utf-8")


async def _run_novel_scene_pic_async(
    *,
    scene_index: int,
    scene: CodexNovelScene,
    scene_prompt_file: Path,
    output_dir: Path,
    size: str | None,
    quality: str | None,
    output_format: str | None,
    semaphore: asyncio.Semaphore,
) -> CodexNovelSceneResult:
    """受限并发生成单个小说场景图片。"""

    scene_stem = _scene_file_stem(scene_index)
    async with semaphore:
        try:
            pic_result = await run_codex_pic_async(
                md_path=scene_prompt_file,
                size=size,
                quality=quality,
                output_format=output_format,
                output_dir=output_dir,
                output_stem=scene_stem,
            )
        except Exception as exc:
            trace_file = output_dir / f"{scene_stem}.trace.log"
            logger.exception("小说单图生成失败: scene=%s", scene_stem)
            return CodexNovelSceneResult(
                scene_index=scene_index,
                title=scene.title,
                scene_prompt_file=scene_prompt_file,
                image_output_file=None,
                trace_output_file=trace_file if trace_file.exists() else None,
                succeeded=False,
                error_message=str(exc),
            )
        return CodexNovelSceneResult(
            scene_index=scene_index,
            title=scene.title,
            scene_prompt_file=scene_prompt_file,
            image_output_file=pic_result.image_output_file,
            trace_output_file=pic_result.trace_output_file,
            succeeded=True,
            error_message=None,
        )


async def run_codex_novel_async(
    *,
    input_path: Path,
    request_path: Path | None = None,
    n: int = 4,
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexNovelResult:
    """执行小说转图片任务。"""

    _validate_input_path(input_path)
    resolved_request_path = _resolve_request_path(input_path, request_path)
    _validate_scene_count(n)
    started_at = time.monotonic()
    config = get_config().codex
    _require_codex_config(config)
    output_dir = _resolve_novel_output_dir(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_managed_outputs(output_dir)
    summary_file = output_dir / "summary.md"
    trace_output_file = output_dir / "novel.trace.log"
    console.print(f"novel 开始: {input_path}，目标场景数: {n}", style="cyan")
    console.print(f"结果目录: {output_dir}", style="cyan")
    source_text = input_path.read_text(encoding="utf-8")[:MAX_NOVEL_INPUT_CHARS]
    request_text = resolved_request_path.read_text(encoding="utf-8") if resolved_request_path is not None else None
    console.print(f"小说已读取: {input_path}（{len(source_text)} 字）", style="cyan")
    scene_selection_input = _build_scene_selection_input(source_text, request_text)
    trace_payload: dict[str, object] = {
        "status": "started",
        "input_path": str(input_path),
        "request_path": str(resolved_request_path) if resolved_request_path is not None else None,
        "requested_count": n,
        "input_chars": len(source_text),
        "request_chars": len(request_text) if request_text is not None else 0,
        "output_dir": str(output_dir),
    }
    _write_novel_trace(trace_output_file, trace_payload)
    logger.info("开始小说转图片: input=%s n=%s output_dir=%s", input_path, n, output_dir)
    if resolved_request_path is not None:
        console.print(f"request 已读取: {resolved_request_path}", style="cyan")
        logger.info("novel request 已读取: request=%s chars=%s", resolved_request_path, len(request_text or ""))

    try:
        console.print(f"开始抽取场景: {n} 个...", style="cyan")
        raw_scenes = await _select_novel_scenes_with_retry_async(
            text=scene_selection_input,
            n=n,
            source_name=input_path.name,
            config=config,
            trace_payload=trace_payload,
            trace_output_file=trace_output_file,
        )
    except ValueError as exc:
        trace_payload["status"] = "scene_select_failed"
        trace_payload["error"] = str(exc)
        trace_payload["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
        _write_novel_trace(trace_output_file, trace_payload)
        logger.exception("小说场景抽取失败: input=%s", input_path)
        raise

    raw_selected_count = len(raw_scenes)
    scenes = raw_scenes[:n]
    trace_payload["raw_selected_count"] = raw_selected_count
    trace_payload["selected_count"] = len(scenes)
    if raw_selected_count > n:
        trace_payload["scene_select_truncated"] = True
    trace_payload["scenes"] = [_scene_to_payload(scene) for scene in scenes]
    _write_novel_trace(trace_output_file, trace_payload)
    console.print(f"场景抽取完成: {len(scenes)}/{n}", style="cyan")
    if len(scenes) < n:
        console.print(f"只抽取到 {len(scenes)}/{n} 个场景，将继续生成已有场景", style="yellow")

    scene_prompt_files: list[Path] = []
    for scene_index, scene in enumerate(scenes, start=1):
        scene_stem = _scene_file_stem(scene_index)
        scene_prompt_file = output_dir / f"{scene_stem}.md"
        scene_prompt_file.write_text(scene.pic_prompt, encoding="utf-8")
        scene_prompt_files.append(scene_prompt_file)
        console.print(f"scene_{scene_index:03d} pic_prompt: {scene.pic_prompt}", style="cyan")
        logger.info("scene_%03d pic_prompt=%s", scene_index, scene.pic_prompt)

    semaphore = asyncio.Semaphore(DEFAULT_NOVEL_IMAGE_CONCURRENCY)
    console.print(
        f"开始生成图片: {len(scenes)} 个场景，并发 {DEFAULT_NOVEL_IMAGE_CONCURRENCY}",
        style="cyan",
    )
    results = await asyncio.gather(
        *[
            _run_novel_scene_pic_async(
                scene_index=scene_index,
                scene=scene,
                scene_prompt_file=scene_prompt_files[scene_index - 1],
                output_dir=output_dir,
                size=size,
                quality=quality,
                output_format=output_format,
                semaphore=semaphore,
            )
            for scene_index, scene in enumerate(scenes, start=1)
        ]
    )
    console.print("图片生成完成，正在写入 summary 和 trace...", style="cyan")
    trace_payload["results"] = [_result_to_payload(item) for item in results]
    _write_novel_trace(trace_output_file, trace_payload)

    novel_result = CodexNovelResult(
        output_dir=output_dir,
        summary_file=summary_file,
        trace_output_file=trace_output_file,
        requested_count=n,
        selected_count=len(scenes),
        results=results,
    )
    _write_summary(novel_result, scenes)
    trace_payload["status"] = "partial_completed" if novel_result.has_failures else "completed"
    trace_payload["summary_file"] = str(summary_file)
    trace_payload["success_count"] = novel_result.success_count
    trace_payload["failure_count"] = novel_result.failure_count
    trace_payload["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
    trace_payload["results"] = [_result_to_payload(item) for item in results]
    _write_novel_trace(trace_output_file, trace_payload)
    logger.info(
        "小说转图片完成: input=%s success=%s failure=%s output_dir=%s",
        input_path,
        novel_result.success_count,
        novel_result.failure_count,
        output_dir,
    )
    console.print(f"novel 完成: 成功 {novel_result.success_count}，失败 {novel_result.failure_count}", style="green")
    return novel_result


def run_codex_novel(
    *,
    input_path: Path,
    request_path: Path | None = None,
    n: int = 4,
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
) -> CodexNovelResult:
    """同步执行小说转图片任务。"""

    return asyncio.run(
        run_codex_novel_async(
            input_path=input_path,
            request_path=request_path,
            n=n,
            size=size,
            quality=quality,
            output_format=output_format,
        )
    )
