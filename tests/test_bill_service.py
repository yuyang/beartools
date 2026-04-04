from __future__ import annotations

import csv
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
        assert result.output_csv_path == Path("data/bill/2601-支付宝.csv")
        rows = list(csv.DictReader(result.output_csv_path.open(encoding="utf-8", newline="")))
        assert rows == [
            {
                "from": "2601-",
                "source": "支付宝",
                "transaction_time": "2025-12-31 18:54:05",
                "counterparty": "山姆会员商店",
                "amount": "289.80",
                "status": "交易成功",
                "remark": "交易分类=日用百货; 收/支=支出; 备注=测试备注",
            }
        ]
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
        assert result.output_csv_path == Path("data/bill/2601-微信.csv")
        rows = list(csv.DictReader(result.output_csv_path.open(encoding="utf-8", newline="")))
        assert rows == [
            {
                "from": "2601-",
                "source": "微信",
                "transaction_time": "2026-01-01 19:43:53",
                "counterparty": "京东七鲜超市",
                "amount": "61.60",
                "status": "支付成功",
                "remark": "交易类型=商户消费; 支付方式=零钱; 备注=/",
            }
        ]
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
        rows = list(csv.DictReader(result.output_csv_path.open(encoding="utf-8", newline="")))
    finally:
        os.chdir(cwd)

    assert result.row_count == 1
    assert len(rows) == 1


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

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        try:
            normalize_bill_file(input_path, "2601-", structure_resolver=lambda _: structure)
        except RuntimeError as exc:
            assert "不存在的交易对方列" in str(exc)
        else:
            raise AssertionError("预期在字段映射列不存在时抛出 RuntimeError")
    finally:
        os.chdir(cwd)
