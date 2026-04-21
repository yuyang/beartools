"""LLM 健康检查。

检查当前配置中的 LLM 节点是否至少存在一个可用节点。
"""

from __future__ import annotations

import time

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.llm.runtime import (
    _collect_configured_nodes,
    _probe_node,
)


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
        configured_nodes = _collect_configured_nodes()

        if not configured_nodes:
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message="LLM 健康检查失败：未配置任何 LLM 节点",
                duration=time.time() - start_time,
                detail=None,
            )

        healthy_nodes = []
        failed_nodes = []

        for node in configured_nodes:
            try:
                _probe_node(node)
                healthy_nodes.append(node)
            except Exception as exc:
                reason = f"{node.name}({node.base_url}, {node.model}): {str(exc)}"
                failed_nodes.append(reason)

        duration = time.time() - start_time

        if healthy_nodes:
            detail_lines = ["✅ 可用节点："]
            detail_lines.extend(f"  {node.name} | {node.model} | {node.base_url}" for node in healthy_nodes)
            if failed_nodes:
                detail_lines.append("\n❌ 不可用节点：")
                detail_lines.extend(f"  {reason}" for reason in failed_nodes)
            detail = "\n".join(detail_lines)
            return CheckResult(
                name=self.name,
                status=CheckStatus.SUCCESS,
                message=f"检测到 {len(healthy_nodes)} 个可用 LLM 节点，{len(failed_nodes)} 个不可用",
                duration=duration,
                detail=detail,
            )
        else:
            detail = "\n".join(f"❌ {reason}" for reason in failed_nodes) if failed_nodes else "未知原因"
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message="LLM 健康检查失败：没有可用的健康节点",
                duration=duration,
                detail=detail,
            )
