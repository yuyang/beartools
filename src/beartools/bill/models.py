"""账单结构识别与归一化数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ConfidenceLevel = Literal["high", "medium", "low"]
BillSource = Literal["支付宝", "微信", "京东", "未知"]


@dataclass(slots=True)
class BillPreview:
    """账单预览内容。"""

    file_name: str
    file_type: str
    file_content: str


@dataclass(slots=True)
class BillFieldDetail:
    """单个核心字段映射。"""

    confidence: ConfidenceLevel
    reason: str
    column_name: str = ""


@dataclass(slots=True)
class BillRemarkColumns:
    """备注字段集合映射。"""

    confidence: ConfidenceLevel
    reason: str
    column_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BillFieldMapping:
    """账单字段映射信息。"""

    transaction_time: BillFieldDetail
    counterparty: BillFieldDetail
    amount: BillFieldDetail
    status: BillFieldDetail
    remark_columns: BillRemarkColumns


@dataclass(slots=True)
class BillStructureFileResult:
    """单文件结构识别结果。"""

    file_name: str
    source: BillSource
    header_row: int
    data_start_row: int
    field_mapping: BillFieldMapping
    sample_rows: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BillStructureResult:
    """Prompt 约定的结构识别结果。"""

    files: list[BillStructureFileResult]


@dataclass(slots=True)
class NormalizedBillRow:
    """统一账单行。"""

    from_value: str
    source: str
    transaction_time: str
    counterparty: str
    amount: str
    status: str
    remark: str


@dataclass(slots=True)
class NormalizeBillFileResult:
    """单文件归一化结果。"""

    input_path: Path
    output_csv_path: Path
    source: str
    row_count: int
