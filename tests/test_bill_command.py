from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from beartools.bill.models import NormalizeBillFileResult
from beartools.cli import app

runner = CliRunner()


class TestBillCommand:
    def test_normalize_success_prints_path_source_and_row_count(self) -> None:
        result = NormalizeBillFileResult(
            input_path=Path("/tmp/wechat.xlsx"),
            output_csv_path=Path("data/bill/2601-微信.csv"),
            source="微信",
            row_count=159,
        )

        with patch("beartools.commands.bill.command.normalize_bill_file", return_value=result) as mock_normalize:
            cli_result = runner.invoke(app, ["bill", "normalize", "/tmp/wechat.xlsx", "2601-"])

        assert cli_result.exit_code == 0
        mock_normalize.assert_called_once_with("/tmp/wechat.xlsx", "2601-")
        assert "输出文件: data/bill/2601-微信.csv" in cli_result.stdout
        assert "来源: 微信" in cli_result.stdout
        assert "行数: 159" in cli_result.stdout
        assert "✅ 归一化完成" in cli_result.stdout

    def test_normalize_runtime_error_exits_with_code_1(self) -> None:
        with patch("beartools.commands.bill.command.normalize_bill_file", side_effect=RuntimeError("识别失败")):
            cli_result = runner.invoke(app, ["bill", "normalize", "/tmp/wechat.xlsx", "2601-"])

        assert cli_result.exit_code == 1
        assert "❌ 识别失败" in cli_result.stdout
