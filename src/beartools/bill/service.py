"""账单归一化服务。"""

from __future__ import annotations

from collections.abc import Callable
import csv
from pathlib import Path
import re

from .agent import resolve_bill_structure
from .models import BillFieldMapping, BillStructureFileResult, NormalizeBillFileResult, NormalizedBillRow
from .reader import read_bill_preview, read_bill_rows

_AMOUNT_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
_OUTPUT_FIELDNAMES = ["原始来源", "交易时间", "交易对方", "金额", "交易状态", "注意", "备注"]


def normalize_bill_file(
    input_path: str | Path,
    from_value: str,
    *,
    structure_resolver: Callable[[Path], BillStructureFileResult] | None = None,
) -> NormalizeBillFileResult:
    """将单个账单文件归一化输出为统一 CSV。"""

    source_path = Path(input_path)
    resolver = structure_resolver or _default_structure_resolver

    structure = resolver(source_path)
    output_path = _build_output_csv_path(from_value, structure.source)
    rows = read_bill_rows(source_path)
    normalized_rows, ignored_lines, total_raw_data_rows = _normalize_rows(rows, structure, from_value=from_value)
    output_row_count = len(normalized_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=_OUTPUT_FIELDNAMES)
        writer.writeheader()
        for normalized_row in normalized_rows:
            writer.writerow(_normalized_row_to_csv_record(normalized_row))

    return NormalizeBillFileResult(
        input_path=source_path,
        output_csv_path=output_path,
        source=structure.source,
        row_count=output_row_count,
        ignored_lines=ignored_lines,
        total_raw_data_rows=total_raw_data_rows,
        output_row_count=output_row_count,
    )


def _default_structure_resolver(input_path: Path) -> BillStructureFileResult:
    preview = read_bill_preview(input_path)
    return resolve_bill_structure(preview)


def _normalize_rows(
    rows: list[list[str]], structure: BillStructureFileResult, *, from_value: str
) -> tuple[list[NormalizedBillRow], list[int], int]:
    if structure.header_row <= 0 or structure.data_start_row <= 0:
        raise RuntimeError("账单结构识别结果缺少有效的 header_row 或 data_start_row")
    if len(rows) < structure.header_row:
        raise RuntimeError("账单文件行数不足，无法定位表头")

    header = rows[structure.header_row - 1]
    column_map = {column_name: index for index, column_name in enumerate(header)}
    field_mapping = structure.field_mapping
    _validate_required_columns(column_map, field_mapping)

    normalized_rows: list[NormalizedBillRow] = []
    ignored_lines: list[int] = []
    data_rows = rows[structure.data_start_row - 1 :]
    total_raw_data_rows = len(data_rows)

    for index, row in enumerate(data_rows):
        original_line_number = structure.data_start_row + index
        if _is_empty_row(row):
            ignored_lines.append(original_line_number)
            continue
        if _is_summary_row(row, column_map, field_mapping):
            ignored_lines.append(original_line_number)
            # 汇总行之后的所有行都忽略
            for remaining_index in range(index + 1, len(data_rows)):
                ignored_lines.append(structure.data_start_row + remaining_index)
            break
        raw_amount = _normalize_amount(_get_column_value(row, column_map, field_mapping.amount.column_name))
        status = _get_column_value(row, column_map, field_mapping.status.column_name)
        adjusted_amount = raw_amount

        # 尝试转换为数字进行正负调整，转换失败保持原样
        try:
            amount_num = float(raw_amount)
            if status == "退款成功":
                # 退款成功强制为负数
                adjusted_amount = f"{-abs(amount_num):g}"
            elif status == "交易成功":
                # 交易成功强制为正数
                adjusted_amount = f"{abs(amount_num):g}"
        except (ValueError, TypeError):
            # 不是合法数字，保持原始值
            pass

        normalized_rows.append(
            NormalizedBillRow(
                from_value=from_value,
                source=structure.source,
                transaction_time=_get_column_value(row, column_map, field_mapping.transaction_time.column_name),
                counterparty=_get_column_value(row, column_map, field_mapping.counterparty.column_name),
                amount=adjusted_amount,
                status=status,
                remark=_build_remark(row, column_map, field_mapping.remark_columns.column_names),
            )
        )
    return normalized_rows, ignored_lines, total_raw_data_rows


def _is_empty_row(row: list[str]) -> bool:
    return not any(cell.strip() for cell in row)


def _get_column_value(row: list[str], column_map: dict[str, int], column_name: str) -> str:
    if not column_name:
        return ""
    index = column_map.get(column_name)
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _normalize_amount(raw_amount: str) -> str:
    if not raw_amount:
        return ""
    match = _AMOUNT_PATTERN.search(raw_amount.replace(",", ""))
    if match is None:
        return raw_amount.strip()
    return match.group(0)


def _build_remark(row: list[str], column_map: dict[str, int], column_names: list[str]) -> str:
    parts: list[str] = []
    for column_name in column_names:
        value = _get_column_value(row, column_map, column_name)
        if not value:
            continue
        parts.append(f"{column_name}={value}")
    return "; ".join(parts)


def _build_output_csv_path(from_value: str, source: str) -> Path:
    return Path("data") / "bill" / f"{from_value}{source}.csv"


def _normalized_row_to_csv_record(normalized_row: NormalizedBillRow) -> dict[str, str]:
    notice = "" if normalized_row.status in ["交易成功", "退款成功"] else "focus"
    return {
        "原始来源": f"{normalized_row.from_value}{normalized_row.source}",
        "交易时间": normalized_row.transaction_time,
        "交易对方": normalized_row.counterparty,
        "金额": normalized_row.amount,
        "交易状态": normalized_row.status,
        "注意": notice,
        "备注": normalized_row.remark,
    }


def _validate_required_columns(column_map: dict[str, int], field_mapping: BillFieldMapping) -> None:
    required_columns = {
        "transaction_time": field_mapping.transaction_time.column_name,
        "counterparty": field_mapping.counterparty.column_name,
        "amount": field_mapping.amount.column_name,
        "status": field_mapping.status.column_name,
    }
    for field_name, column_name in required_columns.items():
        if not column_name:
            raise RuntimeError(f"账单结构识别结果缺少字段映射: {field_name}")
        if column_name not in column_map:
            raise RuntimeError(f"账单结构识别结果中的列不存在: {column_name}")


def _is_summary_row(row: list[str], column_map: dict[str, int], field_mapping: BillFieldMapping) -> bool:
    transaction_time = _get_column_value(row, column_map, field_mapping.transaction_time.column_name)
    counterparty = _get_column_value(row, column_map, field_mapping.counterparty.column_name)
    amount = _get_column_value(row, column_map, field_mapping.amount.column_name)
    status = _get_column_value(row, column_map, field_mapping.status.column_name)
    if amount and _AMOUNT_PATTERN.search(amount.replace(",", "")) is None:
        return True
    if transaction_time and not _looks_like_transaction_time(transaction_time):
        return True
    return not any([counterparty, status]) and bool(transaction_time) and not amount


def _looks_like_transaction_time(value: str) -> bool:
    normalized = value.strip()
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?", normalized))
