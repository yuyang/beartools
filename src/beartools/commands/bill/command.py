"""账单处理命令模块。"""

from __future__ import annotations

from rich.console import Console
import typer

from beartools.bill import normalize_bill_file

console = Console()
app = typer.Typer(help="账单处理相关操作")


@app.command(name="normalize", help="将单个账单文件归一化为统一 CSV")  # type: ignore
def normalize_bill(
    input_path: str = typer.Argument(..., help="输入账单文件路径"),
    from_value: str = typer.Argument(..., help="from 字段值，同时参与输出文件名拼接"),
) -> None:
    """将单个账单文件归一化为统一 CSV。"""

    try:
        result = normalize_bill_file(input_path, from_value)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"输出文件: {result.output_csv_path}")
    console.print(f"来源: {result.source}")
    console.print(f"行数: {result.row_count}")
    console.print("✅ 归一化完成", style="green")
