"""账单结构识别 Agent。"""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI
from pydantic_ai import Agent

from beartools.llm.factory import LLFactory
from beartools.llm.pydantic_openai import create_openai_responses_model
from beartools.llm.runtime import RuntimeNode, get_llm_runtime
from beartools.prompt import get_prompt_manager

from .calculate_tool import calculate_expression
from .models import (
    BillAnalysisResult,
    BillPreview,
    BillStructureFileResult,
    BillStructureResult,
    PartRefundAmountResult,
)


async def _create_openai_client(node: RuntimeNode) -> AsyncOpenAI:
    """由账单调用方获取 OpenAI 兼容 SDK client。"""

    client = await LLFactory().create_async_client_for_node(node)
    if not isinstance(client, AsyncOpenAI):
        raise RuntimeError("bill 当前只支持 OpenAI 兼容 client")
    return client


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
    return asyncio.run(_resolve_bill_structure_async(prompt))


async def _resolve_bill_structure_async(prompt: str) -> BillStructureFileResult:
    """异步调用 LLM 识别单个账单文件结构。"""

    runtime = get_llm_runtime()
    max_attempts = len(runtime.available_nodes)
    for _ in range(max_attempts):
        node = runtime.get_active_node()
        try:
            client = await _create_openai_client(node)
            async with client:
                model = create_openai_responses_model(
                    client,
                    model_name=node.model,
                    timeout_seconds=float(node.timeout_seconds),
                )
                agent: Agent[None, BillStructureResult] = Agent(
                    model,
                    output_type=BillStructureResult,
                    system_prompt="你是账单结构识别助手，只能返回符合 schema 的 JSON。",
                )
                result = await agent.run(prompt)
        except Exception as exc:
            runtime.mark_node_failed(node, error=exc)
            raise

        output = result.output
        if not output.files:
            raise RuntimeError("LLM 未返回任何账单结构结果")
        return output.files[0]

    raise RuntimeError("LLM 请求失败，且没有可用的健康节点")


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
    return asyncio.run(_analyze_bill_row_async(node, prompt))


async def _analyze_bill_row_async(node: RuntimeNode, prompt: str) -> BillAnalysisResult:
    """异步调用 LLM 分析单行账单。"""

    client = await _create_openai_client(node)
    async with client:
        model = create_openai_responses_model(
            client,
            model_name=node.model,
            timeout_seconds=float(node.timeout_seconds),
        )
        agent: Agent[None, BillAnalysisResult] = Agent(
            model,
            output_type=BillAnalysisResult,
            system_prompt="你是账单分类分析助手，只能返回符合 schema 的 JSON。",
        )
        result = await agent.run(prompt)
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
    return asyncio.run(_resolve_part_refund_amount_async(node, prompt))


async def _resolve_part_refund_amount_async(node: RuntimeNode, prompt: str) -> PartRefundAmountResult:
    """异步调用 LLM 修正部分退款金额。"""

    client = await _create_openai_client(node)
    async with client:
        model = create_openai_responses_model(
            client,
            model_name=node.model,
            timeout_seconds=float(node.timeout_seconds),
        )
        agent: Agent[None, PartRefundAmountResult] = Agent(
            model,
            output_type=PartRefundAmountResult,
            system_prompt="你是部分退款金额修正助手，只能返回符合 schema 的 JSON。",
        )

        def calculate_tool(expression: str) -> str:
            """执行四则运算表达式并返回两位小数字符串。"""

            return calculate_expression(expression)

        agent.tool_plain(calculate_tool)
        result = await agent.run(prompt)
        return result.output
