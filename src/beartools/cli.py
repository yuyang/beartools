"""beartools CLI 入口

支持多个子命令，默认输出帮助信息。
"""

from __future__ import annotations

import typer

from beartools.commands.bill import bill_app
from beartools.commands.clear.command import clear_command
from beartools.commands.doctor.command import doctor_command
from beartools.commands.fetch.command import fetch
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
@app.callback(invoke_without_command=True)  # type: ignore
def main(ctx: typer.Context) -> None:
    """beartools 主入口，无参数时显示帮助"""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# 创建doctor命令组
doctor_app = typer.Typer(name="doctor", help="运行环境健康检查", add_completion=False)

# 注册doctor作为子命令组
app.add_typer(doctor_app, name="doctor")


@doctor_app.command(name="run", help="运行健康检查（默认，不包含LLM检查）")  # type: ignore[misc]
def doctor_run() -> None:
    """运行环境健康检查（不包含LLM检查）"""
    doctor_command(run_llm=False)
    shutdown_logging()


@doctor_app.command(name="withall", help="运行所有健康检查，包含LLM检查")  # type: ignore[misc]
def doctor_withall() -> None:
    """运行所有健康检查，包含LLM检查"""
    doctor_command(run_llm=True)
    shutdown_logging()


# 默认子命令，不带参数时执行run
@doctor_app.callback(invoke_without_command=True)  # type: ignore[misc]
def doctor_default(ctx: typer.Context) -> None:
    """Doctor 健康检查命令组"""
    if ctx.invoked_subcommand is None:
        doctor_run()


# 注册clear作为子命令
@app.command(name="clear", help="删除临时文件")  # type: ignore
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
app.add_typer(bill_app, name="bill", help="账单处理相关操作")

# 注册fetch作为子命令
app.command(name="fetch", help="根据URL抓取内容")(fetch)


if __name__ == "__main__":
    app()
