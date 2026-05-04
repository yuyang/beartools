"""Codex 命令。"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
import typer

from beartools.codex import run_codex_markdown, run_codex_pic

codex_app = typer.Typer(help="Codex 相关操作", add_completion=False)
console = Console()


def codex_run(
    md_path: Path = typer.Argument(..., help="本地 Markdown 文件路径"),  # noqa: B008
    output_file: Path | None = typer.Option(None, help="最终回答输出文件"),  # noqa: B008
    trace_file: Path | None = typer.Option(None, help="trace 输出文件"),  # noqa: B008
) -> None:
    """执行 Codex Markdown 任务。"""

    try:
        result = run_codex_markdown(md_path=md_path, output_file=output_file, trace_file=trace_file)
    except (RuntimeError, FileNotFoundError, ValueError, NotImplementedError) as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"回答已写入: {result.final_output_file}", style="green")
    console.print(f"Trace 已写入: {result.trace_output_file}", style="green")


def codex_pic(
    md_path: Path = typer.Argument(..., help="input/codex 目录下的 Markdown 文件路径"),  # noqa: B008
    size: str | None = typer.Option(None, help="图片尺寸，如 1024x1024"),  # noqa: B008
    quality: str | None = typer.Option(None, help="图片质量，如 high"),  # noqa: B008
    output_format: str | None = typer.Option(None, help="输出格式，如 png"),  # noqa: B008
) -> None:
    """执行 Codex 图片任务。"""

    try:
        result = run_codex_pic(md_path=md_path, size=size, quality=quality, output_format=output_format)
    except (RuntimeError, FileNotFoundError, ValueError, NotImplementedError) as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"结果目录: {result.output_dir}", style="green")
    console.print(f"图片已写入: {result.image_output_file}", style="green")
    console.print(f"Trace 已写入: {result.trace_output_file}", style="green")


codex_app.command("run")(codex_run)
codex_app.command("pic")(codex_pic)
