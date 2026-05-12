"""Gmail 命令。"""

from __future__ import annotations

from rich.console import Console
import typer

from beartools.config import get_config
from beartools.gmail import fetch_gmail_summary, send_plain_text_email, validate_email_address
from beartools.logger import get_logger

gmail_app = typer.Typer(help="Gmail 邮件处理", add_completion=False)
console = Console()
logger = get_logger(__name__)


def fetch(
    days: int | None = typer.Option(None, "--days", min=1, help="抓取最近多少天的 INBOX 邮件，默认使用配置值"),
    max_results: int | None = typer.Option(None, "--max-results", min=1, help="最多处理多少封邮件，默认使用配置值"),
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


def _prompt_valid_email() -> str:
    """循环询问收件人直到邮箱格式正确。"""

    while True:
        send_to = console.input("sendto: ")
        try:
            return validate_email_address(send_to)
        except ValueError:
            console.print("邮箱地址格式不正确，请重新输入", style="red")


def _normalize_prompt_content(content: str) -> str:
    """将用户输入中的字面量换行标记转成真实换行。"""

    return content.replace("\\n", "\n")


def send() -> None:
    """发送 Gmail 纯文本邮件。"""

    send_to = _prompt_valid_email()
    title = console.input("title: ")
    content = _normalize_prompt_content(console.input("内容: "))
    try:
        result = send_plain_text_email(send_to=send_to, title=title, content=content)
    # Gmail 授权和 API 客户端会抛出多种第三方异常，CLI 统一收口，避免泄露 traceback 和正文。
    except Exception as exc:
        logger.exception("Gmail 发送失败: send_to=%s error_type=%s", send_to, type(exc).__name__)
        console.print("Gmail 发送失败，请查看日志文件", style="red")
        raise typer.Exit(1) from exc
    console.print(f"发送成功: {result.message_id}", style="green")


gmail_app.command("fetch", help="抓取 Gmail 收件箱摘要")(fetch)
gmail_app.command("send", help="发送 Gmail 纯文本邮件")(send)
