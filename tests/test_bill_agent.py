from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from unittest.mock import Mock, patch


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


def test_resolve_bill_structure_failover_to_next_node() -> None:
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
        patch("beartools.bill.agent.LLFactory.create", side_effect=["model-primary", "model-candidate"]) as mock_create,
        patch("beartools.bill.agent.Agent", _FakeAgent),
    ):
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
