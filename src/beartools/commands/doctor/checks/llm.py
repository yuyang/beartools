"""LLM 健康检查。

检查当前配置中的 LLM 节点是否至少存在一个可用节点。
"""

from __future__ import annotations

import time

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.llm.runtime import LLMRuntimeInitializationError, create_llm_runtime


@register_check
class LLMCheck(BaseCheck):
    """LLM 节点健康检查项。"""

    @property
    def name(self) -> str:
        """检查项名称。"""
        return "llm"

    @property
    def description(self) -> str:
        """检查项描述。"""
        return "检查是否至少存在一个可用的 LLM 节点"

    async def run(self) -> CheckResult:
        """执行 LLM 健康检查。"""
        start_time = time.time()

        try:
            runtime = create_llm_runtime()
            healthy_nodes = runtime.healthy_nodes
            duration = time.time() - start_time
            detail = "\n".join(f"{node.name} | {node.model} | {node.base_url}" for node in healthy_nodes) or None
            return CheckResult(
                name=self.name,
                status=CheckStatus.SUCCESS,
                message=f"检测到 {len(healthy_nodes)} 个可用 LLM 节点",
                duration=duration,
                detail=detail,
            )
        except LLMRuntimeInitializationError as exc:
            duration = time.time() - start_time
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message="LLM 健康检查失败",
                duration=duration,
                detail=str(exc),
            )
