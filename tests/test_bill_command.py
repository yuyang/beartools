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
            print("stdout:", cli_result.stdout)
            print("stderr:", cli_result.stderr)
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
            cli_result = runner.invoke(app, ["bill", "/tmp/input.csv", "2601-"])
            print("stdout:", cli_result.stdout)
            print("stderr:", cli_result.stderr)
            assert cli_result.exit_code == 0
