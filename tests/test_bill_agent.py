from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from unittest.mock import Mock, patch

import pytest


class _RuntimeNodeLike(Protocol):
    name: str


class _RuntimeLike(Protocol):
    def get_active_node(self) -> _RuntimeNodeLike: ...

    def mark_node_failed(self, node: _RuntimeNodeLike, error: BaseException | None = None) -> bool: ...


def test_resolve_bill_structure_returns_first_file_result() -> None:
    from beartools.bill.agent import resolve_bill_structure
    from beartools.bill.models import (
        BillFieldDetail,
        BillFieldMapping,
        BillPreview,
        BillRemarkColumns,
        BillStructureFileResult,
    )

    preview = BillPreview(file_name="wechat.xlsx", file_type="xlsx", file_content="1: 标题")
    expected = BillStructureFileResult(
        file_name="wechat.xlsx",
        source="微信",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(confidence="high", reason="", column_name="交易时间"),
            counterparty=BillFieldDetail(confidence="high", reason="", column_name="交易对方"),
            amount=BillFieldDetail(confidence="high", reason="", column_name="金额"),
            status=BillFieldDetail(confidence="high", reason="", column_name="状态"),
            remark_columns=BillRemarkColumns(confidence="high", reason="", column_names=["备注"]),
        ),
    )

    @dataclass
    class _FakeRunResult:
        output: object

    class _FakeAgent:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def run_sync(self, _prompt: str) -> _FakeRunResult:
            return _FakeRunResult(output=type("_Output", (), {"files": [expected]})())

    @dataclass(frozen=True)
    class _RuntimeNode:
        name: str

    class _FakeRuntime:
        available_nodes = [_RuntimeNode("primary")]

        def get_active_node(self) -> _RuntimeNode:
            return self.available_nodes[0]

        def mark_node_failed(self, node: _RuntimeNode, error: BaseException | None = None) -> bool:
            return False

    with (
        patch("beartools.bill.agent.get_llm_runtime", return_value=_FakeRuntime()),
        patch("beartools.bill.agent.LLFactory.create", return_value="fake-model"),
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
        result = resolve_bill_structure(preview)

    assert result == expected


def test_resolve_bill_structure_marks_failed_node_and_raises_current_error() -> None:
    from beartools.bill.agent import resolve_bill_structure
    from beartools.bill.models import (
        BillFieldDetail,
        BillFieldMapping,
        BillPreview,
        BillRemarkColumns,
        BillStructureFileResult,
    )

    @dataclass(frozen=True)
    class _RuntimeNode:
        name: str

    class _FakeRuntime:
        def __init__(self) -> None:
            self.nodes = [_RuntimeNode("primary"), _RuntimeNode("candidate")]
            self.index = 0
            self.marked: list[str] = []

        @property
        def available_nodes(self) -> list[_RuntimeNode]:
            return self.nodes[self.index :]

        def get_active_node(self) -> _RuntimeNode:
            return self.nodes[self.index]

        def mark_node_failed(self, node: _RuntimeNode, error: BaseException | None = None) -> bool:
            self.marked.append(node.name)
            self.index = 1
            return True

    preview = BillPreview(file_name="wechat.xlsx", file_type="xlsx", file_content="1: 标题")
    expected = BillStructureFileResult(
        file_name="wechat.xlsx",
        source="微信",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(confidence="high", reason="", column_name="交易时间"),
            counterparty=BillFieldDetail(confidence="high", reason="", column_name="交易对方"),
            amount=BillFieldDetail(confidence="high", reason="", column_name="金额"),
            status=BillFieldDetail(confidence="high", reason="", column_name="状态"),
            remark_columns=BillRemarkColumns(confidence="high", reason="", column_names=["备注"]),
        ),
    )

    @dataclass
    class _FakeRunResult:
        output: object

    class _FakeAgent:
        def __init__(self, model: object, **_kwargs: object) -> None:
            self.model = model

        def run_sync(self, _prompt: str) -> _FakeRunResult:
            if self.model == "model-primary":
                raise TimeoutError("timed out")
            return _FakeRunResult(output=type("_Output", (), {"files": [expected]})())

    runtime = _FakeRuntime()

    with (
        patch("beartools.bill.agent.get_llm_runtime", return_value=runtime),
        patch("beartools.bill.agent.LLFactory.create", return_value="model-primary") as mock_create,
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
        try:
            resolve_bill_structure(preview)
        except TimeoutError as exc:
            assert str(exc) == "timed out"
        else:
            raise AssertionError("预期抛出 TimeoutError")

    assert runtime.marked == ["primary"]
    assert mock_create.call_count == 1


def test_resolve_bill_structure_next_request_uses_reselected_node() -> None:
    from beartools.bill.agent import resolve_bill_structure
    from beartools.bill.models import (
        BillFieldDetail,
        BillFieldMapping,
        BillPreview,
        BillRemarkColumns,
        BillStructureFileResult,
    )

    @dataclass(frozen=True)
    class _RuntimeNode:
        name: str

    class _FakeRuntime:
        def __init__(self) -> None:
            self.nodes = [_RuntimeNode("primary"), _RuntimeNode("candidate")]
            self.marked: list[str] = []
            self.current = 0

        @property
        def available_nodes(self) -> list[_RuntimeNode]:
            return self.nodes[self.current :]

        def get_active_node(self) -> _RuntimeNode:
            return self.available_nodes[0]

        def mark_node_failed(self, node: _RuntimeNode, error: BaseException | None = None) -> bool:
            self.marked.append(node.name)
            self.current = 1
            return True

    preview = BillPreview(file_name="wechat.xlsx", file_type="xlsx", file_content="1: 标题")
    expected = BillStructureFileResult(
        file_name="wechat.xlsx",
        source="微信",
        header_row=2,
        data_start_row=3,
        field_mapping=BillFieldMapping(
            transaction_time=BillFieldDetail(confidence="high", reason="", column_name="交易时间"),
            counterparty=BillFieldDetail(confidence="high", reason="", column_name="交易对方"),
            amount=BillFieldDetail(confidence="high", reason="", column_name="金额"),
            status=BillFieldDetail(confidence="high", reason="", column_name="状态"),
            remark_columns=BillRemarkColumns(confidence="high", reason="", column_names=["备注"]),
        ),
    )

    @dataclass
    class _FakeRunResult:
        output: object

    class _FakeAgent:
        def __init__(self, model: object, **_kwargs: object) -> None:
            self.model = model

        def run_sync(self, _prompt: str) -> _FakeRunResult:
            if self.model == "model-primary":
                raise TimeoutError("timed out")
            return _FakeRunResult(output=type("_Output", (), {"files": [expected]})())

    runtime = _FakeRuntime()

    with (
        patch("beartools.bill.agent.get_llm_runtime", return_value=runtime),
        patch("beartools.bill.agent.LLFactory.create", side_effect=["model-primary", "model-candidate"]) as mock_create,
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
        try:
            resolve_bill_structure(preview)
        except TimeoutError:
            pass
        else:
            raise AssertionError("预期首次请求抛出 TimeoutError")

        result = resolve_bill_structure(preview)

    assert result == expected
    assert runtime.marked == ["primary"]
    assert mock_create.call_count == 2


def test_resolve_bill_structure_raises_without_failover() -> None:
    from beartools.bill.agent import resolve_bill_structure
    from beartools.bill.models import BillPreview

    @dataclass(frozen=True)
    class _RuntimeNode:
        name: str

    class _FakeRuntime:
        def __init__(self) -> None:
            self.node = _RuntimeNode("primary")
            self.mark_node_failed = Mock(return_value=False)

        @property
        def available_nodes(self) -> list[_RuntimeNode]:
            return [self.node]

        def get_active_node(self) -> _RuntimeNode:
            return self.node

    class _FakeAgent:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def run_sync(self, _prompt: str) -> object:
            raise RuntimeError("bad request")

    runtime = _FakeRuntime()
    preview = BillPreview(file_name="wechat.xlsx", file_type="xlsx", file_content="1: 标题")

    with (
        patch("beartools.bill.agent.get_llm_runtime", return_value=runtime),
        patch("beartools.bill.agent.LLFactory.create", return_value="model-primary") as mock_create,
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
        try:
            resolve_bill_structure(preview)
        except RuntimeError as exc:
            assert str(exc) == "bad request"
        else:
            raise AssertionError("预期抛出 RuntimeError")

    runtime.mark_node_failed.assert_called_once()
    assert mock_create.call_count == 1


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
            self.registered_tool = None

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


def test_analyze_bill_row_returns_correct_result() -> None:
    from beartools.bill.agent import analyze_bill_row
    from beartools.bill.models import (
        BillAnalysisResult,
    )

    expected = BillAnalysisResult(
        owner="vv",
        purpose="餐饮消费/午晚餐",
    )

    @dataclass
    class _FakeRunResult:
        output: object

    class _FakeAgent:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def run_sync(self, _prompt: str) -> _FakeRunResult:
            return _FakeRunResult(output=expected)

    class _FakePromptManager:
        def render(self, *_args: object, **_kwargs: object) -> str:
            return "fake prompt"

    @dataclass(frozen=True)
    class _RuntimeNode:
        name: str

    class _FakeRuntime:
        @property
        def available_nodes(self) -> list[_RuntimeNode]:
            return [_RuntimeNode("primary")]

        def get_active_node(self) -> _RuntimeNode:
            return self.available_nodes[0]

    with (
        patch("beartools.bill.agent.get_prompt_manager", return_value=_FakePromptManager()),
        patch("beartools.bill.agent.get_llm_runtime", return_value=_FakeRuntime()),
        patch("beartools.bill.agent.LLFactory.create", return_value="fake-model"),
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
        result = analyze_bill_row(
            counterparty="美团",
            remark="美团外卖订单",
            status="交易成功",
            amount="35.80",
        )

    assert result == expected


def test_analyze_bill_row_propagates_exception() -> None:
    from beartools.bill.agent import analyze_bill_row

    class _FakeAgent:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def run_sync(self, _prompt: str) -> None:
            raise ConnectionError("network error")

    class _FakePromptManager:
        def render(self, *_args: object, **_kwargs: object) -> str:
            return "fake prompt"

    @dataclass(frozen=True)
    class _RuntimeNode:
        name: str

    class _FakeRuntime:
        @property
        def available_nodes(self) -> list[_RuntimeNode]:
            return [_RuntimeNode("primary")]

        def get_active_node(self) -> _RuntimeNode:
            return self.available_nodes[0]

    with (
        patch("beartools.bill.agent.get_prompt_manager", return_value=_FakePromptManager()),
        patch("beartools.bill.agent.get_llm_runtime", return_value=_FakeRuntime()),
        patch("beartools.bill.agent.LLFactory.create", return_value="fake-model"),
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
        with pytest.raises(ConnectionError, match="network error"):
            analyze_bill_row(
                counterparty="美团",
                remark="美团外卖订单",
                status="交易成功",
                amount="35.80",
            )
