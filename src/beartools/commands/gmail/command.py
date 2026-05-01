"""Gmail 命令。"""

from __future__ import annotations

from rich.console import Console
import typer

from beartools.config import get_config
from beartools.gmail import fetch_gmail_summary
from beartools.logger import get_logger

gmail_app = typer.Typer(help="Gmail 邮件相关操作", add_completion=False)
console = Console()
logger = get_logger(__name__)


def fetch(
    days: int | None = typer.Option(None, "--days", min=1, help="抓取最近多少天的 INBOX 邮件，默认取配置值"),
    max_results: int | None = typer.Option(None, "--max-results", min=1, help="最多处理多少封邮件，默认取配置值"),
) -> None:
    """抓取 Gmail 收件箱邮件。"""

    config = get_config().gmail
    resolved_days = days or config.default_days
    resolved_max_results = max_results or config.max_results
    try:
        result = fetch_gmail_summary(days=resolved_days, max_results=resolved_max_results)
    except TimeoutError as exc:
        logger.exception("Gmail 抓取超时: days=%s max_results=%s", resolved_days, resolved_max_results)
        console.print("Gmail 抓取超时，请稍后重试", style="red")
        raise typer.Exit(1) from exc
    except Exception as exc:
        logger.exception("Gmail 抓取失败: days=%s max_results=%s", resolved_days, resolved_max_results)
        console.print("Gmail 抓取失败，请查看日志文件", style="red")
        raise typer.Exit(1) from exc
    console.print(f"抓取天数: {result.fetched_days}")
    console.print(f"命中邮件数: {result.total_count}")
    console.print(f"处理的邮件个数: {result.processed_count}")
    if result.truncated:
        console.print(f"超过处理上限，仅处理前 {result.max_results} 封", style="yellow")
    console.print(result.summary_text)
    console.print(f"输出文件: {result.output_file}", style="green")


gmail_app.command("fetch")(fetch)
