# bill run 进度输出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `bill run` 增加每 3 秒一次的步骤播报，并在 `Analysis` 阶段显示已完成分析总数。

**Architecture:** 在 `service` 层新增一个轻量进度状态对象，由 `run_bill_pipeline()` 和 `analyze_bill_file()` 负责推进状态；在 `command` 层新增一个后台播报器线程，普通步骤继续用 `Console.print()` 换行输出，`Analysis` 阶段用 `sys.stdout.write("\r...")` 覆盖同一行刷新。测试按 TDD 拆成 service 状态推进与 command 输出协调两条线。

**Tech Stack:** Python 3.13、Typer、Rich、pytest、openpyxl、threading、sys.stdout

---

## 文件结构

- 修改 `src/beartools/bill/models.py`
  - 新增 `BillRunProgressState` 数据类，承载 `current_step` 与 `analysis_completed_count`。
- 修改 `src/beartools/bill/service.py`
  - 为 `analyze_bill_file()`、`_process_data_rows()`、`run_bill_pipeline()` 增加可选 `progress_state` 参数，并在关键阶段更新状态。
- 修改 `src/beartools/bill/__init__.py`
  - 导出 `BillRunProgressState`，便于 command 层导入。
- 修改 `src/beartools/commands/bill/command.py`
  - 新增 `_BillRunProgressReporter`，协调 `Console.print()` 与 `sys.stdout.write()`。
- 修改 `tests/test_bill_service.py`
  - 为进度状态推进与 analysis 计数编写失败-通过测试。
- 修改 `tests/test_bill_command.py`
  - 为 `bill run` 进度输出与异常换行收尾编写失败-通过测试。

### Task 1: 定义进度状态模型与 service 侧失败测试

**Files:**
- Modify: `src/beartools/bill/models.py:146-156`
- Modify: `src/beartools/bill/__init__.py:5-7`
- Test: `tests/test_bill_service.py:347-438`

- [ ] **Step 1: 写失败测试，锁定 progress_state 的 service 行为**

在 `tests/test_bill_service.py` 末尾追加以下两个测试：

```python
def test_run_bill_pipeline_updates_progress_state(tmp_path: Path) -> None:
    import os

    from beartools.bill.models import (
        BillAnalysisResult,
        BillFieldDetail,
        BillFieldMapping,
        BillRemarkColumns,
        BillRunProgressState,
        BillStructureFileResult,
    )
    from beartools.bill.service import run_bill_pipeline

    input_csv = tmp_path / "test.csv"
    input_csv.write_text(
        "导出信息\n交易时间,交易分类,交易对方,金额,交易状态,收/支,备注\n"
        "2025-12-31 18:54:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n",
        encoding="utf-8",
    )
    structure = BillStructureFileResult(
        file_name="test.csv",
        source="测试账单",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(column_name="交易时间", confidence="high", reason=""),
            counterparty=BillFieldDetail(column_name="交易对方", confidence="high", reason=""),
            amount=BillFieldDetail(column_name="金额", confidence="high", reason=""),
            status=BillFieldDetail(column_name="交易状态", confidence="high", reason=""),
            remark_columns=BillRemarkColumns(column_names=["交易分类", "收/支", "备注"], confidence="high", reason=""),
        ),
    )
    progress_state = BillRunProgressState()

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = run_bill_pipeline(
            input_csv,
            "2601-",
            structure_resolver=lambda _: structure,
            row_analyzer=lambda *args: BillAnalysisResult(purpose="测试用途", owner="vv"),
            progress_state=progress_state,
        )
    finally:
        os.chdir(cwd)

    assert result.analysis_total_rows == 1
    assert progress_state.current_step == "Finished"
    assert progress_state.analysis_completed_count == 1


def test_analyze_bill_file_counts_completed_rows_even_when_row_falls_back_to_unknow(tmp_path: Path) -> None:
    from openpyxl import Workbook

    from beartools.bill.models import BillRunProgressState
    from beartools.bill.service import analyze_bill_file

    input_path = tmp_path / "test.xlsx"

    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.append(["原始来源", "交易时间", "交易对方", "金额", "交易状态", "注意", "备注"])
    worksheet.append(["2601-支付宝", "2025-12-31 18:54:05", "山姆会员商店", "289.80", "交易成功", "", "日用百货"])
    worksheet.append(["2601-支付宝", "2025-12-31 18:55:05", "盒马", "19.80", "交易成功", "", "零食"])
    workbook.save(input_path)

    progress_state = BillRunProgressState()

    def mixed_row_analyzer(counterparty: str, remark: str, status: str, amount: str):
        if counterparty == "盒马":
            raise RuntimeError("分析失败")
        from beartools.bill.models import BillAnalysisResult

        return BillAnalysisResult(purpose="食物", owner="yy")

    result = analyze_bill_file(input_path, row_analyzer=mixed_row_analyzer, progress_state=progress_state)

    assert result.total_rows == 2
    assert result.failed_rows == 1
    assert progress_state.current_step == "Analysis"
    assert progress_state.analysis_completed_count == 2
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run: `uv run pytest tests/test_bill_service.py::test_run_bill_pipeline_updates_progress_state tests/test_bill_service.py::test_analyze_bill_file_counts_completed_rows_even_when_row_falls_back_to_unknow -xvs`

Expected: FAIL，报错包含 `cannot import name 'BillRunProgressState'` 或 `unexpected keyword argument 'progress_state'`。

- [ ] **Step 3: 最小实现进度状态模型与导出**

将 `src/beartools/bill/models.py` 末尾改为：

```python
@dataclass(slots=True)
class RunBillPipelineResult:
    """run_bill_pipeline的结果。"""

    input_path: Path
    normalized_output_path: Path
    analysis_output_path: Path
    source: str
    normalized_row_count: int
    analysis_total_rows: int
    analysis_failed_rows: int


@dataclass(slots=True)
class BillRunProgressState:
    """bill run 运行中的轻量进度状态。"""

    current_step: str = "Pending"
    analysis_completed_count: int = 0
```

将 `src/beartools/bill/__init__.py` 改为：

```python
"""账单归一化与分析模块。"""

from __future__ import annotations

from .models import BillRunProgressState
from .service import analyze_bill_file, normalize_bill_file, run_bill_pipeline

__all__ = ["normalize_bill_file", "analyze_bill_file", "run_bill_pipeline", "BillRunProgressState"]
```

- [ ] **Step 4: 运行测试，确认还剩 service 参数相关失败**

Run: `uv run pytest tests/test_bill_service.py::test_run_bill_pipeline_updates_progress_state tests/test_bill_service.py::test_analyze_bill_file_counts_completed_rows_even_when_row_falls_back_to_unknow -xvs`

Expected: FAIL，报错包含 `unexpected keyword argument 'progress_state'`。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/bill/models.py src/beartools/bill/__init__.py tests/test_bill_service.py
git commit -m "ADD: 增加 bill run 进度状态模型"
```

### Task 2: 实现 service 进度推进并让 service 测试转绿

**Files:**
- Modify: `src/beartools/bill/service.py:15-24`
- Modify: `src/beartools/bill/service.py:279-325`
- Modify: `src/beartools/bill/service.py:355-394`
- Modify: `src/beartools/bill/service.py:443-473`
- Test: `tests/test_bill_service.py:347-438`

- [ ] **Step 1: 先让现有新增测试稳定失败**

Run: `uv run pytest tests/test_bill_service.py::test_run_bill_pipeline_updates_progress_state tests/test_bill_service.py::test_analyze_bill_file_counts_completed_rows_even_when_row_falls_back_to_unknow -xvs`

Expected: FAIL，失败原因仍是 `progress_state` 参数尚未实现。

- [ ] **Step 2: 在 service 中加入 progress_state 参数与状态推进**

将 `src/beartools/bill/service.py` 的相关定义按下列方式修改：

```python
from .models import (
    AnalyzeBillFileResult,
    BillAnalysisResult,
    BillFieldMapping,
    BillRunProgressState,
    BillStructureFileResult,
    NormalizeBillFileResult,
    NormalizedBillRow,
    RunBillPipelineResult,
)


def analyze_bill_file(
    input_path: str | Path,
    *,
    row_analyzer: Callable[[str, str, str, str], BillAnalysisResult] = analyze_bill_row,
    progress_state: BillRunProgressState | None = None,
) -> AnalyzeBillFileResult:
    """分析归一化后的账单文件，每行分析得到用途和归属人，追加列输出到新文件。"""
    input_path = Path(input_path)

    if progress_state is not None:
        progress_state.current_step = "Analysis"

    if input_path.suffix.lower() != ".xlsx":
        raise ValueError("只支持归一化结果 .xlsx 输入")

    wb = load_workbook(input_path)
    ws = wb.active
    if ws is None or ws.max_row < 1:
        raise RuntimeError("输入文件为空工作表")

    headers = _load_and_validate_headers(ws)
    column_index_map = {header: idx for idx, header in enumerate(headers)}
    processed_rows = _prepare_output_headers(headers)

    total_rows, failed_count = _process_data_rows(
        ws,
        column_index_map,
        processed_rows,
        row_analyzer,
        input_path,
        progress_state,
    )

    output_path = _write_analysis_output(input_path, processed_rows)

    return AnalyzeBillFileResult(
        input_path=input_path,
        output_path=output_path,
        total_rows=total_rows,
        failed_rows=failed_count,
    )


def _process_data_rows(
    ws: Worksheet,
    column_index_map: dict[str, int],
    processed_rows: list[list[str | None]],
    row_analyzer: Callable[[str, str, str, str], BillAnalysisResult],
    input_path: Path,
    progress_state: BillRunProgressState | None = None,
) -> tuple[int, int]:
    """处理所有数据行，执行分析并收集结果。"""
    failed_count = 0
    total_rows = 0

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        total_rows += 1
        original_values = _extract_original_row_values(row)

        counterparty = original_values[column_index_map["交易对方"]] or ""
        remark = original_values[column_index_map["备注"]] or ""
        status = original_values[column_index_map["交易状态"]] or ""
        amount = original_values[column_index_map["金额"]] or ""

        purpose, owner = _analyze_single_row(counterparty, remark, status, amount, row_analyzer)

        if progress_state is not None:
            progress_state.analysis_completed_count += 1

        if purpose == "unknow" and owner == "unknow":
            failed_count += 1

        if failed_count > _MAX_FAILURE_ROWS:
            output_path = input_path.with_name(f"{input_path.stem}.analysis.xlsx")
            if output_path.exists():
                output_path.unlink()
            raise RuntimeError(f"分析失败行数超过阈值({_MAX_FAILURE_ROWS})，已达到 {failed_count} 行，终止处理")

        original_values.append(purpose)
        original_values.append(owner)
        processed_rows.append(original_values)

    return total_rows, failed_count


def run_bill_pipeline(
    input_path: str | Path,
    from_value: str,
    *,
    structure_resolver: Callable[[Path], BillStructureFileResult] | None = None,
    row_analyzer: Callable[[str, str, str, str], BillAnalysisResult] = analyze_bill_row,
    progress_state: BillRunProgressState | None = None,
) -> RunBillPipelineResult:
    """串联 normalize 与 analysis，完成从原始账单到最终分析的完整流程。"""
    input_path_obj = Path(input_path)

    if progress_state is not None:
        progress_state.current_step = "Normalize"
        progress_state.analysis_completed_count = 0

    normalize_result = normalize_bill_file(input_path_obj, from_value, structure_resolver=structure_resolver)

    try:
        analyze_result = analyze_bill_file(
            normalize_result.output_path,
            row_analyzer=row_analyzer,
            progress_state=progress_state,
        )
    except Exception:
        candidate = normalize_result.output_path.with_suffix("").with_suffix(".analysis.xlsx")
        if candidate.exists():
            candidate.unlink()
        raise

    if progress_state is not None:
        progress_state.current_step = "Finished"

    return RunBillPipelineResult(
        input_path=input_path_obj,
        normalized_output_path=normalize_result.output_path,
        analysis_output_path=analyze_result.output_path,
        source=normalize_result.source,
        normalized_row_count=normalize_result.output_row_count,
        analysis_total_rows=analyze_result.total_rows,
        analysis_failed_rows=analyze_result.failed_rows,
    )
```

- [ ] **Step 3: 运行新增 service 测试，确认转绿**

Run: `uv run pytest tests/test_bill_service.py::test_run_bill_pipeline_updates_progress_state tests/test_bill_service.py::test_analyze_bill_file_counts_completed_rows_even_when_row_falls_back_to_unknow -xvs`

Expected: PASS。

- [ ] **Step 4: 运行 bill service 全量测试，确认无回归**

Run: `uv run pytest tests/test_bill_service.py -xvs`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/bill/service.py tests/test_bill_service.py
git commit -m "MOD: 增加 bill run 进度状态推进"
```

### Task 3: 为 command 层写进度输出失败测试

**Files:**
- Modify: `tests/test_bill_command.py:1-108`
- Modify: `src/beartools/commands/bill/command.py:1-96`

- [ ] **Step 1: 写 command 侧失败测试，锁定播报器的输出契约**

在 `tests/test_bill_command.py` 末尾追加以下测试：

```python
    def test_bill_run_progress_output_includes_step_and_analysis_count(self) -> None:
        from beartools.bill.models import RunBillPipelineResult

        def fake_run_bill_pipeline(input_path: str, from_value: str, *, progress_state=None):
            assert progress_state is not None
            progress_state.current_step = "Normalize"
            progress_state.current_step = "Analysis"
            progress_state.analysis_completed_count = 12
            progress_state.current_step = "Finished"
            return RunBillPipelineResult(
                input_path=Path(input_path),
                normalized_output_path=Path("data/bill/2601-测试.normalized.xlsx"),
                analysis_output_path=Path("data/bill/2601-测试.analysis.xlsx"),
                source="测试",
                normalized_row_count=12,
                analysis_total_rows=12,
                analysis_failed_rows=0,
            )

        class StubReporter:
            def __init__(self, progress_state, console):
                self.progress_state = progress_state
                self.console = console

            def start(self) -> None:
                self.console.print("当前步骤: Normalize")
                self.console.print("当前步骤: Analysis")
                self.console.file.write("\r当前步骤: Analysis，已分析: 12")
                self.console.file.write("\n")

            def stop(self) -> None:
                return None

        with patch("beartools.commands.bill.command.run_bill_pipeline", side_effect=fake_run_bill_pipeline):
            with patch("beartools.commands.bill.command._BillRunProgressReporter", StubReporter):
                cli_result = runner.invoke(app, ["bill", "run", "/tmp/input.csv", "2601-"])

        assert cli_result.exit_code == 0
        assert "当前步骤: Normalize" in cli_result.stdout
        assert "当前步骤: Analysis" in cli_result.stdout
        assert "当前步骤: Analysis，已分析: 12" in cli_result.stdout
        assert "✅ 完整流程完成" in cli_result.stdout


    def test_bill_run_error_keeps_error_message_on_new_line_after_analysis_refresh(self) -> None:
        def failing_run_bill_pipeline(input_path: str, from_value: str, *, progress_state=None):
            assert progress_state is not None
            progress_state.current_step = "Analysis"
            progress_state.analysis_completed_count = 3
            raise RuntimeError("分析失败行数超过阈值")

        class StubReporter:
            def __init__(self, progress_state, console):
                self.progress_state = progress_state
                self.console = console

            def start(self) -> None:
                self.console.file.write("\r当前步骤: Analysis，已分析: 3")

            def stop(self) -> None:
                self.console.file.write("\n")

        with patch("beartools.commands.bill.command.run_bill_pipeline", side_effect=failing_run_bill_pipeline):
            with patch("beartools.commands.bill.command._BillRunProgressReporter", StubReporter):
                cli_result = runner.invoke(app, ["bill", "run", "/tmp/input.csv", "2601-"])

        assert cli_result.exit_code == 1
        assert "当前步骤: Analysis，已分析: 3\n❌ 分析失败行数超过阈值" in cli_result.stdout
```

- [ ] **Step 2: 运行新增 command 测试，确认当前失败**

Run: `uv run pytest tests/test_bill_command.py::TestBillCommand::test_bill_run_progress_output_includes_step_and_analysis_count tests/test_bill_command.py::TestBillCommand::test_bill_run_error_keeps_error_message_on_new_line_after_analysis_refresh -xvs`

Expected: FAIL，报错包含 `module 'beartools.commands.bill.command' has no attribute '_BillRunProgressReporter'`，或 `fake_run_bill_pipeline() got an unexpected keyword argument 'progress_state'`。

- [ ] **Step 3: Commit**

```bash
git add tests/test_bill_command.py
git commit -m "ADD: 增加 bill run 进度输出测试"
```

### Task 4: 实现 command 层播报器并让 command 测试转绿

**Files:**
- Modify: `src/beartools/commands/bill/command.py:1-96`
- Test: `tests/test_bill_command.py:1-108`

- [ ] **Step 1: 保持 command 测试处于失败状态后开始实现**

Run: `uv run pytest tests/test_bill_command.py::TestBillCommand::test_bill_run_progress_output_includes_step_and_analysis_count tests/test_bill_command.py::TestBillCommand::test_bill_run_error_keeps_error_message_on_new_line_after_analysis_refresh -xvs`

Expected: FAIL。

- [ ] **Step 2: 在 command 中实现播报器与 `bill run` 集成**

将 `src/beartools/commands/bill/command.py` 改为如下结构（保留现有 `normalize` 与 `analysis` 命令，仅新增 imports、helper class 与 `run_bill` 中的调用）：

```python
"""账单处理命令模块。"""

from __future__ import annotations

from typing import cast
import sys
import threading
import time

from rich.console import Console
import typer

from beartools.bill import BillRunProgressState, analyze_bill_file, normalize_bill_file, run_bill_pipeline

console = Console()


class _BillRunProgressReporter:
    """bill run 的终端进度播报器。"""

    def __init__(self, progress_state: BillRunProgressState, console_instance: Console, interval_seconds: float = 3.0) -> None:
        self._progress_state = progress_state
        self._console = console_instance
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._last_step = ""
        self._analysis_line_active = False

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
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
                f"\r当前步骤: Analysis，已分析: {self._progress_state.analysis_completed_count}"
            )
            self._console.file.flush()
            self._analysis_line_active = True


@app.command(name="run", help="完整流程：原始账单 → 归一化 → 分析")
def run_bill(
    input_path: str = typer.Argument(..., help="输入账单文件路径，支持 CSV/Excel"),
    from_value: str | None = typer.Argument(None, help="from 字段值，同时参与输出文件名拼接，默认值：yy"),
) -> None:
    """完整流程：原始账单 → 归一化 → 分析。"""

    if from_value is None:
        from_value = cast(str, typer.prompt("请输入from值", default="yy"))

    progress_state = BillRunProgressState()
    reporter = _BillRunProgressReporter(progress_state, console)

    try:
        reporter.start()
        result = run_bill_pipeline(input_path, from_value, progress_state=progress_state)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        reporter.stop()
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc
    else:
        reporter.stop()

    console.print(f"归一化输出: {result.normalized_output_path}")
    console.print(f"分析输出: {result.analysis_output_path}")
    console.print(f"来源: {result.source}")
    console.print(f"归一化行数: {result.normalized_row_count}")
    console.print(f"分析总行数: {result.analysis_total_rows}")
    console.print(f"分析失败行数: {result.analysis_failed_rows}")
    console.print("\n✅ 完整流程完成", style="green")
```

实现时按项目风格整理 import 顺序，删除未使用 import；如果 `sys` 或 `time` 未实际使用，不要保留。

- [ ] **Step 3: 运行新增 command 测试，确认转绿**

Run: `uv run pytest tests/test_bill_command.py::TestBillCommand::test_bill_run_progress_output_includes_step_and_analysis_count tests/test_bill_command.py::TestBillCommand::test_bill_run_error_keeps_error_message_on_new_line_after_analysis_refresh -xvs`

Expected: PASS。

- [ ] **Step 4: 运行 bill command 全量测试，确认无回归**

Run: `uv run pytest tests/test_bill_command.py -xvs`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/commands/bill/command.py tests/test_bill_command.py
git commit -m "MOD: 增加 bill run 进度播报"
```

### Task 5: 全量校验与收尾

**Files:**
- Modify: `src/beartools/bill/models.py`
- Modify: `src/beartools/bill/__init__.py`
- Modify: `src/beartools/bill/service.py`
- Modify: `src/beartools/commands/bill/command.py`
- Modify: `tests/test_bill_service.py`
- Modify: `tests/test_bill_command.py`

- [ ] **Step 1: 运行账单相关测试**

Run: `uv run pytest tests/test_bill_service.py tests/test_bill_command.py -xvs`

Expected: PASS。

- [ ] **Step 2: 运行 ruff 检查**

Run: `uv run ruff check src/beartools/bill src/beartools/commands/bill tests/test_bill_service.py tests/test_bill_command.py`

Expected: `All checks passed!`

- [ ] **Step 3: 运行 mypy 检查**

Run: `uv run mypy src/beartools/bill src/beartools/commands/bill/command.py`

Expected: `Success: no issues found`

- [ ] **Step 4: 如有格式化差异则修复并复检**

Run: `uv run ruff format src/beartools/bill src/beartools/commands/bill tests/test_bill_service.py tests/test_bill_command.py && uv run ruff check src/beartools/bill src/beartools/commands/bill tests/test_bill_service.py tests/test_bill_command.py && uv run mypy src/beartools/bill src/beartools/commands/bill/command.py`

Expected: 格式化完成后，ruff 与 mypy 继续通过。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/bill/models.py src/beartools/bill/__init__.py src/beartools/bill/service.py src/beartools/commands/bill/command.py tests/test_bill_service.py tests/test_bill_command.py
git commit -m "MOD: 增强 bill run 运行进度输出"
```
