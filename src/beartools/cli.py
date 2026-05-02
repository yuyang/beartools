"""beartools CLI 入口

支持多个子命令，默认输出帮助信息。
"""

from __future__ import annotations

import sys

import typer

from beartools.commands.bill import bill_app
from beartools.commands.clear.command import clear_command
from beartools.commands.codex import codex_app
from beartools.commands.doctor.command import doctor_command
from beartools.commands.fetch.command import fetch
from beartools.commands.gmail import gmail_app
from beartools.commands.markdown import markdown_app
from beartools.commands.record import record_app
from beartools.commands.siyuan import siyuan_app
from beartools.logger import shutdown_logging

# 创建主应用
app = typer.Typer(
    name="beartools",
    help="beartools - 自用工具集合",
    add_completion=False,
)


# 主回调，无参数时显示帮助
@app.callback(invoke_without_command=True)  # type: ignore[misc]
def main(ctx: typer.Context) -> None:
    """beartools 主入口，无参数时显示帮助。"""
    if ctx.invoked_subcommand is None:
        help_text = ctx.command.get_help(ctx)
        print(help_text)


# 注册doctor作为子命令
@app.command(name="doctor", help="运行环境健康检查")  # type: ignore[misc]
def doctor() -> None:
    """运行环境健康检查"""
    doctor_command()


# 注册clear作为子命令
@app.command(name="clear", help="删除临时文件")  # type: ignore[misc]
def clear() -> None:
    """删除临时文件"""
    clear_command()
    shutdown_logging()


# 注册siyuan作为子命令
app.add_typer(siyuan_app, name="siyuan", help="思源笔记相关操作")

# 注册record作为子命令
app.add_typer(record_app, name="record", help="记录管理相关操作")

# 注册markdown作为子命令
app.add_typer(markdown_app, name="markdown", help="Markdown 文件处理相关操作")

# 注册bill作为子命令
app.add_typer(bill_app, name="bill", help="账单处理相关操作，直接输入文件路径默认执行完整流程")

# 注册fetch作为子命令
app.command(name="fetch", help="根据URL抓取内容")(fetch)

# 注册gmail作为子命令
app.add_typer(gmail_app, name="gmail", help="Gmail 邮件相关操作")

# 注册codex作为子命令
app.add_typer(codex_app, name="codex", help="Codex 相关操作")


def _main_wrapper() -> None:
    """
    主函数包装器，支持 bill 命令的默认行为：
    如果用户输入 `beartools bill <input> <from>`，自动插入 `run` 子命令
    """
    argv = sys.argv[:]
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

    # 更新 sys.argv 并运行
    sys.argv = argv
    app()


if __name__ == "__main__":
    _main_wrapper()
