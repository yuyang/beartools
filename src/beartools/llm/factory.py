"""LLM SDK client 工厂。

本模块是业务调用方的统一公开入口；运行时节点、探活和敏感配置只作为内部细节处理。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast, runtime_checkable

from anthropic import Anthropic, AsyncAnthropic
import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI

from beartools.config import AgentNodeConfig, get_config
from beartools.llm.runtime import (
    AgentTier,
    LLMRuntimeError,
    ProviderType,
    RuntimeNode,
    probe_async_runtime_node,
    probe_runtime_node,
)
from beartools.logger import get_logger

type SyncLLMClient = OpenAI | Anthropic
type AsyncLLMClient = AsyncOpenAI | AsyncAnthropic


@dataclass(frozen=True, slots=True)
class LLMCandidate:
    """公开候选摘要，不包含 base_url/api_key 等敏感配置。"""

    name: str
    tier: AgentTier
    provider: Literal["openai", "anthropic"]
    model: str
    timeout_seconds: int


class _LoggerProtocol(Protocol):
    def info(self, msg: str, *args: object) -> None: ...


@runtime_checkable
class _SyncCloseable(Protocol):
    def close(self) -> object: ...


@runtime_checkable
class _AsyncCloseable(Protocol):
    async def close(self) -> object: ...


class LLFactoryError(RuntimeError):
    """LLM 工厂配置或选择错误。"""


def _get_logger() -> _LoggerProtocol:
    return cast(_LoggerProtocol, get_logger(__name__))


def _normalize_type(provider_type: str) -> ProviderType:
    if provider_type in {"openai", "anthropic", "any"}:
        return cast(ProviderType, provider_type)
    raise LLFactoryError(f"type 仅支持 openai/anthropic/any，不支持: {provider_type}")


def _provider_matches(expected: ProviderType, actual: str) -> bool:
    if expected == "any":
        return True
    return expected == actual


def _candidate_from_config(config: AgentNodeConfig, tier: AgentTier) -> LLMCandidate:
    return LLMCandidate(
        name=config.name,
        tier=tier,
        provider=cast(Literal["openai", "anthropic"], config.provider),
        model=config.model,
        timeout_seconds=config.timeout_seconds,
    )


def _sanitize_probe_failure(error: BaseException) -> str:
    match error:
        case object(status_code=int() as status_code):
            return f"{type(error).__name__}(status={status_code})"
    return type(error).__name__


_PROBE_FAILURES = (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ConnectionError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.NetworkError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    LLMRuntimeError,
    TimeoutError,
)


def _create_client_for_node(node: RuntimeNode) -> SyncLLMClient:
    if node.provider == "anthropic":
        return Anthropic(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=float(node.timeout_seconds),
            default_headers=node.extra_headers,
        )
    return OpenAI(
        base_url=node.base_url,
        api_key=node.api_key,
        timeout=float(node.timeout_seconds),
        default_headers=node.extra_headers,
    )


def _create_async_client_for_node(node: RuntimeNode) -> AsyncLLMClient:
    if node.provider == "anthropic":
        return AsyncAnthropic(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=float(node.timeout_seconds),
            default_headers=node.extra_headers,
        )
    return AsyncOpenAI(
        base_url=node.base_url,
        api_key=node.api_key,
        timeout=float(node.timeout_seconds),
        default_headers=node.extra_headers,
    )


def _close_sync_client(client: SyncLLMClient) -> None:
    if isinstance(client, _SyncCloseable):
        client.close()


async def _close_async_client(client: AsyncLLMClient) -> None:
    if isinstance(client, _AsyncCloseable):
        await client.close()


@dataclass
class LLFactory:
    """统一的 LLM candidate 列表与 SDK client 工厂。"""

    logger: _LoggerProtocol | None = None

    def list_candidates(self, *, type: ProviderType = "any", model_size: AgentTier) -> list[LLMCandidate]:
        """列出指定 tier/provider 下的所有配置候选，不执行探活。"""

        normalized_type = _normalize_type(type)
        return [
            _candidate_from_config(config_node, model_size)
            for config_node in self._configs_for_tier(model_size)
            if _provider_matches(normalized_type, config_node.provider)
        ]

    def create_client(
        self,
        *,
        name: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> SyncLLMClient:
        normalized_type = _normalize_type(type)
        configs = self._matching_configs(name=name, normalized_type=normalized_type, tier=model_size)
        self._raise_if_no_matching_config(configs, name=name, normalized_type=normalized_type, tier=model_size)

        failure_reasons: list[str] = []
        normalized_name = name.strip() if name is not None else ""
        for config_node in configs:
            node = RuntimeNode.from_config(config_node)
            client = _create_client_for_node(node)
            try:
                probe_runtime_node(client, node.model)
            except _PROBE_FAILURES as exc:
                _close_sync_client(client)
                if normalized_name:
                    raise
                failure_reasons.append(f"{node.name}({node.model}): {_sanitize_probe_failure(exc)}")
                continue
            self._log_selection(node.name, node.provider, model_size)
            return client

        raise self._all_probe_failed_error(normalized_type, model_size, failure_reasons)

    async def create_async_client(
        self,
        *,
        name: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> AsyncLLMClient:
        normalized_type = _normalize_type(type)
        configs = self._matching_configs(name=name, normalized_type=normalized_type, tier=model_size)
        self._raise_if_no_matching_config(configs, name=name, normalized_type=normalized_type, tier=model_size)

        failure_reasons: list[str] = []
        normalized_name = name.strip() if name is not None else ""
        for config_node in configs:
            node = RuntimeNode.from_config(config_node)
            client = _create_async_client_for_node(node)
            try:
                await probe_async_runtime_node(client, node.model)
            except _PROBE_FAILURES as exc:
                await _close_async_client(client)
                if normalized_name:
                    raise
                failure_reasons.append(f"{node.name}({node.model}): {_sanitize_probe_failure(exc)}")
                continue
            self._log_selection(node.name, node.provider, model_size)
            return client

        raise self._all_probe_failed_error(normalized_type, model_size, failure_reasons)

    def _raise_if_no_matching_config(
        self,
        configs: list[AgentNodeConfig],
        *,
        name: str | None,
        normalized_type: ProviderType,
        tier: AgentTier,
    ) -> None:
        if not configs:
            normalized_name = name.strip() if name is not None else ""
            if normalized_name:
                available = ", ".join(
                    config_node.name
                    for config_node in self._configs_for_tier(tier)
                    if _provider_matches(normalized_type, config_node.provider)
                )
                raise LLFactoryError(
                    f"未找到匹配的 LLM 节点: name={normalized_name}, type={normalized_type}, "
                    f"model_size={tier}；可用节点: {available}"
                )
            raise LLFactoryError(f"未找到匹配的 LLM 节点: type={normalized_type}, model_size={tier}")

    def _all_probe_failed_error(
        self, normalized_type: ProviderType, tier: AgentTier, failure_reasons: list[str]
    ) -> LLFactoryError:
        reason_text = "；".join(failure_reasons) if failure_reasons else "未知原因"
        return LLFactoryError(f"所有匹配的 LLM 节点探活失败: type={normalized_type}, model_size={tier}；{reason_text}")

    def _matching_configs(
        self,
        *,
        name: str | None,
        normalized_type: ProviderType,
        tier: AgentTier,
    ) -> list[AgentNodeConfig]:
        configs = [
            config_node
            for config_node in self._configs_for_tier(tier)
            if _provider_matches(normalized_type, config_node.provider)
        ]
        normalized_name = name.strip() if name is not None else ""
        if not normalized_name:
            return configs
        return [config_node for config_node in configs if config_node.name == normalized_name]

    def _configs_for_tier(self, tier: AgentTier) -> list[AgentNodeConfig]:
        agent_config = get_config().agent
        return agent_config.large if tier == "large" else agent_config.small

    def _log_selection(self, name: str, provider: str, tier: AgentTier) -> None:
        active_logger = self.logger or _get_logger()
        active_logger.info("LLM 选择节点: tier=%s name=%s provider=%s", tier, name, provider)


__all__ = [
    "AsyncLLMClient",
    "LLFactory",
    "LLFactoryError",
    "LLMCandidate",
    "ProviderType",
    "SyncLLMClient",
]
