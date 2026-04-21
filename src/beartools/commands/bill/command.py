"""账单处理命令模块。"""

from __future__ import annotations

from typing import cast

from rich.console import Console
import typer

from beartools.bill import normalize_bill_file

console = Console()
app = typer.Typer(help="账单处理相关操作")


@app.command(name="normalize", help="将单个账单文件归一化为统一 CSV")  # type: ignore
def normalize_bill(
    input_path: str = typer.Argument(..., help="输入账单文件路径"),
    from_value: str | None = typer.Argument(None, help="from 字段值，同时参与输出文件名拼接，默认值：yy"),
) -> None:
    """将单个账单文件归一化为统一 CSV。"""

    # 如果用户没有传入from值，交互式引导输入
    if from_value is None:
        from_value = cast(str, typer.prompt("请输入from值", default="yy"))

    try:
        result = normalize_bill_file(input_path, from_value)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"输出文件: {result.output_csv_path}")
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
