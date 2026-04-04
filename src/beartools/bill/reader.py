"""账单文件读取器。"""

from __future__ import annotations

from collections.abc import Iterable
import csv
import importlib
from pathlib import Path
from typing import Protocol, cast

from .models import BillPreview

_SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xlsm"}
_CSV_ENCODINGS = ("utf-8-sig", "gb18030")


class _WorksheetLike(Protocol):
    def iter_rows(self, *, values_only: bool = ...) -> Iterable[tuple[object | None, ...]]: ...


class _WorkbookLike(Protocol):
    sheetnames: list[str]

    def __getitem__(self, key: str) -> _WorksheetLike: ...

    def close(self) -> None: ...


class _OpenpyxlModule(Protocol):
    def load_workbook(
        self,
        filename: Path,
        read_only: bool = ...,
        data_only: bool = ...,
    ) -> _WorkbookLike: ...


def ensure_supported_bill_file(input_path: Path) -> None:
    """校验账单文件存在且后缀受支持。"""

    if not input_path.exists():
        raise FileNotFoundError(f"账单文件不存在: {input_path}")
    if input_path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"暂不支持的账单文件类型: {input_path.suffix}")


def read_bill_preview(input_path: Path, max_rows: int = 200) -> BillPreview:
    """读取账单预览内容。"""

    ensure_supported_bill_file(input_path)

    if input_path.suffix.lower() == ".csv":
        file_content = _read_csv_preview(input_path, max_rows=max_rows)
    else:
        file_content = _read_excel_preview(input_path, max_rows=max_rows)

    return BillPreview(
        file_name=input_path.name,
        file_type=input_path.suffix.lower().lstrip("."),
        file_content=file_content,
    )


def read_bill_rows(input_path: Path) -> list[list[str]]:
    """读取账单完整二维数据。"""

    ensure_supported_bill_file(input_path)

    if input_path.suffix.lower() == ".csv":
        return _read_csv_rows(input_path)
    return _read_excel_rows(input_path)


def _read_csv_preview(input_path: Path, max_rows: int) -> str:
    rows = _read_csv_rows(input_path)[:max_rows]
    return _format_preview_rows(rows)


def _read_csv_rows(input_path: Path) -> list[list[str]]:
    last_error: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODINGS:
        try:
            with input_path.open("r", encoding=encoding, newline="") as file:
                return [[_normalize_cell(value) for value in row] for row in csv.reader(file)]
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise RuntimeError(f"无法解码 CSV 文件: {input_path}") from last_error
    raise RuntimeError(f"无法读取 CSV 文件: {input_path}")


def _read_excel_preview(input_path: Path, max_rows: int) -> str:
    rows = _read_excel_rows(input_path)[:max_rows]
    return _format_preview_rows(rows)


def _read_excel_rows(input_path: Path) -> list[list[str]]:
    openpyxl_module = cast(_OpenpyxlModule, importlib.import_module("openpyxl"))
    workbook = openpyxl_module.load_workbook(input_path, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    rows = [[_normalize_cell(value) for value in row] for row in sheet.iter_rows(values_only=True)]
    workbook.close()
    return rows


def _normalize_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _format_preview_rows(rows: list[list[str]]) -> str:
    return "\n".join(f"{index}: {_format_preview_row(row)}" for index, row in enumerate(rows, start=1))


def _format_preview_row(row: list[str]) -> str:
    return ",".join(_quote_preview_cell(cell) for cell in row)


def _quote_preview_cell(cell: str) -> str:
    normalized = cell.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    if any(char in normalized for char in [",", '"', "\\n"]):
        escaped = normalized.replace('"', '""')
        return f'"{escaped}"'
    return normalized
