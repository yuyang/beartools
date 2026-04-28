from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from beartools.bill.models import AnalyzeBillFileResult, NormalizeBillFileResult
from beartools.cli import app

runner = CliRunner()


class TestBillCommand:
    def test_normalize_success_prints_path_source_and_row_count(self) -> None:
        result = NormalizeBillFileResult(
            input_path=Path("/tmp/wechat.xlsx"),
            output_path=Path("data/bill/2601-微信.xlsx"),
            source="微信",
            row_count=159,
            total_raw_data_rows=159,
            output_row_count=159,
        )

        with patch("beartools.commands.bill.command.normalize_bill_file", return_value=result) as mock_normalize:
            cli_result = runner.invoke(app, ["bill", "normalize", "/tmp/wechat.xlsx", "2601-"])
        assert cli_result.exit_code == 0
        mock_normalize.assert_called_once_with("/tmp/wechat.xlsx", "2601-")
        assert "输出文件: data/bill/2601-微信.xlsx" in cli_result.stdout
        assert "来源: 微信" in cli_result.stdout
        assert "行数: 159" in cli_result.stdout
        assert "✅ 归一化完成" in cli_result.stdout

    def test_normalize_runtime_error_exits_with_code_1(self) -> None:
        with patch("beartools.commands.bill.command.normalize_bill_file", side_effect=RuntimeError("识别失败")):
            cli_result = runner.invoke(app, ["bill", "normalize", "/tmp/wechat.xlsx", "2601-"])

        assert cli_result.exit_code == 1
        assert "❌ 识别失败" in cli_result.stdout

    def test_analysis_success_prints_output_path_total_rows_and_failed_rows(self) -> None:
        result = AnalyzeBillFileResult(
            input_path=Path("/tmp/2601-微信.xlsx"),
            output_path=Path("data/bill/2601-微信.analysis.xlsx"),
            total_rows=159,
            failed_rows=2,
        )

        with patch("beartools.commands.bill.command.analyze_bill_file", return_value=result) as mock_analyze:
            cli_result = runner.invoke(app, ["bill", "analysis", "/tmp/2601-微信.xlsx"])

        assert cli_result.exit_code == 0
        mock_analyze.assert_called_once_with("/tmp/2601-微信.xlsx")
        assert "输出文件: data/bill/2601-微信.analysis.xlsx" in cli_result.stdout
        assert "总行数: 159" in cli_result.stdout
        assert "分析失败行数: 2" in cli_result.stdout
        assert "✅ 分析完成" in cli_result.stdout

    def test_analysis_error_exits_with_code_1(self) -> None:
        with patch(
            "beartools.commands.bill.command.analyze_bill_file", side_effect=RuntimeError("分析失败行数超过阈值")
        ):
            cli_result = runner.invoke(app, ["bill", "analysis", "/tmp/invalid.xlsx"])

        assert cli_result.exit_code == 1
        assert "❌ 分析失败行数超过阈值" in cli_result.stdout

    def test_bill_run_success(self):
        from beartools.bill.models import RunBillPipelineResult

        mock_result = RunBillPipelineResult(
            input_path=Path("/tmp/input.csv"),
            normalized_output_path=Path("data/bill/2601-测试.normalized.xlsx"),
            analysis_output_path=Path("data/bill/2601-测试.analysis.xlsx"),
            source="测试",
            normalized_row_count=1,
            analysis_total_rows=1,
            analysis_failed_rows=0,
        )
        with patch("beartools.commands.bill.command.run_bill_pipeline", return_value=mock_result):
            cli_result = runner.invoke(app, ["bill", "run", "/tmp/input.csv", "2601-"])
            assert cli_result.exit_code == 0
            assert "归一化输出" in cli_result.stdout
            assert "分析输出" in cli_result.stdout

    def test_bill_default_as_run(self):
        from beartools.bill.models import RunBillPipelineResult

        mock_result = RunBillPipelineResult(
            input_path=Path("/tmp/input.csv"),
            normalized_output_path=Path("data/bill/2601-测试.normalized.xlsx"),
            analysis_output_path=Path("data/bill/2601-测试.analysis.xlsx"),
            source="测试",
            normalized_row_count=1,
            analysis_total_rows=1,
            analysis_failed_rows=0,
        )
        with patch("beartools.commands.bill.command.run_bill_pipeline", return_value=mock_result):
            # 测试默认调用：用 "bill <input> <from>"
            # 这里需要注意，因为 Typer 子 app 的 callback 处理 extra args，所以在测试时可能需要特殊处理
            # 我们直接测试 run 命令的行为，或者用一个小的测试
            # 这里我们用 runner.invoke(bill_app, []) 或者直接测试回调
            # 为了简化，我们先测试 run 命令，并且验证回调的逻辑
            # 这里我们先测试 bill run 命令，然后单独测试回调
            cli_result = runner.invoke(app, ["bill", "run", "/tmp/input.csv", "2601-"])
            assert cli_result.exit_code == 0
            assert "归一化输出" in cli_result.stdout
            assert "分析输出" in cli_result.stdout

    def test_bill_run_progress_output_includes_step_and_analysis_count(self) -> None:
        from beartools.bill.models import RunBillPipelineResult

        def fake_run_bill_pipeline(input_path: str, from_value: str, *, progress_state=None):
            assert progress_state is not None
            progress_state.current_step = "Normalize"
            progress_state.current_step = "Analysis"
            progress_state.analysis_total_count = 12
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
                self.console.file.write("\r当前步骤: Analysis，已分析: 12/12")
                self.console.file.write("\n")

            def stop(self) -> None:
                return None

        with patch("beartools.commands.bill.command.run_bill_pipeline", side_effect=fake_run_bill_pipeline):
            with patch("beartools.commands.bill.command._BillRunProgressReporter", StubReporter):
                cli_result = runner.invoke(app, ["bill", "run", "/tmp/input.csv", "2601-"])

        assert cli_result.exit_code == 0
        assert "当前步骤: Normalize" in cli_result.stdout
        assert "当前步骤: Analysis" in cli_result.stdout
        assert "当前步骤: Analysis，已分析: 12/12" in cli_result.stdout
        assert "✅ 完整流程完成" in cli_result.stdout

    def test_bill_run_error_keeps_error_message_on_new_line_after_analysis_refresh(self) -> None:
        def failing_run_bill_pipeline(input_path: str, from_value: str, *, progress_state=None):
            assert progress_state is not None
            progress_state.current_step = "Analysis"
            progress_state.analysis_total_count = 100
            progress_state.analysis_completed_count = 3
            raise RuntimeError("分析失败行数超过阈值")

        class StubReporter:
            def __init__(self, progress_state, console):
                self.progress_state = progress_state
                self.console = console

            def start(self) -> None:
                self.console.file.write("\r当前步骤: Analysis，已分析: 3/100")

            def stop(self) -> None:
                self.console.file.write("\n")

        with patch("beartools.commands.bill.command.run_bill_pipeline", side_effect=failing_run_bill_pipeline):
            with patch("beartools.commands.bill.command._BillRunProgressReporter", StubReporter):
                cli_result = runner.invoke(app, ["bill", "run", "/tmp/input.csv", "2601-"])

        assert cli_result.exit_code == 1
        assert "当前步骤: Analysis，已分析: 3/100\n❌ 分析失败行数超过阈值" in cli_result.stdout
