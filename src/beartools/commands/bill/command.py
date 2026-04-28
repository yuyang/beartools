"""账单处理命令模块。"""

from __future__ import annotations

import threading
from typing import cast

from rich.console import Console
import typer

from beartools.bill import BillRunProgressState, analyze_bill_file, normalize_bill_file, run_bill_pipeline

console = Console()


class _BillRunProgressReporter:
    """bill run 命令的终端进度播报器。"""

    def __init__(
        self,
        progress_state: BillRunProgressState,
        console_instance: Console,
        interval_seconds: float = 3.0,
    ) -> None:
        self._progress_state = progress_state
        self._console = console_instance
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._last_step = ""
        self._analysis_line_active = False

    def start(self) -> None:
        """启动后台播报线程。"""
        self._thread.start()

    def stop(self) -> None:
        """停止后台播报线程，并清理 analysis 刷新行。"""
        self._stop_event.set()
        self._thread.join(timeout=self._interval_seconds + 0.5)
        if self._analysis_line_active:
            self._console.file.write("\n")
            self._console.file.flush()
            self._analysis_line_active = False

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            self._render_once()

    def _render_once(self) -> None:
        step = self._progress_state.current_step
        if not step or step == "Pending":
            return

        if step != self._last_step:
            if self._analysis_line_active:
                self._console.file.write("\n")
                self._console.file.flush()
                self._analysis_line_active = False
            self._console.print(f"当前步骤: {step}")
            self._last_step = step

        if step == "Analysis":
            self._console.file.write(
                f"\r当前步骤: Analysis，已分析: {self._progress_state.analysis_completed_count}/{self._progress_state.analysis_total_count}"
            )
            self._console.file.flush()
            self._analysis_line_active = True


# 标准 Typer app，包含所有子命令
app = typer.Typer(help="账单处理相关操作，直接输入文件路径默认执行完整流程")


@app.command(name="normalize", help="将单个账单文件归一化为统一 Excel")  # type: ignore[misc]
def normalize_bill(
    input_path: str = typer.Argument(..., help="输入账单文件路径，支持 CSV/Excel"),
    from_value: str | None = typer.Argument(None, help="from 字段值，同时参与输出文件名拼接，默认值：yy"),
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


@app.command(name="analysis", help="分析归一化后的账单文件，添加用途和归属人列")  # type: ignore[misc]
def analyze_bill(
    input_path: str = typer.Argument(..., help="归一化后的账单xlsx文件路径"),
) -> None:
    """分析归一化后的账单文件，每行自动分析交易用途和归属人并输出结果文件。"""

    try:
        result = analyze_bill_file(input_path)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"输出文件: {result.output_path}")
    console.print(f"总行数: {result.total_rows}")
    console.print(f"分析失败行数: {result.failed_rows}")
    console.print("\n✅ 分析完成", style="green")


@app.command(name="run", help="完整流程：原始账单 → 归一化 → 分析")  # type: ignore[misc]
def run_bill(
    input_path: str = typer.Argument(..., help="输入账单文件路径，支持 CSV/Excel"),
    from_value: str | None = typer.Argument(None, help="from 字段值，同时参与输出文件名拼接，默认值：yy"),
) -> None:
    """完整流程：原始账单 → 归一化 → 分析。"""

    if from_value is None:
        from_value = cast(str, typer.prompt("请输入from值", default="yy"))

    progress_state = BillRunProgressState()
    reporter = _BillRunProgressReporter(progress_state, console)
    reporter_stopped = False

    try:
        reporter.start()
        result = run_bill_pipeline(input_path, from_value, progress_state=progress_state)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        reporter.stop()
        reporter_stopped = True
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc
    finally:
        if not reporter_stopped:
            reporter.stop()

    console.print(f"归一化输出: {result.normalized_output_path}")
    console.print(f"分析输出: {result.analysis_output_path}")
    console.print(f"来源: {result.source}")
    console.print(f"归一化行数: {result.normalized_row_count}")
    console.print(f"分析总行数: {result.analysis_total_rows}")
    console.print(f"分析失败行数: {result.analysis_failed_rows}")
    console.print("\n✅ 完整流程完成", style="green")
