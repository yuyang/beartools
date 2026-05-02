"""Codex 命令。"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
import typer

from beartools.codex import run_codex_markdown

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


codex_app.command("run")(codex_run)
