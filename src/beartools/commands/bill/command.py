"""账单处理命令模块。"""

from __future__ import annotations

from typing import cast

from rich.console import Console
import typer

from beartools.bill import analyze_bill_file, normalize_bill_file, run_bill_pipeline

console = Console()


def normalize_bill(
    input_path: str,
    from_value: str | None,
) -> None:
    """将单个账单文件归一化为统一 Excel。"""
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
        if len(result.ignored_lines) > 20:
            show_lines = list(map(str, result.ignored_lines[:20])) + ["..."]
        else:
            show_lines = list(map(str, result.ignored_lines))
        console.print(f"忽略的行号: {', '.join(show_lines)}")
    else:
        console.print("忽略的行号: 无")

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


def bill_command(
    ctx: typer.Context,
    args: list[str] = typer.Argument(None, help="原始账单文件路径，或子命令参数"),  # noqa: B008
) -> None:
    """账单处理相关操作，直接输入文件路径默认执行完整流程。

    子命令:
      normalize 将单个账单文件归一化为统一 Excel
      analysis  分析归一化后的账单文件，添加用途和归属人列
      run       完整流程：原始账单 → 归一化 → 分析
    """
    if not args:
        console.print(ctx.command.get_help(ctx))
        return

    first = args[0]
    if first in ["-h", "--help"]:
        console.print(ctx.command.get_help(ctx))
        return
    elif first == "normalize":
        input_path = args[1] if len(args) > 1 else None
        if input_path is None:
            console.print(ctx.command.get_help(ctx))
            return
        from_value = args[2] if len(args) > 2 else None
        normalize_bill(input_path, from_value)
    elif first == "analysis":
        input_path = args[1] if len(args) > 1 else None
        if input_path is None:
            console.print(ctx.command.get_help(ctx))
            return
        analyze_bill(input_path)
    elif first == "run":
        input_path = args[1] if len(args) > 1 else None
        if input_path is None:
            console.print(ctx.command.get_help(ctx))
            return
        from_value = args[2] if len(args) > 2 else None
        run_bill(input_path, from_value)
    else:
        input_path = first
        from_value = args[1] if len(args) > 1 else None
        run_bill(input_path, from_value)
