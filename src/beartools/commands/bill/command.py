"""账单处理命令模块。"""

from __future__ import annotations

from typing import cast

from rich.console import Console
import typer

from beartools.bill import analyze_bill_file, normalize_bill_file, run_bill_pipeline

console = Console()

# 真正的 bill 子 app，负责处理子命令和默认调用
bill_app = typer.Typer(
    help="账单处理相关操作，直接输入文件路径默认执行完整流程",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},  # type: ignore[misc]
)


@bill_app.command(name="normalize", help="将单个账单文件归一化为统一 Excel")  # type: ignore[misc]
def normalize_bill_command(
    input_path: str = typer.Argument(..., help="输入账单文件路径，支持 CSV/Excel"),
    from_value: str | None = typer.Argument(None, help="from值，同时参与输出文件名拼接，默认值：yy"),
) -> None:
    """将单个账单文件归一化为统一 Excel。"""
    normalize_bill(input_path, from_value)


@bill_app.command(name="analysis", help="分析归一化后的账单文件，添加用途和归属人列")  # type: ignore[misc]
def analyze_bill_command(
    input_path: str = typer.Argument(..., help="归一化后的账单xlsx文件路径"),
) -> None:
    """分析归一化后的账单文件，添加用途和归属人列。"""
    analyze_bill(input_path)


@bill_app.command(name="run", help="完整流程：原始账单 → 归一化 → 分析")  # type: ignore[misc]
def run_bill_command(
    input_path: str = typer.Argument(..., help="输入原始账单文件路径"),
    from_value: str | None = typer.Argument(None, help="from值，默认值：yy"),
) -> None:
    """完整流程：原始账单 → 归一化 → 分析。"""
    run_bill(input_path, from_value)


def normalize_bill(
    input_path: str,
    from_value: str | None,
) -> None:
    """将单个账单文件归一化为统一 Excel。"""
    # 如果用户没有传入from值，交互式引导输入
    if from_value is None:
        from_value = cast(str, typer.prompt("请输入from值", default="yy"))

    try:
        result = normalize_bill_file(input_path, from_value)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"输出文件: {result.output_path}")
    console.print(f"来源: {result.source}")
    console.print(f"读到的有效行数: {result.total_raw_data_rows}")
    console.print(f"输出的行数: {result.output_row_count}")

    if result.ignored_lines:
        # 超过20个行号就截断显示
        if len(result.ignored_lines) > 20:
            show_lines = list(map(str, result.ignored_lines[:20])) + ["..."]
        else:
            show_lines = list(map(str, result.ignored_lines))
        console.print(f"忽略的行号: {', '.join(show_lines)}")
    else:
        console.print("忽略的行号: 无")

    # 检查行数是否一致
    if result.total_raw_data_rows != result.output_row_count:
        console.print("\n❌ XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", style="bold red")
        console.print("❌ 警告：读到的有效行数和输出行数不一致！请检查忽略的行号是否合理", style="red")
        console.print("❌ XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n", style="bold red")
    else:
        console.print("\n✅ 归一化完成", style="green")


def analyze_bill(
    input_path: str,
) -> None:
    """分析归一化后的账单文件。"""
    try:
        result = analyze_bill_file(input_path)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"输出文件: {result.output_path}")
    console.print(f"总行数: {result.total_rows}")
    console.print(f"分析失败行数: {result.failed_rows}")
    console.print("\n✅ 分析完成", style="green")


def run_bill(
    input_path: str,
    from_value: str | None,
) -> None:
    """完整流程：原始账单 → 归一化 → 分析。"""
    if from_value is None:
        from_value = cast(str, typer.prompt("请输入from值", default="yy"))
    try:
        result = run_bill_pipeline(input_path, from_value)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc
    console.print(f"归一化输出: {result.normalized_output_path}")
    console.print(f"分析输出: {result.analysis_output_path}")
    console.print(f"来源: {result.source}")
    console.print(f"归一化行数: {result.normalized_row_count}")
    console.print(f"分析总行数: {result.analysis_total_rows}")
    console.print(f"分析失败行数: {result.analysis_failed_rows}")
    console.print("\n✅ 完整流程完成", style="green")


@bill_app.callback(invoke_without_command=True)  # type: ignore[misc]
def bill_callback(ctx: typer.Context) -> None:
    """处理默认调用：直接输入文件路径默认执行完整流程。"""
    if ctx.invoked_subcommand is not None:
        # 子命令被调用，无需处理
        return

    args = ctx.args
    if not args:
        # 无参数，显示帮助
        help_text = ctx.command.get_help(ctx)
        console.print(help_text)
        return

    first = args[0]
    if first in ["normalize", "analysis", "run"]:
        # 是已知子命令，但被当成 extra args 了，说明我们应该让 Typer 正常处理
        # 所以这种情况直接显示帮助
        help_text = ctx.command.get_help(ctx)
        console.print(help_text)
        return
    else:
        # 默认调用run
        input_path = first
        from_value = args[1] if len(args) > 1 else None
        run_bill(input_path, from_value)
