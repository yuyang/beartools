"""LLM SDK client 工厂。

本模块保留为轻量公开入口，实际节点选择委托给 LLRuntime。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from anthropic import Anthropic, AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

from beartools.llm.runtime import AgentTier, ProviderType, RuntimeNodeSummary, get_llm_runtime
from beartools.logger import get_logger

type SyncLLMClient = OpenAI | Anthropic
type AsyncLLMClient = AsyncOpenAI | AsyncAnthropic


class _LoggerProtocol(Protocol):
    def info(self, msg: str, *args: object) -> None: ...


class LLFactoryError(RuntimeError):
    """LLM 工厂配置或选择错误。"""


def _get_logger() -> _LoggerProtocol:
    return cast(_LoggerProtocol, get_logger(__name__))


def _normalize_type(provider_type: str) -> ProviderType:
    if provider_type in {"openai", "anthropic", "any"}:
        return cast(ProviderType, provider_type)
    raise LLFactoryError(f"type 仅支持 openai/anthropic/any，不支持: {provider_type}")


@dataclass
class LLFactory:
    """基于 LLRuntime 的轻量 client 工厂。"""

    logger: _LoggerProtocol | None = None

    def create_client(
        self,
        *,
        name: str | None = None,
        model: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> SyncLLMClient:
        summary = self._select_summary(name=name, model=model, provider_type=type, tier=model_size)
        self._log_selection(summary.name, summary.provider, model_size)
        return get_llm_runtime().create_client(summary.name, model_size)

    async def create_async_client(
        self,
        *,
        name: str | None = None,
        model: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> AsyncLLMClient:
        summary = self._select_summary(name=name, model=model, provider_type=type, tier=model_size)
        self._log_selection(summary.name, summary.provider, model_size)
        return await get_llm_runtime().create_async_client(summary.name, model_size)

    def _select_summary(
        self,
        *,
        name: str | None,
        model: str | None,
        provider_type: ProviderType,
        tier: AgentTier,
    ) -> RuntimeNodeSummary:
        normalized_type = _normalize_type(provider_type)
        summaries = get_llm_runtime().list_models(normalized_type, tier)
        target = name if name is not None and name.strip() else model
        if target is None or not target.strip():
            if summaries:
                return summaries[0]
            raise LLFactoryError(f"未找到匹配的 LLM 节点: model=*, type={normalized_type}, model_size={tier}")

        normalized_model = target.strip()
        for summary in summaries:
            if summary.name == normalized_model or summary._model == normalized_model:
                return summary
        available = ", ".join(f"{summary.name}/{summary.provider}/{summary._model}" for summary in summaries)
        raise LLFactoryError(
            f"未找到匹配的 LLM 节点: model={normalized_model}, type={normalized_type}, model_size={tier}；可用节点: {available}"
        )

    def _log_selection(self, name: str, provider: str, tier: AgentTier) -> None:
        active_logger = self.logger or _get_logger()
        active_logger.info("LLM 选择节点: tier=%s name=%s provider=%s", tier, name, provider)


__all__ = [
    "AsyncLLMClient",
    "LLFactory",
    "LLFactoryError",
    "ProviderType",
    "SyncLLMClient",
]
