from __future__ import annotations

import os
from pathlib import Path

from openpyxl import Workbook


def test_normalize_bill_file_with_csv(tmp_path: Path) -> None:
    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult
    from beartools.bill.service import normalize_bill_file

    input_path = tmp_path / "alipay.csv"
    input_path.write_text(
        "导出信息\n交易时间,交易分类,交易对方,金额,交易状态,收/支,备注\n"
        "2025-12-31 18:54:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n",
        encoding="utf-8",
    )

    structure = BillStructureFileResult(
        file_name=input_path.name,
        source="支付宝",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(column_name="交易时间", confidence="high", reason=""),
            counterparty=BillFieldDetail(column_name="交易对方", confidence="high", reason=""),
            amount=BillFieldDetail(column_name="金额", confidence="high", reason=""),
            status=BillFieldDetail(column_name="交易状态", confidence="high", reason=""),
            remark_columns=BillRemarkColumns(
                column_names=["交易分类", "收/支", "备注"],
                confidence="high",
                reason="",
            ),
        ),
        sample_rows=[],
        notes=[],
    )

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = normalize_bill_file(input_path, "2601-", structure_resolver=lambda _: structure)

        assert result.source == "支付宝"
        assert result.row_count == 1
        assert result.output_path == Path("data/bill/2601-支付宝.xlsx")
    finally:
        os.chdir(cwd)


def test_normalize_bill_file_with_xlsx(tmp_path: Path) -> None:
    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult
    from beartools.bill.service import normalize_bill_file

    input_path = tmp_path / "wechat.xlsx"

    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "微信支付账单明细"
    sheet.append(["交易时间", "交易类型", "交易对方", "金额(元)", "当前状态", "支付方式", "备注"])
    sheet.append(["2026-01-01 19:43:53", "商户消费", "京东七鲜超市", "¥61.60", "支付成功", "零钱", "/"])
    workbook.save(input_path)

    structure = BillStructureFileResult(
        file_name=input_path.name,
        source="微信",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(column_name="交易时间", confidence="high", reason=""),
            counterparty=BillFieldDetail(column_name="交易对方", confidence="high", reason=""),
            amount=BillFieldDetail(column_name="金额(元)", confidence="high", reason=""),
            status=BillFieldDetail(column_name="当前状态", confidence="high", reason=""),
            remark_columns=BillRemarkColumns(
                column_names=["交易类型", "支付方式", "备注"],
                confidence="high",
                reason="",
            ),
        ),
        sample_rows=[],
        notes=[],
    )

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = normalize_bill_file(input_path, "2601-", structure_resolver=lambda _: structure)

        assert result.source == "微信"
        assert result.output_path == Path("data/bill/2601-微信.xlsx")
    finally:
        os.chdir(cwd)


def test_preview_reader_handles_gb18030_csv(tmp_path: Path) -> None:
    from beartools.bill.reader import read_bill_preview

    input_path = tmp_path / "alipay_gbk.csv"
    content = "导出信息\n交易时间,交易对方,金额,交易状态\n2025-12-31 18:54:05,山姆会员商店,289.80,交易成功\n"
    input_path.write_bytes(content.encode("gb18030"))

    preview = read_bill_preview(input_path, max_rows=3)

    assert preview.file_name == input_path.name
    assert preview.file_type == "csv"
    assert "交易时间,交易对方,金额,交易状态" in preview.file_content


def test_preview_reader_escapes_commas_and_newlines(tmp_path: Path) -> None:
    from beartools.bill.reader import read_bill_preview

    input_path = tmp_path / "complex.csv"
    input_path.write_text(
        '交易时间,交易对方,商品说明\n2025-12-31 18:54:05,山姆会员商店,"商品A,包含逗号\n第二行"\n',
        encoding="utf-8",
    )

    preview = read_bill_preview(input_path, max_rows=3)

    assert "1: 交易时间,交易对方,商品说明" in preview.file_content
    assert '2: 2025-12-31 18:54:05,山姆会员商店,"商品A,包含逗号\\n第二行"' in preview.file_content


def test_normalize_bill_file_skips_footer_summary_rows(tmp_path: Path) -> None:
    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult
    from beartools.bill.service import normalize_bill_file

    input_path = tmp_path / "alipay.csv"
    input_path.write_text(
        "导出信息\n交易时间,交易分类,交易对方,金额,交易状态,收/支,备注\n"
        "2025-12-31 18:54:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n"
        "共1笔记录, , , , , , \n",
        encoding="utf-8",
    )

    structure = BillStructureFileResult(
        file_name=input_path.name,
        source="支付宝",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(column_name="交易时间", confidence="high", reason=""),
            counterparty=BillFieldDetail(column_name="交易对方", confidence="high", reason=""),
            amount=BillFieldDetail(column_name="金额", confidence="high", reason=""),
            status=BillFieldDetail(column_name="交易状态", confidence="high", reason=""),
            remark_columns=BillRemarkColumns(
                column_names=["交易分类", "收/支", "备注"],
                confidence="high",
                reason="",
            ),
        ),
        sample_rows=[],
        notes=[],
    )

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = normalize_bill_file(input_path, "2601-", structure_resolver=lambda _: structure)
    finally:
        os.chdir(cwd)

    assert result.row_count == 1


def test_normalize_bill_file_raises_when_mapped_column_missing(tmp_path: Path) -> None:
    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult
    from beartools.bill.service import normalize_bill_file

    input_path = tmp_path / "alipay.csv"
    input_path.write_text(
        "导出信息\n交易时间,交易分类,交易对方,金额,交易状态,收/支,备注\n"
        "2025-12-31 18:54:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n",
        encoding="utf-8",
    )

    structure = BillStructureFileResult(
        file_name=input_path.name,
        source="支付宝",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(column_name="交易时间", confidence="high", reason=""),
            counterparty=BillFieldDetail(column_name="不存在的交易对方列", confidence="high", reason=""),
            amount=BillFieldDetail(column_name="金额", confidence="high", reason=""),
            status=BillFieldDetail(column_name="交易状态", confidence="high", reason=""),
            remark_columns=BillRemarkColumns(column_names=["交易分类"], confidence="high", reason=""),
        ),
        sample_rows=[],
        notes=[],
    )

    import pytest

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="不存在的交易对方列"):
            normalize_bill_file(input_path, "2601-", structure_resolver=lambda _: structure)
    finally:
        os.chdir(cwd)


def test_analyze_bill_file_success_adds_purpose_owner_columns(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    from beartools.bill.models import BillAnalysisResult
    from beartools.bill.service import analyze_bill_file

    # 创建一个符合normalize格式的测试xlsx
    input_path = tmp_path / "test.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["原始来源", "交易时间", "交易对方", "金额", "交易状态", "注意", "备注"])
    ws.append(["2601-支付宝", "2025-12-31 18:54:05", "山姆会员商店", "289.80", "交易成功", "", "日用百货"])
    wb.save(input_path)

    def mock_row_analyzer(counterparty: str, remark: str, status: str, amount: str) -> BillAnalysisResult:
        return BillAnalysisResult(purpose="购物消费/日用百货", owner="vv")

    result = analyze_bill_file(input_path, row_analyzer=mock_row_analyzer)
    assert result.total_rows == 1
    assert result.failed_rows == 0
    assert result.output_path.exists()

    # 验证输出包含purpose和owner列
    wb_out = load_workbook(result.output_path)
    ws_out = wb_out.active
    headers = [cell.value for cell in ws_out[1]]
    assert headers == ["原始来源", "交易时间", "交易对方", "金额", "交易状态", "注意", "备注", "purpose", "owner"]
    row2 = [cell.value for cell in ws_out[2]]
    assert row2[-2] == "购物消费/日用百货"
    assert row2[-1] == "vv"


def test_analyze_bill_file_single_failure_writes_unknown(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    from beartools.bill.service import analyze_bill_file

    input_path = tmp_path / "test.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["原始来源", "交易时间", "交易对方", "金额", "交易状态", "注意", "备注"])
    ws.append(["2601-支付宝", "2025-12-31 18:54:05", "山姆会员商店", "289.80", "交易成功", "", "日用百货"])
    wb.save(input_path)

    def mock_row_analyzer(*args, **kwargs) -> None:
        raise RuntimeError("analyze failed")

    result = analyze_bill_file(input_path, row_analyzer=mock_row_analyzer)
    assert result.total_rows == 1
    assert result.failed_rows == 1
    assert result.output_path.exists()

    wb_out = load_workbook(result.output_path)
    ws_out = wb_out.active
    row2 = [cell.value for cell in ws_out[2]]
    assert row2[-2] == "unknow"
    assert row2[-1] == "unknow"


def test_analyze_bill_file_5_failures_still_success(tmp_path: Path) -> None:
    from beartools.bill.service import analyze_bill_file

    input_path = tmp_path / "test.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["原始来源", "交易时间", "交易对方", "金额", "交易状态", "注意", "备注"])
    for i in range(5):
        ws.append(["2601-支付宝", f"2025-12-3{i} 18:54:05", f"商家{i}", f"{10 * (i + 1)}.00", "交易成功", "", ""])
    wb.save(input_path)

    def mock_row_analyzer(*args, **kwargs) -> None:
        raise RuntimeError("analyze failed")

    result = analyze_bill_file(input_path, row_analyzer=mock_row_analyzer)
    assert result.total_rows == 5
    assert result.failed_rows == 5
    assert result.output_path.exists()


def test_analyze_bill_file_6_failures_raises_and_no_output(tmp_path: Path) -> None:
    from beartools.bill.service import analyze_bill_file

    input_path = tmp_path / "test.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["原始来源", "交易时间", "交易对方", "金额", "交易状态", "注意", "备注"])
    for i in range(6):
        ws.append(["2601-支付宝", f"2025-12-3{i} 18:54:05", f"商家{i}", f"{10 * (i + 1)}.00", "交易成功", "", ""])
    wb.save(input_path)

    def mock_row_analyzer(*args, **kwargs) -> None:
        raise RuntimeError("analyze failed")

    import pytest

    output_path = input_path.with_name(f"{input_path.stem}.analysis.xlsx")
    assert not output_path.exists()

    with pytest.raises(RuntimeError, match="失败行数超过阈值"):
        analyze_bill_file(input_path, row_analyzer=mock_row_analyzer)

    assert not output_path.exists(), "出错时不应留下输出文件"


def test_analyze_bill_file_non_xlsx_raises(tmp_path: Path) -> None:
    import pytest

    from beartools.bill.service import analyze_bill_file

    input_path = tmp_path / "test.csv"
    input_path.write_text("test", encoding="utf-8")

    with pytest.raises(ValueError, match="只支持归一化结果 .xlsx 输入"):
        analyze_bill_file(input_path)


def test_analyze_bill_file_missing_required_headers_raises(tmp_path: Path) -> None:
    import pytest

    from beartools.bill.service import analyze_bill_file

    input_path = tmp_path / "test.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["原始来源", "交易时间", "交易对方", "金额"])  # 缺少几个表头
    ws.append(["2601-支付宝", "2025-12-31 18:54:05", "山姆会员商店", "289.80"])
    wb.save(input_path)

    with pytest.raises(RuntimeError, match="表头不匹配，需要包含固定表头"):
        analyze_bill_file(input_path)


def test_run_bill_pipeline_success(tmp_path: Path):
    from beartools.bill.models import (
        BillAnalysisResult,
        BillFieldDetail,
        BillFieldMapping,
        BillRemarkColumns,
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
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = run_bill_pipeline(
            input_csv,
            "2601-",
            structure_resolver=lambda _: structure,
            row_analyzer=lambda *args: BillAnalysisResult(purpose="测试用途", owner="测试归属"),
        )
        assert result.normalized_output_path.exists()
        assert result.analysis_output_path.exists()
        assert result.normalized_row_count == 1
        assert result.analysis_total_rows == 1
        assert result.analysis_failed_rows == 0
    finally:
        os.chdir(cwd)


def test_run_bill_pipeline_analysis_fails(tmp_path: Path):
    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult
    from beartools.bill.service import run_bill_pipeline

    input_csv = tmp_path / "test.csv"
    input_csv.write_text(
        "导出信息\n交易时间,交易分类,交易对方,金额,交易状态,收/支,备注\n"
        "2025-12-31 18:54:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n"
        "2025-12-31 18:55:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n"
        "2025-12-31 18:56:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n"
        "2025-12-31 18:57:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n"
        "2025-12-31 18:58:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n"
        "2025-12-31 18:59:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n"
        "2025-12-31 19:00:05,日用百货,山姆会员商店,289.80,交易成功,支出,测试备注\n",
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
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:

        def failing_row_analyzer(*args):
            raise RuntimeError("分析失败")

        run_bill_pipeline(input_csv, "2601-", structure_resolver=lambda _: structure, row_analyzer=failing_row_analyzer)
        raise AssertionError("应该抛出异常")
    except RuntimeError:
        normalized_path = Path("data/bill/2601-测试账单.xlsx")
        analysis_path = Path("data/bill/2601-测试账单.analysis.xlsx")
        assert normalized_path.exists(), "normalized应该保留"
        assert not analysis_path.exists(), "analysis不应该存在"
    finally:
        os.chdir(cwd)
