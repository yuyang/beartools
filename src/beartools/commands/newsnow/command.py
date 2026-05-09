"""NewsNow 命令。"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
import typer

from beartools.newsnow import (
    DEFAULT_DOMAIN,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WORKSPACE,
    NewsNowError,
    fetch_newsnow_from_local_browser,
)

newsnow_app = typer.Typer(help="NewsNow 热点抓取", add_completion=False)
console = Console()


@newsnow_app.command("fetch", help="通过本地浏览器抓取 NewsNow 接口并生成 Markdown")  # type: ignore[misc]
def fetch(
    workspace: str = typer.Option(DEFAULT_WORKSPACE, "--workspace", help="opencli 浏览器 workspace"),
    domain: str = typer.Option(DEFAULT_DOMAIN, "--domain", help="要绑定的 NewsNow 域名"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir", help="输出目录"),  # noqa: B008
    top: int = typer.Option(30, "--top", min=1, help="每个来源写入 Markdown 的最大条目数"),
) -> None:
    """通过 opencli 绑定本地 Chrome 标签页，读取 NewsNow 接口数据。"""
    try:
        result = fetch_newsnow_from_local_browser(workspace=workspace, domain=domain, output_dir=output_dir, top=top)
    except NewsNowError as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"接口来源数: {result.source_count}")
    console.print(f"JSON 输出: {result.json_file}", style="green")
    console.print(f"Markdown 输出: {result.markdown_file}", style="green")
