"""账单结构识别与归一化数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ConfidenceLevel = Literal["high", "medium", "low"]
BillSource = Literal["支付宝", "微信", "京东", "未知"]
BillNormalizedStatus = Literal["NORMAL_SUCCESS", "REFUND", "PART_REFUND"]


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
    normalized_status: BillNormalizedStatus
    remark: str


@dataclass(slots=True)
class UnknownBillStatusesError(RuntimeError):
    """存在未知账单状态时抛出的异常。"""

    statuses: list[str]

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, f"存在未识别的交易状态: {', '.join(self.statuses)}")


@dataclass(slots=True)
class BillStatusPatternRule:
    """状态模式匹配规则。"""

    pattern: str
    normalized_status: BillNormalizedStatus


@dataclass(slots=True)
class BillStatusMappingConfig:
    """账单状态映射配置。"""

    exact: dict[str, BillNormalizedStatus]
    patterns: list[BillStatusPatternRule] = field(default_factory=list)


@dataclass(slots=True)
class PartRefundAmountResult:
    """部分退款金额修正结果。"""

    refund_amount: str
    reason: str


@dataclass(slots=True)
class NormalizeProgressSnapshot:
    """归一化阶段进度快照。"""

    processed_count: int
    normal_success_count: int
    refund_count: int
    part_refund_count: int
    is_final: bool = False


@dataclass(slots=True)
class NormalizeBillFileResult:
    """单文件归一化结果。"""

    input_path: Path
    output_path: Path
    source: str
    row_count: int
    ignored_lines: list[int] = field(default_factory=list)
    total_raw_data_rows: int = 0
    output_row_count: int = 0


BillAnalysisOwner = Literal["vv", "yy", "团团", "all"]
"""账单归属人类型别名。"""

BillAnalysisPurpose = Literal[
    "出行",
    "房租",
    "房贷",
    "学费",
    "食物",
    "衣服",
    "外出吃饭",
    "车",
    "娱乐",
    "人情",
    "爱自己",
    "家居",
    "物业",
    "医疗",
    "家政",
    "通信",
    "交通",
    "工作",
    "书",
    "保养",
    "物流",
    "运费",
    "日常",
]
"""账单交易用途类型别名。"""


@dataclass(slots=True)
class BillAnalysisResult:
    """单行账单分析结果。"""

    purpose: BillAnalysisPurpose
    owner: BillAnalysisOwner


@dataclass(slots=True)
class AnalyzeBillFileResult:
    """整个账单文件分析结果。"""

    input_path: Path
    output_path: Path
    total_rows: int
    failed_rows: int = 0


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
    analysis_total_count: int = 0
    analysis_completed_count: int = 0
