"""beartools CLI 入口

支持多个子命令，默认输出帮助信息。
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
import shlex
import sys
import time
from typing import Protocol, TextIO, cast

import click
import typer
from typer.main import get_command

from beartools.commands.bill import bill_app
from beartools.commands.check import check_app
from beartools.commands.clear.command import clear_command
from beartools.commands.codex import codex_app
from beartools.commands.diary import diary_app
from beartools.commands.doctor.command import doctor_command
from beartools.commands.fetch.command import fetch
from beartools.commands.gmail import gmail_app
from beartools.commands.markdown import markdown_app
from beartools.commands.model import model_app
from beartools.commands.newsnow import newsnow_app
from beartools.commands.record import record_app
from beartools.commands.siyuan import siyuan_app
from beartools.logger import shutdown_logging
from beartools.memory.models import CommandMemoryInput
from beartools.memory.service import append_command_memory, create_command_summarizer, get_memory_root


class _ClickGroupProtocol(Protocol):
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """获取子命令。"""


class _TeeTextCapture:
    """同步写入原始流，并保留一份文本用于命令记忆。"""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._buffer = StringIO()

    def write(self, text: str) -> int:
        """写入终端并复制到内存缓冲。"""

        self._buffer.write(text)
        return self._stream.write(text)

    def flush(self) -> None:
        """刷新原始输出流。"""

        self._stream.flush()

    def getvalue(self) -> str:
        """返回已捕获的文本。"""

        return self._buffer.getvalue()


# 创建主应用
app = typer.Typer(
    name="beartools",
    help="beartools：自用工具集",
    add_completion=False,
)


# 主回调，无参数时显示帮助
@app.callback(invoke_without_command=True)  # type: ignore[misc]
def main(ctx: typer.Context) -> None:
    """beartools 主入口，无参数时显示帮助。"""
    _ = ctx


# 注册doctor作为子命令
@app.command(name="doctor", help="运行环境健康检查")  # type: ignore[misc]
def doctor(
    run_llm: bool = typer.Option(False, "--run-llm", help="是否包含 LLM 检查项"),
) -> None:
    """运行环境健康检查"""
    doctor_command(run_llm=run_llm)


# 注册clear作为子命令
@app.command(name="clear", help="删除临时文件")  # type: ignore[misc]
def clear() -> None:
    """删除临时文件"""
    clear_command()
    shutdown_logging()


# 注册siyuan作为子命令
app.add_typer(siyuan_app, name="siyuan", help="思源笔记管理")

# 注册record作为子命令
app.add_typer(record_app, name="record", help="记录管理")

# 注册markdown作为子命令
app.add_typer(markdown_app, name="markdown", help="Markdown 文件处理")

# 注册model作为子命令
app.add_typer(model_app, name="model", help="模型工具")

# 注册check作为子命令
app.add_typer(check_app, name="check", help="检查工具")

# 注册bill作为子命令
app.add_typer(bill_app, name="bill", help="账单处理，直接输入文件路径时默认执行完整流程")

# 注册fetch作为子命令
app.command(name="fetch", help="根据 URL 抓取内容")(fetch)

# 注册gmail作为子命令
app.add_typer(gmail_app, name="gmail", help="Gmail 邮件处理")

# 注册newsnow作为子命令
app.add_typer(newsnow_app, name="newsnow", help="NewsNow 热点抓取")

# 注册codex作为子命令
app.add_typer(codex_app, name="codex", help="Codex 工具")

# 注册diary作为子命令
app.add_typer(diary_app, name="diary", help="命令记忆日记")


def _main_wrapper() -> None:
    """
    主函数包装器，支持 bill 命令的默认行为：
    如果用户输入 `beartools bill <input> <from>`，自动插入 `run` 子命令
    """
    original_argv = sys.argv[:]
    argv = original_argv[:]
    if len(argv) == 1:
        argv.append("--help")

    bill_index = -1
    for i, arg in enumerate(argv):
        if arg == "bill":
            bill_index = i
            break

    # 如果找到了 bill，检查后面的参数
    if bill_index != -1 and bill_index + 1 < len(argv):
        first_arg = argv[bill_index + 1]
        # 如果不是已知的子命令或帮助选项，插入 run
        if first_arg not in ["normalize", "analysis", "run", "--help", "-h"]:
            argv.insert(bill_index + 1, "run")

    started_at = _resolve_memory_now()
    started_monotonic = time.monotonic()
    stdout_capture = _TeeTextCapture(sys.stdout)
    stderr_capture = _TeeTextCapture(sys.stderr)
    exit_code = 0

    sys.argv = argv
    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            app(args=argv[1:], prog_name="beartools", standalone_mode=False)
    except click.exceptions.Exit as exc:
        exit_code = int(exc.exit_code)
    except SystemExit as exc:
        exit_code = _coerce_exit_code(exc.code)
    finally:
        sys.argv = original_argv

    stdout_text = stdout_capture.getvalue()
    stderr_text = stderr_capture.getvalue()
    sys.stdout.flush()
    sys.stderr.flush()

    duration_seconds = time.monotonic() - started_monotonic
    _record_command_memory(
        argv=argv,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        exit_code=exit_code,
        started_at=started_at,
        duration_seconds=duration_seconds,
    )
    raise SystemExit(exit_code)


def _resolve_memory_now() -> datetime:
    """解析测试可注入的记忆时间。"""

    import os

    raw_value = os.environ.get("BEARTOOLS_MEMORY_NOW")
    if raw_value is None:
        return datetime.now()
    return datetime.fromisoformat(raw_value)


def _coerce_exit_code(code: object) -> int:
    """把 SystemExit code 转成整数。"""

    if isinstance(code, int):
        return code
    if code is None:
        return 0
    return 1


def _record_command_memory(
    *,
    argv: list[str],
    stdout_text: str,
    stderr_text: str,
    exit_code: int,
    started_at: datetime,
    duration_seconds: float,
) -> None:
    """记录本次 beartools 命令，失败不影响原命令结果。"""

    try:
        memory_input = CommandMemoryInput(
            command=_format_command(argv),
            help_text=_resolve_help_text(argv[1:]),
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            started_at=started_at,
            duration_seconds=duration_seconds,
        )
        append_command_memory(
            memory_root=get_memory_root(),
            memory_input=memory_input,
            summarizer=create_command_summarizer(),
        )
    except (RuntimeError, ValueError, OSError, click.ClickException) as exc:
        print(f"记忆写入失败: {exc}", file=sys.stderr)


def _format_command(argv: list[str]) -> str:
    """格式化用于记忆的命令文本。"""

    display_args = ["beartools", *argv[1:]]
    return " ".join(shlex.quote(arg) for arg in display_args)


def _resolve_help_text(args: list[str]) -> str:
    """解析当前命令 help 文本。"""

    click_command = get_command(app)
    current_command: click.Command = click_command
    remaining = list(args)
    while remaining and hasattr(current_command, "get_command"):
        next_arg = remaining[0]
        if next_arg.startswith("-"):
            break
        command_group = cast(_ClickGroupProtocol, current_command)
        next_command = command_group.get_command(click.Context(current_command), next_arg)
        if next_command is None:
            break
        current_command = next_command
        remaining.pop(0)
    return current_command.help or current_command.short_help or "无"


if __name__ == "__main__":
    _main_wrapper()
