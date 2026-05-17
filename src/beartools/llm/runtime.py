from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, cast

from anthropic import Anthropic, AsyncAnthropic
import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior

from beartools.config import AgentNodeConfig, get_config

AgentTier = Literal["large", "small"]
ProviderType = Literal["openai", "anthropic", "any"]


class LLMRuntimeError(RuntimeError):
    pass


class LLMRuntimeInitializationError(LLMRuntimeError):
    pass


class LLMRuntimeNoHealthyNodeError(LLMRuntimeInitializationError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeNode:
    name: str
    provider: str
    base_url: str
    model: str
    api_key: str
    extra_headers: dict[str, str]
    timeout_seconds: int
    fingerprint: str

    @classmethod
    def from_config(cls, config: AgentNodeConfig) -> RuntimeNode:
        normalized_headers = dict(sorted(config.extra_headers.items()))
        fingerprint = _build_node_fingerprint(
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            extra_headers=normalized_headers,
        )
        return cls(
            name=config.name,
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            extra_headers=normalized_headers,
            timeout_seconds=config.timeout_seconds,
            fingerprint=fingerprint,
        )


@dataclass(frozen=True, slots=True)
class RuntimeNodeSummary:
    name: str
    tier: AgentTier
    provider: ProviderType
    _model: str = field(repr=False)
    _base_url: str = field(repr=False)
    _timeout_seconds: int = field(repr=False)


@dataclass(slots=True)
class LLRuntime:
    """公开运行时类型，供工厂与后续测试共享状态。"""

    large_nodes: list[RuntimeNode]
    small_nodes: list[RuntimeNode]
    _active_fingerprints: dict[AgentTier, str | None] = field(init=False, repr=False)
    _failed_fingerprints: dict[AgentTier, set[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.large_nodes:
            raise LLMRuntimeNoHealthyNodeError("LLM 运行时初始化失败：large 没有可用的健康节点")
        if not self.small_nodes:
            raise LLMRuntimeNoHealthyNodeError("LLM 运行时初始化失败：small 没有可用的健康节点")
        self._failed_fingerprints = {"large": set(), "small": set()}
        self._active_fingerprints = {
            "large": self._choose_active_fingerprint("large"),
            "small": self._choose_active_fingerprint("small"),
        }

    @property
    def available_nodes(self) -> list[RuntimeNode]:
        """兼容旧接口，默认返回 small 可用节点池。"""

        return self.available_nodes_for_tier("small")

    def get_active_node(self, tier: AgentTier = "small") -> RuntimeNode:
        active_fingerprint = self._active_fingerprints[tier]
        if active_fingerprint is None:
            raise LLMRuntimeNoHealthyNodeError(f"LLM 运行时当前 {tier} 没有可用的活动节点")
        for node in self._nodes_for_tier(tier):
            if node.fingerprint == active_fingerprint:
                return node
        raise LLMRuntimeNoHealthyNodeError(f"LLM 运行时当前 {tier} 活动节点不存在于健康节点池中")

    def available_nodes_for_tier(self, tier: AgentTier) -> list[RuntimeNode]:
        return [node for node in self._nodes_for_tier(tier) if node.fingerprint not in self._failed_fingerprints[tier]]

    def list_models(self, provider: ProviderType = "any", tier: AgentTier = "small") -> list[RuntimeNodeSummary]:
        """返回指定 tier/provider 的公开模型摘要。"""

        return [
            RuntimeNodeSummary(
                name=node.name,
                tier=tier,
                provider=cast(ProviderType, node.provider),
                _model=node.model,
                _base_url=node.base_url,
                _timeout_seconds=node.timeout_seconds,
            )
            for node in self.available_nodes_for_tier(tier)
            if _provider_matches(provider, node.provider)
        ]

    def create_client(self, name: str, tier: AgentTier = "small") -> OpenAI | Anthropic:
        """按名称和 tier 创建同步 client。"""

        node = self._get_node_by_name(name, tier)
        probe_runtime_node(node)
        return _create_client_for_node(node)

    async def create_async_client(self, name: str, tier: AgentTier = "small") -> AsyncOpenAI | AsyncAnthropic:
        """按名称和 tier 创建异步 client。"""

        node = self._get_node_by_name(name, tier)
        probe_runtime_node(node)
        return _create_async_client_for_node(node)

    def mark_node_failed(
        self, node: RuntimeNode, error: BaseException | None = None, tier: AgentTier = "small"
    ) -> bool:
        """仅更新后续默认节点，不对当前失败请求做透明重放。"""
        if error is not None and not should_invalidate_node(error):
            return False

        if node.fingerprint in self._failed_fingerprints[tier]:
            return False

        self._failed_fingerprints[tier].add(node.fingerprint)
        if self._active_fingerprints[tier] == node.fingerprint:
            self._active_fingerprints[tier] = self._choose_active_fingerprint(
                tier, exclude_fingerprint=node.fingerprint
            )
        return True

    def start(self) -> None:
        return None

    def _nodes_for_tier(self, tier: AgentTier) -> list[RuntimeNode]:
        return self.large_nodes if tier == "large" else self.small_nodes

    def _choose_active_fingerprint(self, tier: AgentTier, exclude_fingerprint: str | None = None) -> str | None:
        for node in self._nodes_for_tier(tier):
            if node.fingerprint in self._failed_fingerprints[tier]:
                continue
            if node.fingerprint == exclude_fingerprint:
                continue
            return node.fingerprint
        return None

    def _get_node_by_name(self, name: str, tier: AgentTier) -> RuntimeNode:
        for node in self.available_nodes_for_tier(tier):
            if node.name == name:
                return node
        available_names = ", ".join(node.name for node in self.available_nodes_for_tier(tier))
        raise LLMRuntimeNoHealthyNodeError(f"{tier} 未找到可用模型: {name}；可用模型: {available_names}")


_runtime_instance: LLRuntime | None = None
_runtime_lock = Lock()


def _openai_client_factory(
    *,
    base_url: str,
    api_key: str,
    timeout: float,
    default_headers: dict[str, str],
) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, default_headers=default_headers)


def _provider_matches(expected: ProviderType, actual: str) -> bool:
    if expected == "any":
        return True
    return expected == actual


def _create_client_for_node(node: RuntimeNode) -> OpenAI | Anthropic:
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


def _create_async_client_for_node(node: RuntimeNode) -> AsyncOpenAI | AsyncAnthropic:
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


def _build_node_fingerprint(base_url: str, model: str, api_key: str, extra_headers: dict[str, str]) -> str:
    header_part = "&".join(f"{key}={value}" for key, value in sorted(extra_headers.items()))
    return "|".join([base_url.strip(), model.strip(), api_key, header_part])


def _deduplicate_nodes(config_nodes: list[AgentNodeConfig]) -> list[RuntimeNode]:
    deduplicated: list[RuntimeNode] = []
    seen_fingerprints: set[str] = set()
    for config_node in config_nodes:
        runtime_node = RuntimeNode.from_config(config_node)
        if runtime_node.fingerprint in seen_fingerprints:
            continue
        deduplicated.append(runtime_node)
        seen_fingerprints.add(runtime_node.fingerprint)
    return deduplicated


def _collect_configured_nodes(tier: AgentTier) -> list[RuntimeNode]:
    agent_config = get_config().agent
    config_nodes = agent_config.large if tier == "large" else agent_config.small
    return _deduplicate_nodes(config_nodes)


def get_openai_compatible_node(tier: AgentTier) -> RuntimeNode:
    """从指定 tier 中选择第一个 OpenAI 兼容运行时节点。"""

    runtime = get_llm_runtime()
    for node in runtime.available_nodes_for_tier(tier):
        if node.provider == "openai":
            return node
    raise LLMRuntimeNoHealthyNodeError(f"{tier} 没有可用的 OpenAI 兼容 LLM 节点")


def _ensure_probe_response_has_text(response: object) -> None:
    """确保 Responses API 探测响应至少包含一段可识别文本。"""
    match response:
        case object(output_text=str() as output_text) if output_text.strip():
            return None
        case object(output=list() as output) if output:
            pass
        case _:
            raise LLMRuntimeInitializationError("LLM 节点探测失败：未返回可识别的最小生成结果")

    for item in output:
        match item:
            case object(content=str() as content):
                if _content_has_probe_text(content):
                    return None
            case object(content=list() as content):
                if _content_has_probe_text(content):
                    return None

    raise LLMRuntimeInitializationError("LLM 节点探测失败：未返回可识别的最小生成结果")


def _content_has_probe_text(content: object) -> bool:
    """判断 Responses output item 的 content 是否包含可识别文本。"""

    if isinstance(content, str) and content.strip():
        return True

    if not isinstance(content, list):
        return False

    for part in content:
        match part:
            case object(text=str() as text) if text.strip():
                return True
    return False


def _probe_node(node: RuntimeNode) -> None:
    if node.provider == "anthropic":
        _probe_anthropic_node(node)
        return None

    client = _openai_client_factory(
        base_url=node.base_url,
        api_key=node.api_key,
        timeout=float(node.timeout_seconds),
        default_headers=node.extra_headers,
    )
    with client:
        response = client.responses.create(
            model=node.model,
            input="ping",
        )
    _ensure_probe_response_has_text(response)


def _probe_anthropic_node(node: RuntimeNode) -> None:
    """使用 Anthropic Messages API 探测 Anthropic 节点。"""

    client = Anthropic(
        base_url=node.base_url,
        api_key=node.api_key,
        timeout=float(node.timeout_seconds),
        default_headers=node.extra_headers,
    )
    with client:
        client.messages.create(
            model=node.model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )


def probe_runtime_node(node: RuntimeNode) -> None:
    """探测运行时节点当前是否可用。"""

    _probe_node(node)


def _sanitize_probe_failure_reason(error: BaseException) -> str:
    match error:
        case object(status_code=int() as status_code):
            return f"{type(error).__name__}(status={status_code})"
    return type(error).__name__


def _build_healthy_node_pool(tier: AgentTier) -> list[RuntimeNode]:
    configured_nodes = _collect_configured_nodes(tier)
    if not configured_nodes:
        raise LLMRuntimeInitializationError(f"LLM 运行时初始化失败：{tier} 未配置任何 agent 节点")

    healthy_nodes: list[RuntimeNode] = []
    failed_reasons: list[str] = []
    for node in configured_nodes:
        try:
            _probe_node(node)
        except (APIConnectionError, APITimeoutError, TimeoutError) as exc:
            failed_reasons.append(f"{node.name}({node.base_url}, {node.model}): {_sanitize_probe_failure_reason(exc)}")
            continue
        except APIStatusError as exc:
            # 捕获所有API状态错误，包括4xx和5xx，只要有一个节点可用就行
            failed_reasons.append(
                f"{node.name}({node.base_url}, {node.model}): {_sanitize_probe_failure_reason(exc)}: {str(exc)}"
            )
            continue
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        ) as exc:
            failed_reasons.append(f"{node.name}({node.base_url}, {node.model}): {_sanitize_probe_failure_reason(exc)}")
            continue
        healthy_nodes.append(node)

    if not healthy_nodes:
        reason_text = "；".join(failed_reasons) if failed_reasons else "未知原因"
        raise LLMRuntimeNoHealthyNodeError(
            f"LLM 运行时初始化失败：{tier} 没有可用的健康节点，探测失败原因：{reason_text}"
        )

    return healthy_nodes


def create_llm_runtime() -> LLRuntime:
    return LLRuntime(large_nodes=_build_healthy_node_pool("large"), small_nodes=_build_healthy_node_pool("small"))


def get_llm_runtime() -> LLRuntime:
    global _runtime_instance
    if _runtime_instance is not None:
        return _runtime_instance

    with _runtime_lock:
        if _runtime_instance is None:
            _runtime_instance = create_llm_runtime()
    return _runtime_instance


def get_active_llm_node(tier: AgentTier = "small") -> RuntimeNode:
    return get_llm_runtime().get_active_node(tier)


def mark_active_llm_node_failed(error: BaseException | None = None, tier: AgentTier = "small") -> bool:
    runtime = get_llm_runtime()
    return runtime.mark_node_failed(runtime.get_active_node(tier), error=error, tier=tier)


def reset_llm_runtime() -> None:
    global _runtime_instance
    with _runtime_lock:
        _runtime_instance = None


def should_invalidate_node(error: BaseException) -> bool:
    return _should_invalidate_by_type(error)


def _should_invalidate_by_type(error: BaseException) -> bool:
    if isinstance(error, ModelHTTPError):
        return _should_invalidate_model_http_error(error)

    if isinstance(error, ModelAPIError):
        return _should_invalidate_model_api_error(error)

    if isinstance(error, UnexpectedModelBehavior):
        return True

    if isinstance(error, (APIConnectionError, APITimeoutError, TimeoutError)):
        return True

    if isinstance(error, APIStatusError):
        return isinstance(error.status_code, int) and error.status_code >= 500

    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500

    if isinstance(error, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError)):
        return True

    if isinstance(error, httpx.NetworkError):
        return True

    match error:
        case object(status_code=int() as status_code):
            return status_code >= 500
    return False


def _should_invalidate_known_network_error(error: BaseException) -> bool:
    return isinstance(
        error,
        (
            APIConnectionError,
            APITimeoutError,
            TimeoutError,
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.PoolTimeout,
            httpx.WriteTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        ),
    )


def _should_invalidate_model_http_error(error: ModelHTTPError) -> bool:
    return isinstance(error.status_code, int) and error.status_code >= 500


def _should_invalidate_model_api_error(error: ModelAPIError) -> bool:
    seen_errors: set[int] = set()
    current_error: BaseException | None = error
    for _ in range(3):
        if current_error is None:
            return False
        error_id = id(current_error)
        if error_id in seen_errors:
            return False
        seen_errors.add(error_id)
        if _should_invalidate_known_network_error(current_error):
            return True
        current_error = current_error.__cause__ or current_error.__context__
    return False


__all__ = [
    "LLMRuntimeError",
    "LLMRuntimeInitializationError",
    "LLMRuntimeNoHealthyNodeError",
    "RuntimeNode",
    "RuntimeNodeSummary",
    "LLRuntime",
    "ProviderType",
    "create_llm_runtime",
    "get_llm_runtime",
    "get_active_llm_node",
    "mark_active_llm_node_failed",
    "probe_runtime_node",
    "reset_llm_runtime",
    "should_invalidate_node",
]
