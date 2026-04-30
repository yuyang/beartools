# Bill 状态映射与部分退款处理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 bill 归一化流程增加 YAML 状态映射、未知状态人工确认写回，以及 `PART_REFUND` 的 Tool Calling + `CalculateTool` 金额修正能力。

**Architecture:** 新增一个独立的状态映射模块负责 `config/bill_status_mapping.yaml` 的加载、匹配和写回；`service` 层统一按标准状态驱动金额处理与退款抵消；`command` 层负责未知状态的交互确认；`agent` 层新增 `PART_REFUND` 专用 prompt 与 `CalculateTool`，通过 Tool Calling 产出结构化退款金额。

**Tech Stack:** Python 3.13、PyYAML、pydantic-ai、Typer、openpyxl、pytest、ruff、mypy

---

## 文件结构

### 新增文件

- `config/bill_status_mapping.yaml`
  - 默认状态映射配置，包含 `exact` 和 `patterns`
- `src/beartools/bill/status_mapping.py`
  - 状态映射加载、匹配、未知状态异常、配置写回
- `src/beartools/bill/calculate_tool.py`
  - 安全的算术表达式计算工具，供 `PART_REFUND` Tool Calling 使用
- `prompts/bill_part_refund_amount.md`
  - 部分退款金额修正 prompt
- `tests/test_bill_status_mapping.py`
  - 状态映射模块单测
- `tests/test_bill_calculate_tool.py`
  - `CalculateTool` 单测

### 修改文件

- `src/beartools/bill/models.py`
  - 增加标准状态类型、`normalized_status` 字段、未知状态异常载荷模型、部分退款输出模型
- `src/beartools/bill/agent.py`
  - 增加 `PART_REFUND` 专用 agent 入口和 Tool Calling 注册
- `src/beartools/bill/service.py`
  - 接入状态映射、未知状态扫描、部分退款金额修正、退款抵消基于标准状态
- `src/beartools/bill/__init__.py`
  - 导出新能力（如果 command 需要直接导入）
- `src/beartools/commands/bill/command.py`
  - 为 `normalize` / `run` 增加未知状态确认并写回配置后重试的循环
- `tests/test_bill_service.py`
  - 补充归一化、未知状态、部分退款、抵消逻辑测试
- `tests/test_bill_agent.py`
  - 补充 `PART_REFUND` agent 与 Tool Calling 测试
- `tests/test_bill_command.py`
  - 补充未知状态交互测试

---

### Task 1: 状态映射配置与领域模型

**Files:**
- Create: `config/bill_status_mapping.yaml`
- Create: `src/beartools/bill/status_mapping.py`
- Create: `tests/test_bill_status_mapping.py`
- Modify: `src/beartools/bill/models.py`

- [ ] **Step 1: 写状态映射模块失败测试**

```python
from __future__ import annotations

from pathlib import Path

import pytest


def test_status_mapping_prefers_exact_over_pattern(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text(
        """
exact:
  已退款特殊: REFUND
patterns:
  - pattern: "^已退款"
    normalized_status: PART_REFUND
""".strip(),
        encoding="utf-8",
    )

    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("已退款特殊", mapping) == "REFUND"


def test_status_mapping_matches_pattern(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text(
        """
exact: {}
patterns:
  - pattern: "^已退款"
    normalized_status: PART_REFUND
""".strip(),
        encoding="utf-8",
    )

    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("已退款￥1.00", mapping) == "PART_REFUND"


def test_status_mapping_returns_none_for_unknown_value(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text("exact: {}\npatterns: []\n", encoding="utf-8")

    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("等待确认收货", mapping) is None


def test_append_exact_mapping_persists_new_status(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import append_exact_mapping, load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text("exact: {}\npatterns: []\n", encoding="utf-8")

    append_exact_mapping(config_path, "等待确认收货", "NORMAL_SUCCESS")
    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("等待确认收货", mapping) == "NORMAL_SUCCESS"


def test_append_exact_mapping_rejects_duplicate_with_different_status(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import append_exact_mapping

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text("exact:\n  交易成功: NORMAL_SUCCESS\npatterns: []\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="交易成功"):
        append_exact_mapping(config_path, "交易成功", "REFUND")
```

- [ ] **Step 2: 运行状态映射测试，确认当前失败**

Run: `uv run pytest tests/test_bill_status_mapping.py -xvs`

Expected: FAIL，提示 `beartools.bill.status_mapping` 不存在，或 `load_status_mapping` / `append_exact_mapping` 未定义。

- [ ] **Step 3: 增加标准状态与异常模型**

在 `src/beartools/bill/models.py` 中加入这些定义：

```python
BillNormalizedStatus = Literal["NORMAL_SUCCESS", "REFUND", "PART_REFUND"]


@dataclass(slots=True)
class UnknownBillStatusesError(RuntimeError):
    statuses: list[str]

    def __post_init__(self) -> None:
        super().__init__(f"存在未识别的交易状态: {', '.join(self.statuses)}")


@dataclass(slots=True)
class BillStatusPatternRule:
    pattern: str
    normalized_status: BillNormalizedStatus


@dataclass(slots=True)
class BillStatusMappingConfig:
    exact: dict[str, BillNormalizedStatus]
    patterns: list[BillStatusPatternRule] = field(default_factory=list)
```

同时把 `NormalizedBillRow` 改成：

```python
@dataclass(slots=True)
class NormalizedBillRow:
    from_value: str
    source: str
    transaction_time: str
    counterparty: str
    amount: str
    status: str
    normalized_status: BillNormalizedStatus
    remark: str
```

- [ ] **Step 4: 实现状态映射模块最小功能**

在 `src/beartools/bill/status_mapping.py` 中先实现这版代码：

```python
from __future__ import annotations

from pathlib import Path
import re

import yaml

from .models import BillNormalizedStatus, BillStatusMappingConfig, BillStatusPatternRule

DEFAULT_STATUS_MAPPING_PATH = Path("config") / "bill_status_mapping.yaml"


def load_status_mapping(config_path: Path | None = None) -> BillStatusMappingConfig:
    path = config_path or DEFAULT_STATUS_MAPPING_PATH
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    exact_raw = raw.get("exact", {})
    patterns_raw = raw.get("patterns", [])
    exact = {str(k): _normalize_status(str(v)) for k, v in exact_raw.items()}
    patterns = [
        BillStatusPatternRule(
            pattern=str(item["pattern"]),
            normalized_status=_normalize_status(str(item["normalized_status"])),
        )
        for item in patterns_raw
    ]
    return BillStatusMappingConfig(exact=exact, patterns=patterns)


def resolve_normalized_status(
    raw_status: str, config: BillStatusMappingConfig
) -> BillNormalizedStatus | None:
    if raw_status in config.exact:
        return config.exact[raw_status]
    for rule in config.patterns:
        if re.search(rule.pattern, raw_status):
            return rule.normalized_status
    return None


def append_exact_mapping(config_path: Path, raw_status: str, normalized_status: BillNormalizedStatus) -> None:
    config = load_status_mapping(config_path)
    existing = config.exact.get(raw_status)
    if existing is not None and existing != normalized_status:
        raise RuntimeError(f"状态 {raw_status} 已存在映射 {existing}，不能覆盖为 {normalized_status}")
    config.exact[raw_status] = normalized_status
    payload = {
        "exact": dict(sorted(config.exact.items())),
        "patterns": [
            {"pattern": rule.pattern, "normalized_status": rule.normalized_status}
            for rule in config.patterns
        ],
    }
    with config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)


def _normalize_status(value: str) -> BillNormalizedStatus:
    if value not in {"NORMAL_SUCCESS", "REFUND", "PART_REFUND"}:
        raise RuntimeError(f"非法标准状态: {value}")
    return value  # type: ignore[return-value]
```

- [ ] **Step 5: 写默认配置文件**

创建 `config/bill_status_mapping.yaml`：

```yaml
exact:
  交易成功: NORMAL_SUCCESS
  支付成功: NORMAL_SUCCESS
  已转账: NORMAL_SUCCESS
  对方已收钱: NORMAL_SUCCESS
  已存入零钱: NORMAL_SUCCESS
  已到账: NORMAL_SUCCESS
  退款成功: REFUND
  已全额退款: REFUND
patterns:
  - pattern: "^已退款"
    normalized_status: PART_REFUND
```

- [ ] **Step 6: 运行状态映射测试，确认转绿**

Run: `uv run pytest tests/test_bill_status_mapping.py -xvs`

Expected: PASS，5 个测试全部通过。

- [ ] **Step 7: 提交本任务**

```bash
git add config/bill_status_mapping.yaml src/beartools/bill/models.py src/beartools/bill/status_mapping.py tests/test_bill_status_mapping.py
git commit -m "ADD: 增加账单状态映射配置"
```

---

### Task 2: CalculateTool 与 PART_REFUND Agent

**Files:**
- Create: `src/beartools/bill/calculate_tool.py`
- Create: `prompts/bill_part_refund_amount.md`
- Create: `tests/test_bill_calculate_tool.py`
- Modify: `src/beartools/bill/models.py`
- Modify: `src/beartools/bill/agent.py`
- Modify: `tests/test_bill_agent.py`

- [ ] **Step 1: 写 CalculateTool 与 PART_REFUND agent 失败测试**

在 `tests/test_bill_calculate_tool.py` 中写：

```python
from __future__ import annotations

import pytest


def test_calculate_expression_returns_decimal_string() -> None:
    from beartools.bill.calculate_tool import calculate_expression

    assert calculate_expression("10.50 - 2.30") == "8.20"


def test_calculate_expression_rejects_unsafe_syntax() -> None:
    from beartools.bill.calculate_tool import calculate_expression

    with pytest.raises(ValueError, match="非法表达式"):
        calculate_expression("__import__('os').system('pwd')")
```

在 `tests/test_bill_agent.py` 追加：

```python
def test_resolve_part_refund_amount_returns_structured_result() -> None:
    from dataclasses import dataclass
    from unittest.mock import patch

    from beartools.bill.agent import resolve_part_refund_amount
    from beartools.bill.models import PartRefundAmountResult

    @dataclass
    class _FakeRunResult:
        output: object

    class _FakeAgent:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def tool_plain(self, func):
            self.registered_tool = func
            return func

        def run_sync(self, _prompt: str) -> _FakeRunResult:
            return _FakeRunResult(output=PartRefundAmountResult(refund_amount="1.00", reason="命中状态文本"))

    with (
        patch("beartools.bill.agent.get_llm_runtime") as mock_runtime,
        patch("beartools.bill.agent.LLFactory.create", return_value="fake-model"),
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
        mock_runtime.return_value.get_active_node.return_value = object()
        result = resolve_part_refund_amount(
            counterparty="测试商户",
            remark="状态显示已退款￥1.00",
            status="已退款￥1.00",
            amount="61.60",
            source="微信",
            transaction_time="2026-01-01 19:43:53",
        )

    assert result.refund_amount == "1.00"
    assert result.reason == "命中状态文本"
```

- [ ] **Step 2: 运行新测试，确认当前失败**

Run: `uv run pytest tests/test_bill_calculate_tool.py tests/test_bill_agent.py -xvs`

Expected: FAIL，提示 `calculate_expression`、`PartRefundAmountResult`、`resolve_part_refund_amount` 未定义。

- [ ] **Step 3: 增加 PART_REFUND 输出模型**

在 `src/beartools/bill/models.py` 中加入：

```python
@dataclass(slots=True)
class PartRefundAmountResult:
    refund_amount: str
    reason: str
```

- [ ] **Step 4: 实现安全 CalculateTool**

在 `src/beartools/bill/calculate_tool.py` 中实现：

```python
from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation


def calculate_expression(expression: str) -> str:
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("非法表达式") from exc
    value = _eval_node(node.body)
    return format(value.quantize(Decimal("0.01")), "f")


def _eval_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    raise ValueError("非法表达式")
```

- [ ] **Step 5: 新增 PART_REFUND prompt**

创建 `prompts/bill_part_refund_amount.md`：

```md
你是账单部分退款金额修正助手。

请根据以下信息判断这条账单的实际退款金额。

- 原始来源: {{ source }}
- 交易时间: {{ transaction_time }}
- 交易对方: {{ counterparty }}
- 原始金额: {{ amount }}
- 原始状态: {{ status }}
- 备注: {{ remark }}

要求：

1. 你的最终输出必须是结构化结果。
2. 当需要四则运算时，必须调用 `CalculateTool`，不要直接心算。
3. `refund_amount` 只填写退款金额本身，不带负号，不带货币符号。
4. 如果状态或备注中已经明确出现退款金额，优先使用该金额。
5. `reason` 用中文简要说明依据。
```

- [ ] **Step 6: 实现 PART_REFUND agent 入口**

在 `src/beartools/bill/agent.py` 中增加：

```python
from .calculate_tool import calculate_expression
from .models import PartRefundAmountResult


class _PartRefundRunResult(Protocol):
    output: PartRefundAmountResult


def resolve_part_refund_amount(
    *,
    counterparty: str,
    remark: str,
    status: str,
    amount: str,
    source: str,
    transaction_time: str,
) -> PartRefundAmountResult:
    prompt = get_prompt_manager().render(
        "bill_part_refund_amount",
        {
            "counterparty": counterparty,
            "remark": remark,
            "status": status,
            "amount": amount,
            "source": source,
            "transaction_time": transaction_time,
        },
    )
    runtime = get_llm_runtime()
    node = runtime.get_active_node()
    model = LLFactory().create(node=node)
    agent = Agent(
        model,
        output_type=PartRefundAmountResult,
        system_prompt="你是部分退款金额修正助手，只能返回符合 schema 的 JSON。",
    )

    @agent.tool_plain
    def calculate_tool(expression: str) -> str:
        """执行四则运算表达式并返回两位小数字符串。"""

        return calculate_expression(expression)

    result = cast(_PartRefundRunResult, agent.run_sync(prompt))
    return result.output
```

- [ ] **Step 7: 运行测试，确认转绿**

Run: `uv run pytest tests/test_bill_calculate_tool.py tests/test_bill_agent.py -xvs`

Expected: PASS，新增的 CalculateTool / PART_REFUND agent 测试通过，原有 `tests/test_bill_agent.py` 用例不受影响。

- [ ] **Step 8: 提交本任务**

```bash
git add src/beartools/bill/models.py src/beartools/bill/calculate_tool.py src/beartools/bill/agent.py prompts/bill_part_refund_amount.md tests/test_bill_calculate_tool.py tests/test_bill_agent.py
git commit -m "ADD: 增加部分退款计算工具"
```

---

### Task 3: service 层接入标准状态与部分退款修正

**Files:**
- Modify: `src/beartools/bill/service.py`
- Modify: `src/beartools/bill/models.py`
- Modify: `src/beartools/bill/__init__.py`
- Modify: `tests/test_bill_service.py`

- [ ] **Step 1: 写 service 失败测试**

在 `tests/test_bill_service.py` 追加这些测试：

```python
def test_normalize_bill_file_maps_status_and_preserves_raw_status(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult
    from beartools.bill.service import normalize_bill_file

    input_path = tmp_path / "wechat.csv"
    input_path.write_text(
        "标题\n交易时间,交易对方,金额,当前状态,备注\n2026-01-01 19:43:53,京东,61.60,支付成功,测试\n",
        encoding="utf-8",
    )
    structure = BillStructureFileResult(
        file_name=input_path.name,
        source="微信",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(column_name="交易时间", confidence="high", reason=""),
            counterparty=BillFieldDetail(column_name="交易对方", confidence="high", reason=""),
            amount=BillFieldDetail(column_name="金额", confidence="high", reason=""),
            status=BillFieldDetail(column_name="当前状态", confidence="high", reason=""),
            remark_columns=BillRemarkColumns(column_names=["备注"], confidence="high", reason=""),
        ),
    )

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = normalize_bill_file(input_path, "2601-", structure_resolver=lambda _: structure)
    finally:
        os.chdir(cwd)

    wb = load_workbook(tmp_path / result.output_path)
    ws = wb.active
    assert ws["D2"].value == "61.6"
    assert ws["E2"].value == "支付成功"


def test_normalize_bill_file_raises_unknown_statuses_before_writing_output(tmp_path: Path) -> None:
    import pytest

    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult
    from beartools.bill.service import normalize_bill_file

    input_path = tmp_path / "alipay.csv"
    input_path.write_text(
        "标题\n交易时间,交易对方,金额,交易状态,备注\n2026-01-01 10:00:00,淘宝,10.00,等待确认收货,备注\n",
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
            remark_columns=BillRemarkColumns(column_names=["备注"], confidence="high", reason=""),
        ),
    )

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="等待确认收货"):
            normalize_bill_file(input_path, "2601-", structure_resolver=lambda _: structure)
    finally:
        os.chdir(cwd)


def test_normalize_bill_file_uses_part_refund_amount_resolver(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    from beartools.bill.models import BillFieldDetail, BillFieldMapping, BillRemarkColumns, BillStructureFileResult, PartRefundAmountResult
    from beartools.bill.service import normalize_bill_file

    input_path = tmp_path / "wechat.csv"
    input_path.write_text(
        "标题\n交易时间,交易对方,金额,当前状态,备注\n2026-01-01 19:43:53,京东,61.60,已退款￥1.00,状态显示已退款￥1.00\n",
        encoding="utf-8",
    )
    structure = BillStructureFileResult(
        file_name=input_path.name,
        source="微信",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(column_name="交易时间", confidence="high", reason=""),
            counterparty=BillFieldDetail(column_name="交易对方", confidence="high", reason=""),
            amount=BillFieldDetail(column_name="金额", confidence="high", reason=""),
            status=BillFieldDetail(column_name="当前状态", confidence="high", reason=""),
            remark_columns=BillRemarkColumns(column_names=["备注"], confidence="high", reason=""),
        ),
    )

    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = normalize_bill_file(
            input_path,
            "2601-",
            structure_resolver=lambda _: structure,
            part_refund_amount_resolver=lambda **_: PartRefundAmountResult(refund_amount="1.00", reason="命中状态"),
        )
    finally:
        os.chdir(cwd)

    wb = load_workbook(tmp_path / result.output_path)
    ws = wb.active
    assert ws["D2"].value == "-1"
    assert ws["E2"].value == "已退款￥1.00"


def test_apply_refund_offset_ignores_full_refund_only() -> None:
    from beartools.bill.models import NormalizedBillRow
    from beartools.bill.service import _apply_refund_offset

    rows = [
        NormalizedBillRow("2601-", "支付宝", "2026-01-01", "淘宝", "10", "交易成功", "NORMAL_SUCCESS", ""),
        NormalizedBillRow("2601-", "支付宝", "2026-01-02", "淘宝", "-10", "退款成功", "REFUND", ""),
        NormalizedBillRow("2601-", "微信", "2026-01-03", "京东", "-1", "已退款￥1.00", "PART_REFUND", ""),
    ]

    filtered_rows, ignored = _apply_refund_offset(rows, [3, 4, 5], [])

    assert len(filtered_rows) == 1
    assert filtered_rows[0].normalized_status == "PART_REFUND"
    assert ignored == [3, 4]
```

- [ ] **Step 2: 运行 service 测试，确认当前失败**

Run: `uv run pytest tests/test_bill_service.py -xvs`

Expected: FAIL，提示 `normalize_bill_file` 不支持 `part_refund_amount_resolver`，`_apply_refund_offset` 仍基于原始状态匹配，未知状态不会抛错。

- [ ] **Step 3: 扫描未知状态并抛出领域异常**

在 `src/beartools/bill/service.py` 中增加：

```python
from .models import PartRefundAmountResult, UnknownBillStatusesError
from .status_mapping import DEFAULT_STATUS_MAPPING_PATH, load_status_mapping, resolve_normalized_status


def _collect_unknown_statuses(rows: list[list[str]], structure: BillStructureFileResult) -> list[str]:
    header = rows[structure.header_row - 1]
    column_map = {column_name: index for index, column_name in enumerate(header)}
    status_column = structure.field_mapping.status.column_name
    mapping = load_status_mapping(DEFAULT_STATUS_MAPPING_PATH)
    unknown: list[str] = []
    seen: set[str] = set()
    for row in rows[structure.data_start_row - 1 :]:
        raw_status = _get_column_value(row, column_map, status_column)
        if not raw_status:
            continue
        if resolve_normalized_status(raw_status, mapping) is None and raw_status not in seen:
            seen.add(raw_status)
            unknown.append(raw_status)
    return unknown
```

并在 `normalize_bill_file()` 读完 `rows` 后立刻加：

```python
unknown_statuses = _collect_unknown_statuses(rows, structure)
if unknown_statuses:
    raise UnknownBillStatusesError(unknown_statuses)
```

- [ ] **Step 4: 接入标准状态和部分退款修正**

把 `normalize_bill_file()` 签名改成：

```python
def normalize_bill_file(
    input_path: str | Path,
    from_value: str,
    *,
    structure_resolver: Callable[[Path], BillStructureFileResult] | None = None,
    part_refund_amount_resolver: Callable[..., PartRefundAmountResult] = resolve_part_refund_amount,
) -> NormalizeBillFileResult:
```

在 `_normalize_rows()` 中用这段核心逻辑替换原来的正负判断：

```python
mapping = load_status_mapping(DEFAULT_STATUS_MAPPING_PATH)
normalized_status = resolve_normalized_status(status, mapping)
if normalized_status is None:
    raise RuntimeError(f"未识别的交易状态: {status}")

if normalized_status == "NORMAL_SUCCESS":
    adjusted_amount = f"{abs(float(raw_amount)):g}"
elif normalized_status == "REFUND":
    adjusted_amount = f"{-abs(float(raw_amount)):g}"
else:
    part_refund = part_refund_amount_resolver(
        counterparty=_get_column_value(row, column_map, field_mapping.counterparty.column_name),
        remark=_build_remark(row, column_map, field_mapping.remark_columns.column_names),
        status=status,
        amount=raw_amount,
        source=structure.source,
        transaction_time=_get_column_value(row, column_map, field_mapping.transaction_time.column_name),
    )
    adjusted_amount = f"{-abs(float(part_refund.refund_amount)):g}"

normalized_row = NormalizedBillRow(
    from_value=from_value,
    source=structure.source,
    transaction_time=...,
    counterparty=...,
    amount=adjusted_amount,
    status=status,
    normalized_status=normalized_status,
    remark=...,
)
```

- [ ] **Step 5: 让退款抵消基于标准状态**

把 `_apply_refund_offset()` 中的判断改成：

```python
if row.normalized_status == "NORMAL_SUCCESS":
    success_by_amount[abs_amount].append(idx)
elif row.normalized_status == "REFUND":
    refund_by_amount[abs_amount].append(idx)
```

把 `_write_normalized_excel()` 中的 notice 判断改成：

```python
notice = "" if row.normalized_status in ["NORMAL_SUCCESS", "REFUND", "PART_REFUND"] else "focus"
```

- [ ] **Step 6: 导出新增能力**

在 `src/beartools/bill/__init__.py` 中补充导出：

```python
from .models import BillRunProgressState, UnknownBillStatusesError

__all__ = [
    "normalize_bill_file",
    "analyze_bill_file",
    "run_bill_pipeline",
    "BillRunProgressState",
    "UnknownBillStatusesError",
]
```

- [ ] **Step 7: 运行 service 测试，确认转绿**

Run: `uv run pytest tests/test_bill_service.py -xvs`

Expected: PASS，新增的未知状态、PART_REFUND、标准状态驱动抵消测试全部通过。

- [ ] **Step 8: 提交本任务**

```bash
git add src/beartools/bill/models.py src/beartools/bill/service.py src/beartools/bill/__init__.py tests/test_bill_service.py
git commit -m "MOD: 接入账单标准状态处理"
```

---

### Task 4: command 层未知状态确认与重试

**Files:**
- Modify: `src/beartools/commands/bill/command.py`
- Modify: `tests/test_bill_command.py`

- [ ] **Step 1: 写 command 层失败测试**

在 `tests/test_bill_command.py` 追加：

```python
def test_normalize_prompts_unknown_status_and_retries() -> None:
    from beartools.bill.models import NormalizeBillFileResult, UnknownBillStatusesError

    result = NormalizeBillFileResult(
        input_path=Path("/tmp/alipay.csv"),
        output_path=Path("data/bill/2601-支付宝.xlsx"),
        source="支付宝",
        row_count=1,
        total_raw_data_rows=1,
        output_row_count=1,
    )
    calls: list[str] = []

    def fake_normalize(*_args, **_kwargs):
        if not calls:
            calls.append("first")
            raise UnknownBillStatusesError(["等待确认收货"])
        return result

    with (
        patch("beartools.commands.bill.command.normalize_bill_file", side_effect=fake_normalize),
        patch("beartools.commands.bill.command.append_exact_mapping") as mock_append,
        patch("beartools.commands.bill.command.typer.prompt", return_value="NORMAL_SUCCESS"),
    ):
        cli_result = runner.invoke(app, ["bill", "normalize", "/tmp/alipay.csv", "2601-"])

    assert cli_result.exit_code == 0
    mock_append.assert_called_once()
    assert "发现未识别的交易状态: 等待确认收货" in cli_result.stdout


def test_run_prompts_unknown_status_and_retries_pipeline() -> None:
    from beartools.bill.models import RunBillPipelineResult, UnknownBillStatusesError

    result = RunBillPipelineResult(
        input_path=Path("/tmp/input.csv"),
        normalized_output_path=Path("data/bill/2601-测试.xlsx"),
        analysis_output_path=Path("data/bill/2601-测试.analysis.xlsx"),
        source="测试",
        normalized_row_count=1,
        analysis_total_rows=1,
        analysis_failed_rows=0,
    )
    calls: list[str] = []

    def fake_run(*_args, **_kwargs):
        if not calls:
            calls.append("first")
            raise UnknownBillStatusesError(["等待确认收货"])
        return result

    class StubReporter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    with (
        patch("beartools.commands.bill.command.run_bill_pipeline", side_effect=fake_run),
        patch("beartools.commands.bill.command._BillRunProgressReporter", StubReporter),
        patch("beartools.commands.bill.command.append_exact_mapping") as mock_append,
        patch("beartools.commands.bill.command.typer.prompt", return_value="REFUND"),
    ):
        cli_result = runner.invoke(app, ["bill", "run", "/tmp/input.csv", "2601-"])

    assert cli_result.exit_code == 0
    mock_append.assert_called_once()
    assert "✅ 完整流程完成" in cli_result.stdout
```

- [ ] **Step 2: 运行 command 测试，确认当前失败**

Run: `uv run pytest tests/test_bill_command.py -xvs`

Expected: FAIL，`command.py` 还没有捕获 `UnknownBillStatusesError`，也没有调用 `append_exact_mapping`。

- [ ] **Step 3: 增加状态确认辅助函数**

在 `src/beartools/commands/bill/command.py` 头部补充导入：

```python
from pathlib import Path

from beartools.bill import BillRunProgressState, UnknownBillStatusesError, analyze_bill_file, normalize_bill_file, run_bill_pipeline
from beartools.bill.status_mapping import DEFAULT_STATUS_MAPPING_PATH, append_exact_mapping
```

并新增：

```python
def _confirm_unknown_statuses(statuses: list[str]) -> None:
    console.print(f"发现未识别的交易状态: {', '.join(statuses)}")
    for status in statuses:
        normalized_status = cast(
            str,
            typer.prompt(
                f"请确认状态 [{status}] 属于 NORMAL_SUCCESS / REFUND / PART_REFUND",
                default="NORMAL_SUCCESS",
            ),
        ).strip().upper()
        if normalized_status not in {"NORMAL_SUCCESS", "REFUND", "PART_REFUND"}:
            raise typer.BadParameter("状态只能是 NORMAL_SUCCESS / REFUND / PART_REFUND")
        append_exact_mapping(Path(DEFAULT_STATUS_MAPPING_PATH), status, normalized_status)
        console.print(f"已写入状态映射: {status} -> {normalized_status}")
```

- [ ] **Step 4: 为 normalize 命令加重试循环**

把 `normalize_bill()` 中的核心调用改成：

```python
while True:
    try:
        result = normalize_bill_file(input_path, from_value)
        break
    except UnknownBillStatusesError as exc:
        _confirm_unknown_statuses(exc.statuses)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc
```

- [ ] **Step 5: 为 run 命令加重试循环**

把 `run_bill()` 中的主流程调用改成：

```python
while True:
    try:
        reporter.start()
        result = run_bill_pipeline(input_path, from_value, progress_state=progress_state)
        break
    except UnknownBillStatusesError as exc:
        reporter.stop()
        reporter_stopped = True
        _confirm_unknown_statuses(exc.statuses)
        progress_state = BillRunProgressState()
        reporter = _BillRunProgressReporter(progress_state, console)
        reporter_stopped = False
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        reporter.stop()
        reporter_stopped = True
        console.print(f"❌ {exc}", style="red")
        raise typer.Exit(1) from exc
```

- [ ] **Step 6: 运行 command 测试，确认转绿**

Run: `uv run pytest tests/test_bill_command.py -xvs`

Expected: PASS，未知状态确认、原有 normalize / analysis / run 行为测试全部通过。

- [ ] **Step 7: 提交本任务**

```bash
git add src/beartools/commands/bill/command.py tests/test_bill_command.py
git commit -m "MOD: 增加未知状态人工确认"
```

---

### Task 5: 全量回归与代码质量验证

**Files:**
- Modify: `docs/superpowers/plans/2026-04-30-bill-status-mapping-implementation-plan.md`（仅勾选，不改内容）

- [ ] **Step 1: 运行 bill 相关测试**

Run: `uv run pytest tests/test_bill_status_mapping.py tests/test_bill_calculate_tool.py tests/test_bill_service.py tests/test_bill_agent.py tests/test_bill_command.py -xvs`

Expected: PASS，全部 bill 相关测试通过。

- [ ] **Step 2: 运行 ruff 检查**

Run: `uv run ruff check .`

Expected: PASS，无 lint 报错。

- [ ] **Step 3: 如有必要运行格式化**

Run: `uv run ruff format .`

Expected: PASS，仅在前一步提示格式问题时执行；执行后需重新运行 `uv run ruff check .`。

- [ ] **Step 4: 运行 mypy**

Run: `uv run mypy .`

Expected: PASS，无类型错误。

- [ ] **Step 5: 查看工作区变更**

Run: `git status --short`

Expected: 仅包含本次计划涉及文件，没有意外文件改动。

- [ ] **Step 6: 提交本任务**

```bash
git add config/bill_status_mapping.yaml src/beartools/bill/status_mapping.py src/beartools/bill/calculate_tool.py src/beartools/bill/models.py src/beartools/bill/agent.py src/beartools/bill/service.py src/beartools/bill/__init__.py src/beartools/commands/bill/command.py prompts/bill_part_refund_amount.md tests/test_bill_status_mapping.py tests/test_bill_calculate_tool.py tests/test_bill_service.py tests/test_bill_agent.py tests/test_bill_command.py
git commit -m "MOD: 完成账单状态映射与部分退款处理"
```

---

## 自检

- spec 覆盖检查：
  - YAML 配置：Task 1
  - exact + patterns：Task 1
  - 未知状态人工确认 + 写回：Task 4
  - `PART_REFUND` Tool Calling + `CalculateTool`：Task 2
  - 标准状态驱动金额与退款抵消：Task 3
  - bill 相关测试 / ruff / mypy：Task 5
- 占位符检查：无 `TODO` / `TBD` / “后续补充” 占位描述
- 类型一致性检查：计划统一使用 `BillNormalizedStatus`、`UnknownBillStatusesError`、`PartRefundAmountResult`、`calculate_expression`、`resolve_part_refund_amount` 这些命名
