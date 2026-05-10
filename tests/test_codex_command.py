"""Codex 命令与核心流程测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from beartools.cli import app
from beartools.codex import _CodexStreamEvent, _normalize_stream_event, run_codex_markdown_async
from beartools.codex_pic import (
    CodexPicBatchItemResult,
    CodexPicBatchResult,
    CodexPicResult,
    _TokenUsage,
    _log_pic_stage,
    _refine_pic_prompt_async,
    run_codex_pic,
    run_codex_picbatch,
    run_codex_picedit,
)
from beartools.config import CodexConfig, Config

runner = CliRunner()


@dataclass
class _FakeStreamRunResult:
    """最小化 streamed 结果替身。"""

    events_factory: Callable[[], AsyncIterator[object]]
    final_output: object | None = None

    def stream_events(self) -> AsyncIterator[object]:
        return self.events_factory()


def _build_fake_config(output_dir: Path) -> Config:
    """构造测试使用的最小 Codex 配置。"""

    return Config(
        codex=CodexConfig(
            base_url="https://example.com/v1",
            api_key="token",
            model="demo-model",
            pic_model="demo-pic-model",
            output_dir=output_dir,
        )
    )


def test_codex_config_pic_defaults() -> None:
    config = CodexConfig()

    assert config.pic_size == "1024x1024"
    assert config.pic_quality == "high"


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: Config,
    stream: _FakeStreamRunResult,
) -> None:
    """替换运行时依赖，避免触发真实 SDK。"""

    class FakeRunner:
        @staticmethod
        def run_streamed(agent: object, input: str) -> _FakeStreamRunResult:
            del agent, input
            return stream

    class FakeModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    class FakeAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    monkeypatch.setattr("beartools.codex.get_config", lambda: config)
    monkeypatch.setattr("beartools.codex.Runner", FakeRunner)
    monkeypatch.setattr("beartools.codex.OpenAIResponsesModel", FakeModel)
    monkeypatch.setattr("beartools.codex.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex.Agent", FakeAgent)
    monkeypatch.setattr("beartools.codex.set_tracing_disabled", lambda _value: None)
    monkeypatch.setattr("beartools.codex._normalize_stream_event", lambda event: event)


def test_codex_run_missing_markdown_file_exits_with_error(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.md"

    result = runner.invoke(app, ["codex", "run", str(missing_file)])

    assert result.exit_code == 1
    assert "错误:" in result.stdout
    assert "不存在" in result.stdout


def test_codex_run_prints_final_and_trace_paths(tmp_path: Path) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("hello", encoding="utf-8")
    output_dir = tmp_path / "codex-output"

    from beartools.codex import CodexRunResult

    def fake_run_codex_markdown(*, md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
        assert md_path == md_file
        assert output_file is None
        assert trace_file is None
        final_file = output_dir / "prompt.codex.md"
        trace_out = output_dir / "prompt.codex.trace.log"
        final_file.parent.mkdir(parents=True, exist_ok=True)
        final_file.write_text("最终回答", encoding="utf-8")
        trace_out.write_text("trace", encoding="utf-8")
        return CodexRunResult(final_output_file=final_file, trace_output_file=trace_out, final_text="最终回答")

    with patch("beartools.commands.codex.command.run_codex_markdown", side_effect=fake_run_codex_markdown):
        result = runner.invoke(app, ["codex", "run", str(md_file)])

    assert result.exit_code == 0
    assert "prompt.codex.md" in result.stdout
    assert "prompt.codex.trace.log" in result.stdout


def test_codex_pic_prints_output_dir(tmp_path: Path) -> None:
    md_file = tmp_path / "input" / "codex" / "cover.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成图片", encoding="utf-8")

    def fake_run_codex_pic(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        assert md_path == md_file
        assert size is None
        assert quality is None
        assert output_format is None
        output_dir = Path("output") / "pic" / "cover"
        return CodexPicResult(
            output_dir=output_dir,
            image_output_file=output_dir / "cover.png",
            trace_output_file=output_dir / "cover.trace.log",
        )

    with patch("beartools.commands.codex.command.run_codex_pic", side_effect=fake_run_codex_pic):
        result = runner.invoke(app, ["codex", "pic", str(md_file)])

    assert result.exit_code == 0
    assert "结果目录: output/pic/cover" in result.stdout
    assert "图片已写入: output/pic/cover/cover.png" in result.stdout
    assert "Trace 已写入: output/pic/cover/cover.trace.log" in result.stdout


def test_codex_pic_passes_cli_options(tmp_path: Path) -> None:
    md_file = tmp_path / "input" / "codex" / "poster.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成海报", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run_codex_pic(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        captured["md_path"] = md_path
        captured["size"] = size
        captured["quality"] = quality
        captured["output_format"] = output_format
        output_dir = Path("output") / "pic" / "poster"
        return CodexPicResult(
            output_dir=output_dir,
            image_output_file=output_dir / "poster.webp",
            trace_output_file=output_dir / "poster.trace.log",
        )

    with patch("beartools.commands.codex.command.run_codex_pic", side_effect=fake_run_codex_pic):
        result = runner.invoke(
            app,
            [
                "codex",
                "pic",
                str(md_file),
                "--size",
                "1536x1024",
                "--quality",
                "medium",
                "--output-format",
                "webp",
            ],
        )

    assert result.exit_code == 0
    assert captured == {
        "md_path": md_file,
        "size": "1536x1024",
        "quality": "medium",
        "output_format": "webp",
    }


def test_codex_pic_plays_system_notification_sound_after_success(tmp_path: Path) -> None:
    md_file = tmp_path / "input" / "codex" / "cover.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成图片", encoding="utf-8")

    def fake_run_codex_pic(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        assert md_path == md_file
        assert size is None
        assert quality is None
        assert output_format is None
        output_dir = Path("output") / "pic" / "cover"
        return CodexPicResult(
            output_dir=output_dir,
            image_output_file=output_dir / "cover.png",
            trace_output_file=output_dir / "cover.trace.log",
        )

    with (
        patch("beartools.commands.codex.command.run_codex_pic", side_effect=fake_run_codex_pic),
        patch("beartools.commands.codex.command.play_system_notification_sound") as mock_play_system_notification_sound,
    ):
        result = runner.invoke(app, ["codex", "pic", str(md_file)])

    assert result.exit_code == 0
    mock_play_system_notification_sound.assert_called_once_with()


def test_codex_picbatch_prints_mixed_results_and_keeps_exit_zero(tmp_path: Path) -> None:
    first_file = tmp_path / "first.md"
    second_file = tmp_path / "second.md"
    first_file.write_text("生成第一张图", encoding="utf-8")
    second_file.write_text("生成第二张图", encoding="utf-8")

    def fake_run_codex_picbatch(
        *,
        md_paths: list[Path],
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicBatchResult:
        assert md_paths == [first_file, second_file]
        assert size is None
        assert quality is None
        assert output_format is None
        return CodexPicBatchResult(
            results=[
                CodexPicBatchItemResult(
                    md_path=first_file,
                    succeeded=True,
                    image_output_file=Path("output") / "pic" / "first" / "first.png",
                    trace_output_file=Path("output") / "pic" / "first" / "first.trace.log",
                    error_message=None,
                ),
                CodexPicBatchItemResult(
                    md_path=second_file,
                    succeeded=False,
                    image_output_file=None,
                    trace_output_file=Path("output") / "pic" / "second" / "second.trace.log",
                    error_message="refine boom",
                ),
            ]
        )

    with patch("beartools.commands.codex.command.run_codex_picbatch", side_effect=fake_run_codex_picbatch):
        result = runner.invoke(app, ["codex", "picbatch", f"{first_file},{second_file}"])

    assert result.exit_code == 0
    assert f"[成功] {first_file}" in result.stdout
    assert "first.png" in result.stdout
    assert f"[失败] {second_file}" in result.stdout
    assert "refine boom" in result.stdout


def test_codex_picbatch_plays_system_notification_sound_once_after_completion(tmp_path: Path) -> None:
    first_file = tmp_path / "first.md"
    second_file = tmp_path / "second.md"
    first_file.write_text("生成第一张图", encoding="utf-8")
    second_file.write_text("生成第二张图", encoding="utf-8")

    def fake_run_codex_picbatch(
        *,
        md_paths: list[Path],
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicBatchResult:
        assert md_paths == [first_file, second_file]
        assert size is None
        assert quality is None
        assert output_format is None
        return CodexPicBatchResult(
            results=[
                CodexPicBatchItemResult(
                    md_path=first_file,
                    succeeded=True,
                    image_output_file=Path("output") / "pic" / "first" / "first.png",
                    trace_output_file=Path("output") / "pic" / "first" / "first.trace.log",
                    error_message=None,
                ),
                CodexPicBatchItemResult(
                    md_path=second_file,
                    succeeded=False,
                    image_output_file=None,
                    trace_output_file=Path("output") / "pic" / "second" / "second.trace.log",
                    error_message="refine boom",
                ),
            ]
        )

    with (
        patch("beartools.commands.codex.command.run_codex_picbatch", side_effect=fake_run_codex_picbatch),
        patch("beartools.commands.codex.command.play_system_notification_sound") as mock_play_system_notification_sound,
    ):
        result = runner.invoke(app, ["codex", "picbatch", f"{first_file},{second_file}"])

    assert result.exit_code == 0
    mock_play_system_notification_sound.assert_called_once_with()


def test_codex_picbatch_passes_cli_options(tmp_path: Path) -> None:
    first_file = tmp_path / "first.md"
    second_file = tmp_path / "second.md"
    first_file.write_text("生成第一张图", encoding="utf-8")
    second_file.write_text("生成第二张图", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_codex_picbatch(
        *,
        md_paths: list[Path],
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicBatchResult:
        captured["md_paths"] = md_paths
        captured["size"] = size
        captured["quality"] = quality
        captured["output_format"] = output_format
        return CodexPicBatchResult(results=[])

    with patch("beartools.commands.codex.command.run_codex_picbatch", side_effect=fake_run_codex_picbatch):
        result = runner.invoke(
            app,
            [
                "codex",
                "picbatch",
                f"{first_file},{second_file}",
                "--size",
                "1536x1024",
                "--quality",
                "medium",
                "--output-format",
                "webp",
            ],
        )

    assert result.exit_code == 0
    assert captured == {
        "md_paths": [first_file, second_file],
        "size": "1536x1024",
        "quality": "medium",
        "output_format": "webp",
    }


def test_codex_picedit_prints_output_dir(tmp_path: Path) -> None:
    image_file = tmp_path / "avatar.png"
    image_file.write_bytes(b"image")

    def fake_run_codex_picedit(
        *,
        image_path: Path,
        prompt: str,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        assert image_path == image_file
        assert prompt == "提亮并增强科技感"
        assert size is None
        assert quality is None
        assert output_format is None
        output_dir = image_file.parent
        return CodexPicResult(
            output_dir=output_dir,
            image_output_file=output_dir / "avatar_version_001.png",
            trace_output_file=output_dir / "avatar_version_001.trace.log",
        )

    with patch("beartools.commands.codex.command.run_codex_picedit", side_effect=fake_run_codex_picedit):
        result = runner.invoke(app, ["codex", "picedit", str(image_file), "提亮并增强科技感"])

    assert result.exit_code == 0
    normalized_stdout = result.stdout.replace("\n", "")
    assert f"结果目录: {image_file.parent}" in normalized_stdout
    assert f"图片已写入: {image_file.parent / 'avatar_version_001.png'}" in normalized_stdout
    assert f"Trace 已写入: {image_file.parent / 'avatar_version_001.trace.log'}" in normalized_stdout


def test_codex_picedit_plays_system_notification_sound_after_success(tmp_path: Path) -> None:
    image_file = tmp_path / "avatar.png"
    image_file.write_bytes(b"image")

    def fake_run_codex_picedit(
        *,
        image_path: Path,
        prompt: str,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        assert image_path == image_file
        assert prompt == "提亮并增强科技感"
        assert size is None
        assert quality is None
        assert output_format is None
        output_dir = image_file.parent
        return CodexPicResult(
            output_dir=output_dir,
            image_output_file=output_dir / "avatar_version_001.png",
            trace_output_file=output_dir / "avatar_version_001.trace.log",
        )

    with (
        patch("beartools.commands.codex.command.run_codex_picedit", side_effect=fake_run_codex_picedit),
        patch("beartools.commands.codex.command.play_system_notification_sound") as mock_play_system_notification_sound,
    ):
        result = runner.invoke(app, ["codex", "picedit", str(image_file), "提亮并增强科技感"])

    assert result.exit_code == 0
    mock_play_system_notification_sound.assert_called_once_with()


def test_codex_novel_passes_default_options_and_prints_summary(tmp_path: Path) -> None:
    novel_file = tmp_path / "input" / "novel1.md"
    novel_file.parent.mkdir(parents=True)
    novel_file.write_text("小说内容", encoding="utf-8")

    from beartools.codex_novel import CodexNovelResult, CodexNovelSceneResult

    def fake_run_codex_novel(
        *,
        input_path: Path,
        n: int = 4,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexNovelResult:
        assert input_path == novel_file
        assert n == 4
        assert size is None
        assert quality is None
        assert output_format is None
        output_dir = Path("output") / "novel" / "stem_novel1"
        return CodexNovelResult(
            output_dir=output_dir,
            summary_file=output_dir / "summary.md",
            trace_output_file=output_dir / "novel.trace.log",
            requested_count=4,
            selected_count=4,
            results=[
                CodexNovelSceneResult(
                    scene_index=index,
                    title=f"场景{index}",
                    scene_prompt_file=output_dir / f"scene_{index:03d}.md",
                    image_output_file=output_dir / f"scene_{index:03d}.png",
                    trace_output_file=output_dir / f"scene_{index:03d}.trace.log",
                    succeeded=True,
                    error_message=None,
                )
                for index in range(1, 5)
            ],
        )

    with (
        patch("beartools.commands.codex.command.run_codex_novel", side_effect=fake_run_codex_novel),
        patch("beartools.commands.codex.command.play_system_notification_sound") as mock_play_system_notification_sound,
    ):
        result = runner.invoke(app, ["codex", "novel", str(novel_file)])

    assert result.exit_code == 0
    assert "结果目录: output/novel/stem_novel1" in result.stdout
    assert "Summary 已写入: output/novel/stem_novel1/summary.md" in result.stdout
    assert "成功: 4" in result.stdout
    assert "失败: 0" in result.stdout
    assert "scene_001.png" in result.stdout
    mock_play_system_notification_sound.assert_called_once_with()


def test_codex_novel_passes_cli_options(tmp_path: Path) -> None:
    novel_file = tmp_path / "input" / "novel2.txt"
    novel_file.parent.mkdir(parents=True)
    novel_file.write_text("小说内容", encoding="utf-8")
    captured: dict[str, object] = {}

    from beartools.codex_novel import CodexNovelResult

    def fake_run_codex_novel(
        *,
        input_path: Path,
        n: int = 4,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexNovelResult:
        captured["input_path"] = input_path
        captured["n"] = n
        captured["size"] = size
        captured["quality"] = quality
        captured["output_format"] = output_format
        output_dir = Path("output") / "novel" / "stem_novel2"
        return CodexNovelResult(
            output_dir=output_dir,
            summary_file=output_dir / "summary.md",
            trace_output_file=output_dir / "novel.trace.log",
            requested_count=n,
            selected_count=n,
            results=[],
        )

    with patch("beartools.commands.codex.command.run_codex_novel", side_effect=fake_run_codex_novel):
        result = runner.invoke(
            app,
            [
                "codex",
                "novel",
                str(novel_file),
                "--n",
                "2",
                "--size",
                "1536x1024",
                "--quality",
                "medium",
                "--output-format",
                "webp",
            ],
        )

    assert result.exit_code == 0
    assert captured == {
        "input_path": novel_file,
        "n": 2,
        "size": "1536x1024",
        "quality": "medium",
        "output_format": "webp",
    }


def test_codex_novel_exits_one_when_partial_failure(tmp_path: Path) -> None:
    novel_file = tmp_path / "input" / "novel1.md"
    novel_file.parent.mkdir(parents=True)
    novel_file.write_text("小说内容", encoding="utf-8")

    from beartools.codex_novel import CodexNovelResult, CodexNovelSceneResult

    def fake_run_codex_novel(
        *,
        input_path: Path,
        n: int = 4,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexNovelResult:
        del input_path, n, size, quality, output_format
        output_dir = Path("output") / "novel" / "stem_novel1"
        return CodexNovelResult(
            output_dir=output_dir,
            summary_file=output_dir / "summary.md",
            trace_output_file=output_dir / "novel.trace.log",
            requested_count=2,
            selected_count=2,
            results=[
                CodexNovelSceneResult(
                    scene_index=1,
                    title="场景一",
                    scene_prompt_file=output_dir / "scene_001.md",
                    image_output_file=output_dir / "scene_001.png",
                    trace_output_file=output_dir / "scene_001.trace.log",
                    succeeded=True,
                    error_message=None,
                ),
                CodexNovelSceneResult(
                    scene_index=2,
                    title="场景二",
                    scene_prompt_file=output_dir / "scene_002.md",
                    image_output_file=None,
                    trace_output_file=output_dir / "scene_002.trace.log",
                    succeeded=False,
                    error_message="image boom",
                ),
            ],
        )

    with patch("beartools.commands.codex.command.run_codex_novel", side_effect=fake_run_codex_novel):
        result = runner.invoke(app, ["codex", "novel", str(novel_file), "--n", "2"])

    assert result.exit_code == 1
    assert "成功: 1" in result.stdout
    assert "失败: 1" in result.stdout
    assert "image boom" in result.stdout


@pytest.mark.parametrize(
    ("file_name", "args", "message"),
    [
        ("story.epub", [], "txt 或 md"),
        ("story.md", ["--n", "0"], "n"),
        ("story.md", ["--n", "13"], "n"),
    ],
)
def test_codex_novel_rejects_invalid_input_and_n(tmp_path: Path, file_name: str, args: list[str], message: str) -> None:
    novel_file = tmp_path / file_name
    novel_file.write_text("小说内容", encoding="utf-8")

    result = runner.invoke(app, ["codex", "novel", str(novel_file), *args])

    assert result.exit_code == 1
    assert "错误:" in result.stdout
    assert message in result.stdout


def test_run_codex_novel_writes_prompts_summary_and_uses_novel_output_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from beartools.codex_novel import run_codex_novel

    monkeypatch.chdir(tmp_path)
    caplog.set_level("INFO")
    input_file = tmp_path / "input" / "long.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("甲" * 30005, encoding="utf-8")
    captured: dict[str, object] = {}

    async def fake_select_novel_scenes_async(
        *, text: str, n: int, source_name: str, config: CodexConfig
    ) -> list[dict[str, str]]:
        captured["text"] = text
        captured["n"] = n
        captured["source_name"] = source_name
        captured["model"] = config.model
        return [
            {
                "title": "场景一",
                "source_summary": "摘要一",
                "visual_moment": "瞬间一",
                "characters": "人物一",
                "environment": "环境一",
                "composition": "构图一",
                "mood": "氛围一",
                "pic_prompt": "只写图片提示词一",
            },
            {
                "title": "场景二",
                "source_summary": "摘要二",
                "visual_moment": "瞬间二",
                "characters": "人物二",
                "environment": "环境二",
                "composition": "构图二",
                "mood": "氛围二",
                "pic_prompt": "只写图片提示词二",
            },
        ]

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
        output_dir: Path | None = None,
        output_stem: str | None = None,
    ) -> CodexPicResult:
        assert size == "1536x1024"
        assert quality == "medium"
        assert output_format == "webp"
        assert output_dir == Path("output") / "novel" / "stem_long"
        assert output_stem in {"scene_001", "scene_002"}
        assert md_path.parent == output_dir
        assert md_path.read_text(encoding="utf-8") in {"只写图片提示词一", "只写图片提示词二"}
        image_file = output_dir / f"{output_stem}.webp"
        trace_file = output_dir / f"{output_stem}.trace.log"
        image_file.write_bytes(b"image")
        trace_file.write_text("trace", encoding="utf-8")
        return CodexPicResult(output_dir=output_dir, image_output_file=image_file, trace_output_file=trace_file)

    monkeypatch.setattr("beartools.codex_novel._select_novel_scenes_async", fake_select_novel_scenes_async)
    monkeypatch.setattr("beartools.codex_novel.run_codex_pic_async", fake_run_codex_pic_async)
    monkeypatch.setattr(
        "beartools.codex_novel.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    result = run_codex_novel(
        input_path=input_file,
        n=2,
        size="1536x1024",
        quality="medium",
        output_format="webp",
    )

    assert captured["text"] == "甲" * 30000
    assert captured["n"] == 2
    assert captured["source_name"] == "long.md"
    assert captured["model"] == "grok-3-mini"
    captured_output = capsys.readouterr().out
    assert "scene_001 pic_prompt: 只写图片提示词一" in captured_output
    assert "scene_002 pic_prompt: 只写图片提示词二" in captured_output
    assert "scene_001 pic_prompt=只写图片提示词一" in caplog.text
    assert "scene_002 pic_prompt=只写图片提示词二" in caplog.text
    assert result.output_dir == Path("output") / "novel" / "stem_long"
    assert result.requested_count == 2
    assert result.selected_count == 2
    assert [item.succeeded for item in result.results] == [True, True]
    assert (result.output_dir / "scene_001.md").read_text(encoding="utf-8") == "只写图片提示词一"
    assert "source_summary" not in (result.output_dir / "scene_001.md").read_text(encoding="utf-8")
    summary_text = (result.output_dir / "summary.md").read_text(encoding="utf-8")
    assert "![scene_001](scene_001.webp)" in summary_text
    assert "scene_001.md" in summary_text
    assert "scene_001.trace.log" in summary_text
    assert "只写图片提示词一" in summary_text


def test_run_codex_novel_limits_image_generation_concurrency_to_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beartools.codex_novel import run_codex_novel

    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / "input" / "novel.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("小说内容", encoding="utf-8")
    active_count = 0
    max_active_count = 0
    counter_lock = asyncio.Lock()

    async def fake_select_novel_scenes_async(
        *, text: str, n: int, source_name: str, config: CodexConfig
    ) -> list[dict[str, str]]:
        del text, source_name, config
        return [
            {
                "title": f"场景{index}",
                "source_summary": "摘要",
                "visual_moment": "瞬间",
                "characters": "人物",
                "environment": "环境",
                "composition": "构图",
                "mood": "氛围",
                "pic_prompt": f"图片提示词{index}",
            }
            for index in range(1, n + 1)
        ]

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
        output_dir: Path | None = None,
        output_stem: str | None = None,
    ) -> CodexPicResult:
        del md_path, size, quality, output_format
        assert output_dir is not None
        assert output_stem is not None
        nonlocal active_count, max_active_count
        async with counter_lock:
            active_count += 1
            if active_count > max_active_count:
                max_active_count = active_count
        await asyncio.sleep(0.05)
        async with counter_lock:
            active_count -= 1
        image_file = output_dir / f"{output_stem}.png"
        trace_file = output_dir / f"{output_stem}.trace.log"
        image_file.write_bytes(b"image")
        trace_file.write_text("trace", encoding="utf-8")
        return CodexPicResult(output_dir=output_dir, image_output_file=image_file, trace_output_file=trace_file)

    monkeypatch.setattr("beartools.codex_novel._select_novel_scenes_async", fake_select_novel_scenes_async)
    monkeypatch.setattr("beartools.codex_novel.run_codex_pic_async", fake_run_codex_pic_async)
    monkeypatch.setattr(
        "beartools.codex_novel.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    result = run_codex_novel(input_path=input_file, n=4)

    assert len(result.results) == 4
    assert max_active_count == 2


def test_run_codex_novel_retries_scene_selection_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from beartools.codex_novel import run_codex_novel

    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / "input" / "novel.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("小说内容", encoding="utf-8")
    call_count = 0

    async def fake_select_novel_scenes_async(
        *, text: str, n: int, source_name: str, config: CodexConfig
    ) -> list[dict[str, str]]:
        del text, n, source_name, config
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("JSON 解析失败")
        return [
            {
                "title": "场景一",
                "source_summary": "摘要一",
                "visual_moment": "瞬间一",
                "characters": "人物一",
                "environment": "环境一",
                "composition": "构图一",
                "mood": "氛围一",
                "pic_prompt": "只写图片提示词一",
            }
        ]

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
        output_dir: Path | None = None,
        output_stem: str | None = None,
    ) -> CodexPicResult:
        del md_path, size, quality, output_format
        assert output_dir is not None
        assert output_stem is not None
        image_file = output_dir / f"{output_stem}.png"
        trace_file = output_dir / f"{output_stem}.trace.log"
        image_file.write_bytes(b"image")
        trace_file.write_text("trace", encoding="utf-8")
        return CodexPicResult(output_dir=output_dir, image_output_file=image_file, trace_output_file=trace_file)

    monkeypatch.setattr("beartools.codex_novel._select_novel_scenes_async", fake_select_novel_scenes_async)
    monkeypatch.setattr("beartools.codex_novel.run_codex_pic_async", fake_run_codex_pic_async)
    monkeypatch.setattr(
        "beartools.codex_novel.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    result = run_codex_novel(input_path=input_file, n=1)

    assert call_count == 2
    assert result.results[0].succeeded is True
    assert "JSON 解析失败" in result.trace_output_file.read_text(encoding="utf-8")


def test_run_codex_novel_allows_fewer_scenes_and_exits_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from beartools.codex_novel import run_codex_novel

    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / "input" / "short.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("小说内容", encoding="utf-8")

    async def fake_select_novel_scenes_async(
        *, text: str, n: int, source_name: str, config: CodexConfig
    ) -> list[dict[str, str]]:
        del text, n, source_name, config
        return [
            {
                "title": "唯一场景",
                "source_summary": "摘要",
                "visual_moment": "瞬间",
                "characters": "人物",
                "environment": "环境",
                "composition": "构图",
                "mood": "氛围",
                "pic_prompt": "唯一图片提示词",
            }
        ]

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
        output_dir: Path | None = None,
        output_stem: str | None = None,
    ) -> CodexPicResult:
        del md_path, size, quality, output_format
        assert output_dir is not None
        assert output_stem == "scene_001"
        image_file = output_dir / "scene_001.png"
        trace_file = output_dir / "scene_001.trace.log"
        image_file.write_bytes(b"image")
        trace_file.write_text("trace", encoding="utf-8")
        return CodexPicResult(output_dir=output_dir, image_output_file=image_file, trace_output_file=trace_file)

    monkeypatch.setattr("beartools.codex_novel._select_novel_scenes_async", fake_select_novel_scenes_async)
    monkeypatch.setattr("beartools.codex_novel.run_codex_pic_async", fake_run_codex_pic_async)
    monkeypatch.setattr(
        "beartools.codex_novel.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    result = run_codex_novel(input_path=input_file, n=2)

    assert result.requested_count == 2
    assert result.selected_count == 1
    assert result.has_failures is True
    assert len(result.results) == 1
    assert "只抽取到 1/2 个场景" in result.summary_file.read_text(encoding="utf-8")


def test_run_codex_novel_truncates_extra_scenes_to_requested_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beartools.codex_novel import run_codex_novel

    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / "input" / "novel.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("小说内容", encoding="utf-8")
    generated_stems: list[str] = []

    async def fake_select_novel_scenes_async(
        *, text: str, n: int, source_name: str, config: CodexConfig
    ) -> list[dict[str, str]]:
        del text, n, source_name, config
        return [
            {
                "title": f"场景{index}",
                "source_summary": "摘要",
                "visual_moment": "瞬间",
                "characters": "人物",
                "environment": "环境",
                "composition": "构图",
                "mood": "氛围",
                "pic_prompt": f"图片提示词{index}",
            }
            for index in range(1, 5)
        ]

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
        output_dir: Path | None = None,
        output_stem: str | None = None,
    ) -> CodexPicResult:
        del md_path, size, quality, output_format
        assert output_dir is not None
        assert output_stem is not None
        generated_stems.append(output_stem)
        image_file = output_dir / f"{output_stem}.png"
        trace_file = output_dir / f"{output_stem}.trace.log"
        image_file.write_bytes(b"image")
        trace_file.write_text("trace", encoding="utf-8")
        return CodexPicResult(output_dir=output_dir, image_output_file=image_file, trace_output_file=trace_file)

    monkeypatch.setattr("beartools.codex_novel._select_novel_scenes_async", fake_select_novel_scenes_async)
    monkeypatch.setattr("beartools.codex_novel.run_codex_pic_async", fake_run_codex_pic_async)
    monkeypatch.setattr(
        "beartools.codex_novel.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    result = run_codex_novel(input_path=input_file, n=2)

    assert result.requested_count == 2
    assert result.selected_count == 2
    assert result.failure_count == 0
    assert generated_stems == ["scene_001", "scene_002"]
    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"raw_selected_count": 4' in trace_text
    assert '"selected_count": 2' in trace_text


def test_run_codex_novel_generates_best_effort_after_image_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beartools.codex_novel import run_codex_novel

    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / "input" / "novel.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("小说内容", encoding="utf-8")

    async def fake_select_novel_scenes_async(
        *, text: str, n: int, source_name: str, config: CodexConfig
    ) -> list[dict[str, str]]:
        del text, n, source_name, config
        return [
            {
                "title": "失败场景",
                "source_summary": "摘要一",
                "visual_moment": "瞬间一",
                "characters": "人物一",
                "environment": "环境一",
                "composition": "构图一",
                "mood": "氛围一",
                "pic_prompt": "失败图片提示词",
            },
            {
                "title": "成功场景",
                "source_summary": "摘要二",
                "visual_moment": "瞬间二",
                "characters": "人物二",
                "environment": "环境二",
                "composition": "构图二",
                "mood": "氛围二",
                "pic_prompt": "成功图片提示词",
            },
        ]

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
        output_dir: Path | None = None,
        output_stem: str | None = None,
    ) -> CodexPicResult:
        del md_path, size, quality, output_format
        assert output_dir is not None
        assert output_stem is not None
        trace_file = output_dir / f"{output_stem}.trace.log"
        if output_stem == "scene_001":
            trace_file.write_text("failed trace", encoding="utf-8")
            raise RuntimeError("image boom")
        image_file = output_dir / f"{output_stem}.png"
        image_file.write_bytes(b"image")
        trace_file.write_text("trace", encoding="utf-8")
        return CodexPicResult(output_dir=output_dir, image_output_file=image_file, trace_output_file=trace_file)

    monkeypatch.setattr("beartools.codex_novel._select_novel_scenes_async", fake_select_novel_scenes_async)
    monkeypatch.setattr("beartools.codex_novel.run_codex_pic_async", fake_run_codex_pic_async)
    monkeypatch.setattr(
        "beartools.codex_novel.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    result = run_codex_novel(input_path=input_file, n=2)

    assert [item.succeeded for item in result.results] == [False, True]
    assert result.has_failures is True
    assert result.results[0].error_message == "image boom"
    assert result.results[1].image_output_file == Path("output") / "novel" / "stem_novel" / "scene_002.png"
    summary_text = result.summary_file.read_text(encoding="utf-8")
    assert "image boom" in summary_text
    assert "![scene_001]" not in summary_text
    assert "![scene_002](scene_002.png)" in summary_text


def test_run_codex_picedit_uses_incrementing_output_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image_file = tmp_path / "avatar.png"
    image_file.write_bytes(b"source-image")
    monkeypatch.chdir(tmp_path)

    captured: dict[str, object] = {}

    async def fake_refine_picedit_prompt_async(prompt: str, config: CodexConfig) -> str:
        captured["refine_prompt"] = prompt
        captured["refine_model"] = config.model
        return "保留人物主体，提亮光线并增加悬浮面板"

    class FakeImages:
        async def edit(self, **kwargs: object) -> object:
            captured["kwargs"] = kwargs
            image_handle = kwargs["image"]
            captured["image_name"] = getattr(image_handle, "name", "")
            return type(
                "FakeImageResponse",
                (),
                {
                    "data": [type("FakeImageData", (), {"b64_json": "aGVsbG8="})()],
                    "usage": {"input_tokens": 7, "output_tokens": 8, "total_tokens": 15},
                    "__str__": lambda _self: "image-edit-response",
                },
            )()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["client_timeout"] = timeout
            self.images = FakeImages()

        def with_options(self, *, timeout: float) -> FakeClient:
            captured["request_timeout"] = timeout
            return self

    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic._refine_picedit_prompt_async", fake_refine_picedit_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
                pic_size="1024x1024",
                pic_quality="high",
                pic_output_format="png",
                pic_response_format="b64_json",
            )
        ),
    )

    existing_output = image_file.parent / "avatar_version_001.png"
    existing_output.parent.mkdir(parents=True, exist_ok=True)
    existing_output.write_bytes(b"old")

    result = run_codex_picedit(image_path=image_file, prompt="提亮并增强科技感")

    assert captured["api_key"] == "token"
    assert captured["base_url"] == "https://example.com/v1"
    assert captured["client_timeout"] == 600.0
    assert captured["request_timeout"] == 600.0
    assert captured["refine_prompt"] == "提亮并增强科技感"
    assert captured["refine_model"] == "grok-3-mini"
    assert captured["image_name"] == str(image_file)
    image_kwargs = captured["kwargs"]
    assert isinstance(image_kwargs, dict)
    image_kwargs_mapping = cast(dict[str, object], image_kwargs)
    image_value = image_kwargs_mapping.get("image")
    assert image_kwargs_mapping == {
        "model": "gpt-image-2",
        "image": image_value,
        "prompt": "保留人物主体，提亮光线并增加悬浮面板",
        "size": "1024x1024",
        "quality": "high",
        "output_format": "png",
        "response_format": "b64_json",
    }
    assert result.output_dir == image_file.parent
    assert result.image_output_file == image_file.parent / "avatar_version_002.png"
    assert result.image_output_file.read_bytes() == b"hello"
    assert result.trace_output_file == image_file.parent / "avatar_version_002.trace.log"
    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"status": "completed"' in trace_text
    assert '"source_image":' in trace_text
    assert '"original_prompt": "提亮并增强科技感"' in trace_text
    assert '"refined_prompt": "保留人物主体，提亮光线并增加悬浮面板"' in trace_text
    assert '"refine_token_usage": {' in trace_text
    assert '"image_token_usage": {' in trace_text
    assert '"input_tokens": 7' in trace_text
    assert '"output_tokens": 8' in trace_text
    assert '"total_tokens": 15' in trace_text
    assert '"image_request_elapsed_seconds":' in trace_text
    assert '"image_decode_elapsed_seconds":' in trace_text
    assert '"image_write_elapsed_seconds":' in trace_text
    assert '"total_elapsed_seconds":' in trace_text
    assert '"image_response": "image-edit-response"' in trace_text


def test_run_codex_picedit_excludes_b64_payload_from_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image_file = tmp_path / "avatar.png"
    image_file.write_bytes(b"source-image")
    monkeypatch.chdir(tmp_path)

    async def fake_refine_picedit_prompt_async(prompt: str, config: CodexConfig) -> str:
        del config
        assert prompt == "提亮并增强科技感"
        return "保留人物主体，提亮光线并增加悬浮面板"

    class FakeImages:
        async def edit(self, **kwargs: object) -> object:
            del kwargs
            return type(
                "FakeImageResponse",
                (),
                {
                    "data": [type("FakeImageData", (), {"b64_json": "aGVsbG8=", "revised_prompt": "增强层次"})()],
                    "usage": {"input_tokens": 7, "output_tokens": 8, "total_tokens": 15},
                    "model_dump": lambda _self: {
                        "data": [{"b64_json": "HUGE_BASE64_EDIT", "revised_prompt": "增强层次"}],
                        "meta": {"source": "edit"},
                    },
                    "__str__": lambda _self: "should-not-appear",
                },
            )()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float | None = None) -> None:
            del api_key, base_url, timeout
            self.images = FakeImages()

        def with_options(self, *, timeout: float) -> FakeClient:
            del timeout
            return self

    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic._refine_picedit_prompt_async", fake_refine_picedit_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
                pic_size="1024x1024",
                pic_quality="high",
                pic_output_format="png",
                pic_response_format="b64_json",
            )
        ),
    )

    result = run_codex_picedit(image_path=image_file, prompt="提亮并增强科技感")

    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"image_response": {' in trace_text
    assert '"meta": {' in trace_text
    assert '"source": "edit"' in trace_text
    assert '"revised_prompt": "增强层次"' in trace_text
    assert "HUGE_BASE64_EDIT" not in trace_text
    assert '"image_response": "should-not-appear"' not in trace_text
    assert "should-not-appear" not in trace_text


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"size": "1792x1024"}, "图片编辑暂不支持该尺寸"),
        ({"quality": "hd"}, "图片编辑暂不支持该质量"),
        ({"output_format": "gif"}, "输出格式"),
    ],
)
def test_run_codex_picedit_rejects_invalid_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    message: str,
) -> None:
    image_file = tmp_path / "avatar.png"
    image_file.write_bytes(b"source-image")

    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    with pytest.raises(ValueError, match=message):
        run_codex_picedit(image_path=image_file, prompt="提亮并增强科技感", **kwargs)


def test_run_codex_picedit_strips_existing_version_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image_file = tmp_path / "p2_version_001.png"
    image_file.write_bytes(b"source-image")
    monkeypatch.chdir(tmp_path)

    async def fake_refine_picedit_prompt_async(prompt: str, config: CodexConfig) -> str:
        del prompt, config
        return "优化后的改图提示词"

    class FakeImages:
        async def edit(self, **kwargs: object) -> object:
            del kwargs
            return type(
                "FakeImageResponse",
                (),
                {
                    "data": [type("FakeImageData", (), {"b64_json": "aGVsbG8="})()],
                    "__str__": lambda _self: "image-edit-response",
                },
            )()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float | None = None) -> None:
            del api_key, base_url, timeout
            self.images = FakeImages()

        def with_options(self, *, timeout: float) -> FakeClient:
            del timeout
            return self

    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic._refine_picedit_prompt_async", fake_refine_picedit_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
                pic_size="1024x1024",
                pic_quality="high",
                pic_output_format="png",
                pic_response_format="b64_json",
            )
        ),
    )

    result = run_codex_picedit(image_path=image_file, prompt="提亮并增强科技感")

    assert result.image_output_file == image_file.parent / "p2_version_002.png"
    assert result.trace_output_file == image_file.parent / "p2_version_002.trace.log"


def test_run_codex_pic_uses_fixed_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    md_file = tmp_path / "input" / "codex" / "banner.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成图片", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    captured: dict[str, object] = {}

    async def fake_refine_pic_prompt_async(prompt: str, config: CodexConfig) -> str:
        captured["refine_prompt"] = prompt
        captured["refine_model"] = config.model
        return "润色后的图片提示词"

    class FakeImages:
        async def generate(self, **kwargs: object) -> object:
            captured["kwargs"] = kwargs
            return type(
                "FakeImageResponse",
                (),
                {
                    "data": [type("FakeImageData", (), {"b64_json": "aGVsbG8="})()],
                    "usage": type(
                        "FakeUsage",
                        (),
                        {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46},
                    )(),
                    "__str__": lambda _self: "image-response",
                },
            )()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["client_timeout"] = timeout
            self.images = FakeImages()

        def with_options(self, *, timeout: float) -> FakeClient:
            captured["request_timeout"] = timeout
            return self

    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic._refine_pic_prompt_async", fake_refine_pic_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
                pic_size="1536x1024",
                pic_quality="high",
                pic_output_format="png",
                pic_response_format="b64_json",
            )
        ),
    )

    result = run_codex_pic(md_path=md_file)
    captured_output = capsys.readouterr().out

    assert captured["api_key"] == "token"
    assert captured["base_url"] == "https://example.com/v1"
    assert captured["client_timeout"] == 600.0
    assert captured["request_timeout"] == 600.0
    assert captured["refine_prompt"] == "生成图片"
    assert captured["refine_model"] == "grok-3-mini"
    assert captured["kwargs"] == {
        "model": "gpt-image-2",
        "prompt": "润色后的图片提示词",
        "size": "1536x1024",
        "quality": "high",
        "output_format": "png",
        "response_format": "b64_json",
    }
    assert result.image_output_file == Path("output") / "pic" / "banner" / "banner.png"
    assert result.image_output_file.read_bytes() == b"hello"
    assert result.trace_output_file == Path("output") / "pic" / "banner" / "banner.trace.log"
    assert "开始优化做图提示词：banner.md" in captured_output
    assert "提示词优化完成：banner.md，开始生成图片" in captured_output
    assert "图片生成完成，开始写入结果文件：output/pic/banner/banner.png" in captured_output
    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"status": "completed"' in trace_text
    assert '"refine_timeout_seconds": 300' in trace_text
    assert '"image_timeout_seconds": 600' in trace_text
    assert '"refine_elapsed_seconds":' in trace_text
    assert '"image_elapsed_seconds":' in trace_text
    assert '"refine_model": "grok-3-mini"' in trace_text
    assert '"pic_model": "gpt-image-2"' in trace_text
    assert '"original_prompt": "生成图片"' in trace_text
    assert '"refined_prompt": "润色后的图片提示词"' in trace_text
    assert '"refine_token_usage": {' in trace_text
    assert '"image_token_usage": {' in trace_text
    assert '"input_tokens": 12' in trace_text
    assert '"output_tokens": 34' in trace_text
    assert '"total_tokens": 46' in trace_text
    assert '"image_request_started_at": ' in trace_text
    assert '"image_request_elapsed_seconds":' in trace_text
    assert '"image_decode_elapsed_seconds":' in trace_text
    assert '"image_write_elapsed_seconds":' in trace_text
    assert '"total_elapsed_seconds":' in trace_text
    assert '"image_response": "image-response"' in trace_text
    assert result.output_dir == Path("output") / "pic" / "banner"


def test_run_codex_pic_excludes_b64_payload_from_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "input" / "codex" / "big-banner.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成大图", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    async def fake_refine_pic_prompt_async(prompt: str, config: CodexConfig) -> str:
        del config
        assert prompt == "生成大图"
        return "润色后的大图提示词"

    class FakeImages:
        async def generate(self, **kwargs: object) -> object:
            del kwargs
            return type(
                "FakeImageResponse",
                (),
                {
                    "data": [
                        type(
                            "FakeImageData",
                            (),
                            {"b64_json": "aGVsbG8=", "revised_prompt": "保留主体，增强光影"},
                        )()
                    ],
                    "created": 1234567890,
                    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                    "model_dump": lambda _self: {
                        "created": 1234567890,
                        "data": [{"b64_json": "VERY_LARGE_BASE64", "revised_prompt": "保留主体，增强光影"}],
                    },
                    "__str__": lambda _self: "should-not-be-used-when-model-dump-exists",
                },
            )()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float | None = None) -> None:
            del api_key, base_url, timeout
            self.images = FakeImages()

        def with_options(self, *, timeout: float) -> FakeClient:
            del timeout
            return self

    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic._refine_pic_prompt_async", fake_refine_pic_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
                pic_size="1536x1024",
                pic_quality="high",
                pic_output_format="png",
                pic_response_format="b64_json",
            )
        ),
    )

    result = run_codex_pic(md_path=md_file)

    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"image_response": {' in trace_text
    assert '"created": 1234567890' in trace_text
    assert '"revised_prompt": "保留主体，增强光影"' in trace_text
    assert "VERY_LARGE_BASE64" not in trace_text
    assert '"image_response": "should-not-be-used-when-model-dump-exists"' not in trace_text
    assert "should-not-be-used-when-model-dump-exists" not in trace_text


def test_run_codex_pic_does_not_log_before_request_and_writes_request_started_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    md_file = tmp_path / "input" / "codex" / "poster.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成海报", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    caplog.set_level("INFO")

    async def fake_refine_pic_prompt_async(prompt: str, config: CodexConfig) -> str:
        del config
        assert prompt == "生成海报"
        return "适合出图的海报提示词"

    class FakeImages:
        async def generate(self, **kwargs: object) -> object:
            assert kwargs["prompt"] == "适合出图的海报提示词"
            return type(
                "FakeImageResponse",
                (),
                {
                    "data": [type("FakeImageData", (), {"b64_json": "aGVsbG8="})()],
                    "usage": type(
                        "FakeUsage",
                        (),
                        {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                    )(),
                    "__str__": lambda _self: "image-response",
                },
            )()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float | None = None) -> None:
            del api_key, base_url, timeout
            self.images = FakeImages()

        def with_options(self, *, timeout: float) -> FakeClient:
            del timeout
            return self

    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic._refine_pic_prompt_async", fake_refine_pic_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    run_codex_pic(md_path=md_file)

    assert "即将请求图片生成接口" not in caplog.text
    trace_text = (Path("output") / "pic" / "poster" / "poster.trace.log").read_text(encoding="utf-8")
    assert '"image_request_started_at": ' in trace_text


def test_log_pic_stage_records_prompt_and_usage(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    _log_pic_stage(
        "pic_completed",
        source=Path("input/codex/banner.md"),
        original_prompt="原始提示词",
        refined_prompt="优化后的提示词",
        elapsed_seconds=1.234,
        token_usage=_TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
        output_file=Path("output/pic/banner/banner.png"),
    )

    assert "original_prompt=原始提示词" in caplog.text
    assert "refined_prompt=优化后的提示词" in caplog.text
    assert "elapsed_seconds=1.234" in caplog.text
    assert "input_tokens" in caplog.text


def test_run_codex_pic_prefers_explicit_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "input" / "codex" / "album.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成专辑封面", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    captured: dict[str, object] = {}

    async def fake_refine_pic_prompt_async(prompt: str, config: CodexConfig) -> str:
        captured["refine_prompt"] = prompt
        captured["refine_model"] = config.model
        return "更适合做图的提示词"

    class FakeImages:
        async def generate(self, **kwargs: object) -> object:
            captured["kwargs"] = kwargs
            return type(
                "FakeImageResponse",
                (),
                {
                    "data": [type("FakeImageData", (), {"b64_json": "aGVsbG8="})()],
                    "__str__": lambda _self: "image-response",
                },
            )()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float | None = None) -> None:
            del api_key, base_url
            captured["client_timeout"] = timeout
            self.images = FakeImages()

        def with_options(self, *, timeout: float) -> FakeClient:
            captured["request_timeout"] = timeout
            return self

    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic._refine_pic_prompt_async", fake_refine_pic_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
                pic_size="1536x1024",
                pic_quality="high",
                pic_output_format="png",
                pic_response_format="b64_json",
            )
        ),
    )

    result = run_codex_pic(md_path=md_file, size="1536x1024", quality="low", output_format="webp")

    assert captured["refine_prompt"] == "生成专辑封面"
    assert captured["refine_model"] == "grok-3-mini"
    assert captured["client_timeout"] == 600.0
    assert captured["request_timeout"] == 600.0
    assert captured["kwargs"] == {
        "model": "gpt-image-2",
        "prompt": "更适合做图的提示词",
        "size": "1536x1024",
        "quality": "low",
        "output_format": "webp",
        "response_format": "b64_json",
    }
    assert result.image_output_file == Path("output") / "pic" / "album" / "album.webp"


def test_run_codex_pic_rejects_non_markdown_file(tmp_path: Path) -> None:
    text_file = tmp_path / "input" / "codex" / "banner.txt"
    text_file.parent.mkdir(parents=True)
    text_file.write_text("生成图片", encoding="utf-8")

    with pytest.raises(ValueError, match="Markdown"):
        run_codex_pic(md_path=text_file)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"size": "999x999"}, "图片尺寸"),
        ({"quality": "ultra"}, "图片质量"),
        ({"output_format": "gif"}, "输出格式"),
    ],
)
def test_run_codex_pic_rejects_invalid_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    message: str,
) -> None:
    md_file = tmp_path / "input" / "codex" / "invalid.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成图片", encoding="utf-8")

    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    with pytest.raises(ValueError, match=message):
        run_codex_pic(md_path=md_file, **kwargs)


def test_execute_shell_commands_passes_cwd_and_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"ok", b"")

    async def fake_create_subprocess_shell(
        command: str,
        *,
        cwd: Path,
        stdout: object,
        stderr: object,
    ) -> FakeProcess:
        executed["command"] = command
        executed["cwd"] = cwd
        executed["stdout"] = stdout
        executed["stderr"] = stderr
        return FakeProcess()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_create_subprocess_shell)

    from beartools.codex import _execute_shell_commands

    result = asyncio.run(_execute_shell_commands(["pwd"], timeout_seconds=5))

    assert executed["command"] == "pwd"
    assert executed["cwd"] == tmp_path / "output" / "codex"
    assert result.output[0].command == "pwd"
    assert result.output[0].stdout == "ok"


def test_run_codex_markdown_raises_when_config_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(
        "beartools.codex.get_config",
        lambda: Config(codex=CodexConfig(base_url="", api_key="token", model="demo-model")),
    )

    with pytest.raises(RuntimeError, match="base_url"):
        asyncio.run(run_codex_markdown_async(md_file, None, None))


def test_run_codex_pic_requires_pic_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("生成图片", encoding="utf-8")

    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(base_url="https://example.com/v1", api_key="token", model="demo-model", pic_model="")
        ),
    )

    with pytest.raises(RuntimeError, match="pic_model"):
        run_codex_pic(md_path=md_file)


def test_run_codex_pic_writes_trace_when_refine_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "input" / "codex" / "failed.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("生成失败图片", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    async def fake_refine_pic_prompt_async(prompt: str, config: CodexConfig) -> str:
        del prompt, config
        raise RuntimeError("refine boom")

    monkeypatch.setattr("beartools.codex_pic._refine_pic_prompt_async", fake_refine_pic_prompt_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
            )
        ),
    )

    with pytest.raises(RuntimeError, match="refine boom"):
        run_codex_pic(md_path=md_file)

    trace_file = Path("output") / "pic" / "failed" / "failed.trace.log"
    trace_text = trace_file.read_text(encoding="utf-8")
    assert '"status": "refine_failed"' in trace_text
    assert '"refine_elapsed_seconds":' in trace_text
    assert '"error": "refine boom"' in trace_text


def test_run_codex_markdown_happy_path_writes_trace_and_final_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("请执行", encoding="utf-8")
    config = _build_fake_config(tmp_path / "output")

    async def fake_events() -> AsyncIterator[object]:
        yield _CodexStreamEvent(type="reasoning_item_created", message="思考中", display_text="[thinking] 思考中")
        yield _CodexStreamEvent(type="tool_called", message="shell", display_text="[tool:start] shell")
        yield _CodexStreamEvent(type="response.output_text.delta", message="部分回答", display_text="部分回答")

    stream = _FakeStreamRunResult(events_factory=fake_events, final_output="最终回答")
    _patch_runtime(monkeypatch, config=config, stream=stream)

    result = asyncio.run(run_codex_markdown_async(md_file, None, None))

    assert result.final_text == "最终回答"
    assert result.final_output_file.read_text(encoding="utf-8") == "最终回答"
    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"type": "reasoning_item_created"' in trace_text
    assert '"type": "tool_called"' in trace_text
    assert '"message": "部分回答"' in trace_text


def test_refine_pic_prompt_uses_text_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del tmp_path
    captured: dict[str, object] = {}

    class FakeRunResult:
        final_output = "润色后的提示词"

    class FakeRunner:
        @staticmethod
        async def run(agent: object, input: str) -> FakeRunResult:
            captured["agent"] = agent
            captured["input"] = input
            return FakeRunResult()

    class FakeModel:
        def __init__(self, *, model: str, openai_client: object) -> None:
            captured["model"] = model
            captured["openai_client"] = openai_client

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    class FakeAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["agent_kwargs"] = kwargs

    monkeypatch.setattr("beartools.codex_pic.Runner", FakeRunner)
    monkeypatch.setattr("beartools.codex_pic.OpenAIResponsesModel", FakeModel)
    monkeypatch.setattr("beartools.codex_pic.AsyncOpenAI", FakeClient)
    monkeypatch.setattr("beartools.codex_pic.Agent", FakeAgent)
    monkeypatch.setattr("beartools.codex_pic.set_tracing_disabled", lambda _value: None)
    monkeypatch.setattr("beartools.codex_pic._build_refine_instructions", lambda _name: "模板里的提示词")

    refined = asyncio.run(
        _refine_pic_prompt_async(
            "原始 markdown 提示词",
            CodexConfig(
                base_url="https://example.com/v1", api_key="token", model="grok-3-mini", pic_model="gpt-image-2"
            ),
        )
    )

    assert refined == "润色后的提示词"
    assert captured["api_key"] == "token"
    assert captured["base_url"] == "https://example.com/v1"
    assert captured["model"] == "grok-3-mini"
    assert captured["input"] == "原始 markdown 提示词"
    agent_kwargs = cast(dict[str, object], captured["agent_kwargs"])
    assert agent_kwargs["instructions"] == "模板里的提示词"


def test_run_codex_picbatch_collects_success_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first_file = tmp_path / "first.md"
    second_file = tmp_path / "second.md"
    first_file.write_text("生成第一张图", encoding="utf-8")
    second_file.write_text("生成第二张图", encoding="utf-8")

    def fake_run_codex_pic(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        assert size == "1536x1024"
        assert quality == "medium"
        assert output_format == "webp"
        if md_path == second_file:
            raise RuntimeError("refine boom")
        output_dir = Path("output") / "pic" / md_path.stem
        return CodexPicResult(
            output_dir=output_dir,
            image_output_file=output_dir / f"{md_path.stem}.webp",
            trace_output_file=output_dir / f"{md_path.stem}.trace.log",
        )

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        return fake_run_codex_pic(md_path=md_path, size=size, quality=quality, output_format=output_format)

    monkeypatch.setattr("beartools.codex_pic.run_codex_pic_async", fake_run_codex_pic_async)
    monkeypatch.setattr(
        "beartools.codex_pic.get_config",
        lambda: Config(
            codex=CodexConfig(
                base_url="https://example.com/v1",
                api_key="token",
                model="grok-3-mini",
                pic_model="gpt-image-2",
                pic_output_format="png",
            )
        ),
    )

    result = run_codex_picbatch([first_file, second_file], size="1536x1024", quality="medium", output_format="webp")

    assert len(result.results) == 2
    assert result.results[0].md_path == first_file
    assert result.results[0].succeeded is True
    assert result.results[0].image_output_file == Path("output") / "pic" / "first" / "first.webp"
    assert result.results[0].trace_output_file == Path("output") / "pic" / "first" / "first.trace.log"
    assert result.results[0].error_message is None
    assert result.results[1].md_path == second_file
    assert result.results[1].succeeded is False
    assert result.results[1].image_output_file is None
    assert result.results[1].trace_output_file == Path("output") / "pic" / "second" / "second.trace.log"
    assert result.results[1].error_message == "refine boom"


def test_run_codex_picbatch_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        run_codex_picbatch([])


def test_run_codex_picbatch_limits_concurrency_to_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = [tmp_path / f"task_{index}.md" for index in range(3)]
    for md_file in files:
        md_file.write_text("生成图片", encoding="utf-8")

    active_count = 0
    max_active_count = 0
    counter_lock = asyncio.Lock()

    async def fake_run_codex_pic_async(
        *,
        md_path: Path,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
    ) -> CodexPicResult:
        del md_path, size, quality, output_format
        nonlocal active_count, max_active_count
        async with counter_lock:
            active_count += 1
            if active_count > max_active_count:
                max_active_count = active_count
        await asyncio.sleep(0.05)
        async with counter_lock:
            active_count -= 1
        output_dir = Path("output") / "pic" / "ok"
        return CodexPicResult(
            output_dir=output_dir,
            image_output_file=output_dir / "ok.png",
            trace_output_file=output_dir / "ok.trace.log",
        )

    monkeypatch.setattr("beartools.codex_pic.run_codex_pic_async", fake_run_codex_pic_async)

    result = run_codex_picbatch(files)

    assert len(result.results) == 3
    assert max_active_count == 2


def test_run_codex_markdown_recovers_on_stream_error_and_keeps_final_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("请执行", encoding="utf-8")
    config = _build_fake_config(tmp_path / "output")

    async def fake_events() -> AsyncIterator[object]:
        yield _CodexStreamEvent(type="unknown_event", message="turn.started", display_text="")
        raise RuntimeError("socket error")

    stream = _FakeStreamRunResult(events_factory=fake_events, final_output="保留的最终回答")
    _patch_runtime(monkeypatch, config=config, stream=stream)

    result = asyncio.run(run_codex_markdown_async(md_file, None, None))

    assert result.final_text == "保留的最终回答"
    assert result.final_output_file.read_text(encoding="utf-8") == "保留的最终回答"
    trace_text = result.trace_output_file.read_text(encoding="utf-8")
    assert '"type": "unknown_event"' in trace_text
    assert "turn.started" in trace_text
    assert "stream_error: socket error" in trace_text


def test_normalize_stream_event_maps_agent_updated_event() -> None:
    class FakeRuntimeAgentUpdatedStreamEvent:
        def __init__(self) -> None:
            self.type = "agent_updated_stream_event"
            self.new_agent = "Codex Runner"

        def __repr__(self) -> str:
            return "FakeAgentUpdatedEvent(new_agent='Codex Runner')"

    with patch.dict(
        "sys.modules",
        {
            "agents.stream_events": type(
                "FakeModule",
                (),
                {
                    "AgentUpdatedStreamEvent": FakeRuntimeAgentUpdatedStreamEvent,
                    "RawResponsesStreamEvent": type("RawResponsesStreamEvent", (), {}),
                    "RunItemStreamEvent": type("RunItemStreamEvent", (), {}),
                },
            )(),
            "agents.items": type(
                "FakeItemsModule",
                (),
                {
                    "ReasoningItem": type("ReasoningItem", (), {}),
                    "ToolCallItem": type("ToolCallItem", (), {}),
                    "ToolCallOutputItem": type("ToolCallOutputItem", (), {}),
                },
            )(),
        },
    ):
        event = _normalize_stream_event(FakeRuntimeAgentUpdatedStreamEvent())

    assert event == _CodexStreamEvent(
        type="agent_updated_stream_event",
        message="agent_updated_stream_event: FakeAgentUpdatedEvent(new_agent='Codex Runner')",
        display_text="",
    )


def test_normalize_stream_event_maps_raw_response_lifecycle_events() -> None:
    class FakeResponseEvent:
        def __init__(self, event_type: str) -> None:
            self.type = event_type

        def __repr__(self) -> str:
            return f"FakeResponseEvent(type={self.type!r})"

    class FakeRuntimeRawResponsesStreamEvent:
        def __init__(self, event_type: str) -> None:
            self.type = "raw_response_event"
            self.data = FakeResponseEvent(event_type)

    with patch.dict(
        "sys.modules",
        {
            "agents.stream_events": type(
                "FakeModule",
                (),
                {
                    "AgentUpdatedStreamEvent": type("AgentUpdatedStreamEvent", (), {}),
                    "RawResponsesStreamEvent": FakeRuntimeRawResponsesStreamEvent,
                    "RunItemStreamEvent": type("RunItemStreamEvent", (), {}),
                },
            )(),
            "agents.items": type(
                "FakeItemsModule",
                (),
                {
                    "ReasoningItem": type("ReasoningItem", (), {}),
                    "ToolCallItem": type("ToolCallItem", (), {}),
                    "ToolCallOutputItem": type("ToolCallOutputItem", (), {}),
                },
            )(),
        },
    ):
        event = _normalize_stream_event(FakeRuntimeRawResponsesStreamEvent("response.created"))

    assert event == _CodexStreamEvent(
        type="response.lifecycle",
        message="response.created: FakeResponseEvent(type='response.created')",
        display_text="",
    )


def test_normalize_stream_event_maps_raw_response_web_search_call() -> None:
    class FakeResponseEvent:
        def __init__(self) -> None:
            self.type = "response.output_item.done"
            self.item = type(
                "FakeWebSearchItem",
                (),
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "__repr__": lambda _self: "FakeWebSearchItem(type='web_search_call', status='completed')",
                },
            )()

        def __repr__(self) -> str:
            return "FakeResponseEvent(type='response.output_item.done', item=FakeWebSearchItem(type='web_search_call', status='completed'))"

    class FakeRuntimeRawResponsesStreamEvent:
        def __init__(self) -> None:
            self.type = "raw_response_event"
            self.data = FakeResponseEvent()

    with patch.dict(
        "sys.modules",
        {
            "agents.stream_events": type(
                "FakeModule",
                (),
                {
                    "AgentUpdatedStreamEvent": type("AgentUpdatedStreamEvent", (), {}),
                    "RawResponsesStreamEvent": FakeRuntimeRawResponsesStreamEvent,
                    "RunItemStreamEvent": type("RunItemStreamEvent", (), {}),
                },
            )(),
            "agents.items": type(
                "FakeItemsModule",
                (),
                {
                    "ReasoningItem": type("ReasoningItem", (), {}),
                    "ToolCallItem": type("ToolCallItem", (), {}),
                    "ToolCallOutputItem": type("ToolCallOutputItem", (), {}),
                },
            )(),
        },
    ):
        event = _normalize_stream_event(FakeRuntimeRawResponsesStreamEvent())

    assert event == _CodexStreamEvent(
        type="tool_called",
        message="web_search_call",
        display_text="[tool:start] web_search_call",
    )
