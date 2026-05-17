"""LLM 健康检查。

检查当前配置中的 LLM 节点是否至少存在一个可用节点。
"""

from __future__ import annotations

import time
from typing import Literal, Protocol

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.config import get_config
from beartools.llm.factory import LLFactory

type _AgentTier = Literal["large", "small"]


class _DoctorAgentNode(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    @property
    def model(self) -> str: ...


def _build_tier_summary(
    *,
    tiers: tuple[_AgentTier, _AgentTier],
    healthy_nodes: list[tuple[_AgentTier, _DoctorAgentNode]],
    failed_nodes: list[tuple[_AgentTier, str]],
    tier_configured_nodes: dict[_AgentTier, list[_DoctorAgentNode]],
) -> str:
    parts: list[str] = []
    for tier in tiers:
        total = len(tier_configured_nodes[tier])
        healthy = sum(1 for node_tier, _ in healthy_nodes if node_tier == tier)
        parts.append(f"{tier} {healthy}/{total}")
    return "，".join(parts)


def _probe_tier_nodes(
    *,
    tiers: tuple[_AgentTier, _AgentTier],
    tier_configured_nodes: dict[_AgentTier, list[_DoctorAgentNode]],
) -> tuple[list[tuple[_AgentTier, _DoctorAgentNode]], list[tuple[_AgentTier, str]]]:
    healthy_nodes: list[tuple[_AgentTier, _DoctorAgentNode]] = []
    failed_nodes: list[tuple[_AgentTier, str]] = []

    for tier in tiers:
        configured_nodes = tier_configured_nodes[tier]
        for node in configured_nodes:
            try:
                client = LLFactory().create_client(name=node.name, type="any", model_size=tier)
                with client:
                    pass
                healthy_nodes.append((tier, node))
            except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
                reason = f"{node.name}({node.base_url}, {node.model}): {str(exc)}"
                failed_nodes.append((tier, reason))

    return healthy_nodes, failed_nodes


def _build_detail_lines(
    *,
    tiers: tuple[_AgentTier, _AgentTier],
    healthy_nodes: list[tuple[_AgentTier, _DoctorAgentNode]],
    failed_nodes: list[tuple[_AgentTier, str]],
) -> list[str]:
    detail_lines: list[str] = [f"汇总：可用 {len(healthy_nodes)}，不可用 {len(failed_nodes)}"]

    for tier in tiers:
        tier_healthy_nodes = [node for node_tier, node in healthy_nodes if node_tier == tier]
        if tier_healthy_nodes:
            detail_lines.append(f"✅ {tier} 可用节点：")
            detail_lines.extend(f"  {node.name} | {node.model} | {node.base_url}" for node in tier_healthy_nodes)

    for tier in tiers:
        tier_failed_nodes = [reason for node_tier, reason in failed_nodes if node_tier == tier]
        if tier_failed_nodes:
            detail_lines.append(f"❌ {tier} 不可用节点：")
            detail_lines.extend(f"  {reason}" for reason in tier_failed_nodes)

    return detail_lines


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
        tiers: tuple[_AgentTier, _AgentTier] = ("large", "small")
        agent_config = get_config().agent
        tier_configured_nodes: dict[_AgentTier, list[_DoctorAgentNode]] = {
            "large": list(agent_config.large),
            "small": list(agent_config.small),
        }

        if not any(tier_configured_nodes.values()):
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message="LLM 健康检查失败：未配置任何 LLM 节点",
                duration=time.time() - start_time,
                detail=None,
            )

        healthy_nodes, failed_nodes = _probe_tier_nodes(tiers=tiers, tier_configured_nodes=tier_configured_nodes)

        duration = time.time() - start_time
        summary = _build_tier_summary(
            tiers=tiers,
            healthy_nodes=healthy_nodes,
            failed_nodes=failed_nodes,
            tier_configured_nodes=tier_configured_nodes,
        )

        if healthy_nodes:
            detail = "\n".join(_build_detail_lines(tiers=tiers, healthy_nodes=healthy_nodes, failed_nodes=failed_nodes))
            return CheckResult(
                name=self.name,
                status=CheckStatus.SUCCESS,
                message=f"LLM 节点检查通过：{summary}",
                duration=duration,
                detail=detail,
            )
        else:
            detail = "\n".join(_build_detail_lines(tiers=tiers, healthy_nodes=healthy_nodes, failed_nodes=failed_nodes))
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message=f"LLM 节点检查失败：{summary}",
                duration=duration,
                detail=detail,
            )
