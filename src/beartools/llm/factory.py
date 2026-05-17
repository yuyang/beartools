"""LLM SDK client 工厂。

本模块只负责从运行时节点中选择配置并构建 OpenAI/Anthropic SDK client。
PydanticAI 模型封装和 client 关闭都由调用方负责。
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Literal, Protocol, cast

from anthropic import Anthropic, AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

from beartools.llm.runtime import AgentTier, LLRuntime, RuntimeNode, get_llm_runtime, probe_runtime_node
from beartools.logger import get_logger

ProviderType = Literal["openai", "openrouter", "anthropic", "any"]
ProviderFamily = Literal["openai", "anthropic"]
type SyncLLMClient = OpenAI | Anthropic
type AsyncLLMClient = AsyncOpenAI | AsyncAnthropic


class _LoggerProtocol(Protocol):
    def info(self, msg: str, *args: object) -> None: ...


class LLFactoryError(RuntimeError):
    """LLM 工厂配置或选择错误。"""


def _get_logger() -> _LoggerProtocol:
    """延迟获取日志器，避免模块导入阶段触发配置加载。"""

    return cast(_LoggerProtocol, get_logger(__name__))


def _supports_default_headers() -> bool:
    """判断当前 OpenAI 客户端是否支持默认请求头。"""

    return "default_headers" in inspect.signature(OpenAI).parameters


def _normalize_provider_family(provider: str) -> ProviderFamily:
    """把配置 provider 归一为 SDK family。"""

    if provider in {"openai", "openrouter"}:
        return "openai"
    if provider == "anthropic":
        return "anthropic"
    raise LLFactoryError(f"不支持的 provider: {provider}")


def _normalize_type(provider_type: str) -> ProviderType:
    """校验并归一 type 参数。"""

    if provider_type in {"openai", "openrouter", "anthropic", "any"}:
        return cast(ProviderType, provider_type)
    raise LLFactoryError(f"type 仅支持 openai/openrouter/anthropic/any，不支持: {provider_type}")


def _type_matches_provider(provider_type: ProviderType, node: RuntimeNode) -> bool:
    """判断 type 过滤条件是否匹配节点 provider。"""

    if provider_type == "any":
        return True
    node_family = _normalize_provider_family(node.provider)
    if provider_type in {"openai", "openrouter"}:
        return node_family == "openai"
    return node_family == "anthropic"


@dataclass
class LLFactory:
    """从运行时节点构建 SDK client 的轻量工厂。"""

    logger: _LoggerProtocol | None = None

    def create_client(
        self,
        *,
        model: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> SyncLLMClient:
        """按 model/type/model_size 选择节点并构建同步 SDK client。"""

        runtime_node = self._select_valid_node(get_llm_runtime(), model=model, provider_type=type, tier=model_size)
        return self.create_client_for_node(runtime_node)

    def create_client_for_node(self, node: RuntimeNode) -> SyncLLMClient:
        """按已选 RuntimeNode 构建同步 SDK client。"""

        probe_runtime_node(node)
        self._log_node(node)
        provider_family = _normalize_provider_family(node.provider)
        if provider_family == "openai":
            return self._create_openai_client(node)
        return self._create_anthropic_client(node)

    async def create_async_client(
        self,
        *,
        model: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> AsyncLLMClient:
        """按 model/type/model_size 选择节点并构建异步 SDK client。"""

        runtime_node = self._select_valid_node(get_llm_runtime(), model=model, provider_type=type, tier=model_size)
        return await self.create_async_client_for_node(runtime_node)

    async def create_async_client_for_node(self, node: RuntimeNode) -> AsyncLLMClient:
        """按已选 RuntimeNode 构建异步 SDK client。"""

        probe_runtime_node(node)
        self._log_node(node)
        provider_family = _normalize_provider_family(node.provider)
        if provider_family == "openai":
            return self._create_async_openai_client(node)
        return self._create_async_anthropic_client(node)

    def _select_valid_node(
        self,
        runtime: LLRuntime,
        *,
        model: str | None,
        provider_type: ProviderType,
        tier: AgentTier,
    ) -> RuntimeNode:
        """选择并探测当前可用节点，失败时切换到下一个节点。"""

        normalized_type = _normalize_type(provider_type)
        while True:
            runtime_node = self._find_candidate_node(runtime, model=model, provider_type=normalized_type, tier=tier)
            try:
                probe_runtime_node(runtime_node)
            except Exception as exc:
                changed = runtime.mark_node_failed(runtime_node, error=exc, tier=tier)
                if not changed:
                    raise
                continue
            return runtime_node

    def _find_candidate_node(
        self,
        runtime: LLRuntime,
        *,
        model: str | None,
        provider_type: ProviderType,
        tier: AgentTier,
    ) -> RuntimeNode:
        """从指定 tier 的可用节点中按条件选出第一个候选节点。"""

        candidates = [
            node
            for node in runtime.available_nodes_for_tier(tier)
            if _type_matches_provider(provider_type, node) and _model_matches(model, node)
        ]
        if candidates:
            return candidates[0]

        available = ", ".join(
            f"{node.name}/{node.provider}/{node.model}" for node in runtime.available_nodes_for_tier(tier)
        )
        filter_text = f"model={model or '*'}, type={provider_type}, model_size={tier}"
        raise LLFactoryError(f"未找到匹配的 LLM 节点: {filter_text}；可用节点: {available}")

    def _create_openai_client(self, node: RuntimeNode) -> SyncLLMClient:
        """构建同步 OpenAI 兼容 client。"""

        if node.extra_headers and not _supports_default_headers():
            raise LLFactoryError("当前环境的 OpenAI 客户端不支持 extra_headers，无法安全传递请求头")
        return OpenAI(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=float(node.timeout_seconds),
            default_headers=node.extra_headers,
        )

    def _create_async_openai_client(self, node: RuntimeNode) -> AsyncLLMClient:
        """构建异步 OpenAI 兼容 client。"""

        if node.extra_headers and not _supports_default_headers():
            raise LLFactoryError("当前环境的 OpenAI 客户端不支持 extra_headers，无法安全传递请求头")
        return AsyncOpenAI(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=float(node.timeout_seconds),
            default_headers=node.extra_headers,
        )

    def _create_anthropic_client(self, node: RuntimeNode) -> SyncLLMClient:
        """构建同步 Anthropic client。"""

        return Anthropic(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=float(node.timeout_seconds),
            default_headers=node.extra_headers,
        )

    def _create_async_anthropic_client(self, node: RuntimeNode) -> AsyncLLMClient:
        """构建异步 Anthropic client。"""

        return AsyncAnthropic(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=float(node.timeout_seconds),
            default_headers=node.extra_headers,
        )

    def _log_node(self, node: RuntimeNode) -> None:
        """记录最终选中的节点。"""

        active_logger = self.logger or _get_logger()
        active_logger.info(
            "LLM 选择节点: name=%s provider=%s base_url=%s model=%s",
            node.name,
            node.provider,
            node.base_url,
            node.model,
        )


def _model_matches(model: str | None, node: RuntimeNode) -> bool:
    """判断 model 参数是否匹配节点 name 或 model。"""

    if model is None or not model.strip():
        return True
    normalized_model = model.strip()
    return node.name == normalized_model or node.model == normalized_model


__all__ = [
    "LLFactory",
    "LLFactoryError",
    "AsyncLLMClient",
    "ProviderFamily",
    "ProviderType",
    "SyncLLMClient",
]
