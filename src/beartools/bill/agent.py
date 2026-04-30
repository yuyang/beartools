"""账单结构识别 Agent。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from pydantic_ai import Agent

from beartools.llm.factory import LLFactory
from beartools.llm.runtime import get_llm_runtime
from beartools.prompt import get_prompt_manager

from .calculate_tool import calculate_expression
from .models import (
    BillAnalysisResult,
    BillPreview,
    BillStructureFileResult,
    BillStructureResult,
    PartRefundAmountResult,
)


class _BillStructureRunResult(Protocol):
    output: BillStructureResult


def resolve_bill_structure(preview: BillPreview) -> BillStructureFileResult:
    """调用 LLM 识别单个账单文件结构。"""

    prompt = get_prompt_manager().render(
        "bill_structure_identification_fewshot",
        {
            "file_name": preview.file_name,
            "file_type": preview.file_type,
            "file_content": preview.file_content,
        },
    )
    runtime = get_llm_runtime()
    max_attempts = len(runtime.available_nodes)

    for _ in range(max_attempts):
        node = runtime.get_active_node()
        model = LLFactory().create(node=node)
        agent = Agent(
            model,
            output_type=BillStructureResult,
            system_prompt="你是账单结构识别助手，只能返回符合 schema 的 JSON。",
        )
        try:
            result = cast(_BillStructureRunResult, agent.run_sync(prompt))
        except Exception as exc:
            runtime.mark_node_failed(node, error=exc)
            raise

        output = result.output
        if not output.files:
            raise RuntimeError("LLM 未返回任何账单结构结果")
        return output.files[0]

    raise RuntimeError("LLM 请求失败，且没有可用的健康节点")


class _BillAnalysisRunResult(Protocol):
    output: BillAnalysisResult


class _PartRefundRunResult(Protocol):
    output: PartRefundAmountResult


def analyze_bill_row(
    counterparty: str,
    remark: str,
    status: str,
    amount: str,
) -> BillAnalysisResult:
    """调用 LLM 分析单行账单交易对方和交易用途。"""

    prompt = get_prompt_manager().render(
        "bill_transaction_analysis",
        {
            "counterparty": counterparty,
            "remark": remark,
            "status": status,
            "amount": amount,
        },
    )
    runtime = get_llm_runtime()
    node = runtime.get_active_node()
    model = LLFactory().create(node=node)
    agent = Agent(
        model,
        output_type=BillAnalysisResult,
        system_prompt="你是账单分类分析助手，只能返回符合 schema 的 JSON。",
    )
    result = cast(_BillAnalysisRunResult, agent.run_sync(prompt))
    return result.output


def resolve_part_refund_amount(
    *,
    counterparty: str,
    remark: str,
    status: str,
    amount: str,
    source: str,
    transaction_time: str,
) -> PartRefundAmountResult:
    """调用 LLM 修正部分退款金额。"""

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

    tool_plain = cast(Callable[[Callable[[str], str]], Callable[[str], str]], agent.tool_plain)

    @tool_plain
    def calculate_tool(expression: str) -> str:
        """执行四则运算表达式并返回两位小数字符串。"""

        return calculate_expression(expression)

    result = cast(_PartRefundRunResult, agent.run_sync(prompt))
    return result.output
