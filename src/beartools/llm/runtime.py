from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import random
from threading import Lock
from typing import Final, Protocol, cast, runtime_checkable

from beartools.config import AgentNodeConfig, get_config

_PROBE_MESSAGES: Final[list[dict[str, str]]] = [{"role": "user", "content": "ping"}]
_PROBE_MAX_TOKENS: Final[int] = 16


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


@dataclass(slots=True)
class LLRuntime:
    """公开运行时类型，供工厂与后续测试共享状态。"""

    healthy_nodes: list[RuntimeNode]
    _random: random.Random = field(default_factory=random.Random, repr=False)
    _active_fingerprint: str | None = field(init=False, default=None, repr=False)
    _failed_fingerprints: set[str] = field(init=False, default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if not self.healthy_nodes:
            raise LLMRuntimeNoHealthyNodeError("LLM 运行时初始化失败：没有可用的健康节点")
        self._active_fingerprint = self._choose_active_fingerprint()

    @property
    def active_node(self) -> RuntimeNode:
        active_fingerprint = self._active_fingerprint
        if active_fingerprint is None:
            raise LLMRuntimeNoHealthyNodeError("LLM 运行时当前没有可用的活动节点")
        for node in self.healthy_nodes:
            if node.fingerprint == active_fingerprint:
                return node
        raise LLMRuntimeNoHealthyNodeError("LLM 运行时当前活动节点不存在于健康节点池中")

    @property
    def available_nodes(self) -> list[RuntimeNode]:
        return [node for node in self.healthy_nodes if node.fingerprint not in self._failed_fingerprints]

    def get_active_node(self) -> RuntimeNode:
        return self.active_node

    def mark_node_failed(self, node: RuntimeNode, error: BaseException | None = None) -> bool:
        """仅更新后续默认节点，不对当前失败请求做透明重放。"""
        if error is not None and not should_invalidate_node(error):
            return False

        if node.fingerprint in self._failed_fingerprints:
            return False

        self._failed_fingerprints.add(node.fingerprint)
        if self._active_fingerprint == node.fingerprint:
            self._active_fingerprint = self._choose_active_fingerprint(exclude_fingerprint=node.fingerprint)
        return True

    def start(self) -> None:
        return None

    def _choose_active_fingerprint(self, exclude_fingerprint: str | None = None) -> str | None:
        candidate_nodes = [
            node
            for node in self.healthy_nodes
            if node.fingerprint not in self._failed_fingerprints and node.fingerprint != exclude_fingerprint
        ]
        if not candidate_nodes:
            return None
        return self._random.choice(candidate_nodes).fingerprint


_runtime_instance: LLRuntime | None = None
_runtime_lock = Lock()


class _LiteLLMModule(Protocol):
    APIConnectionError: type[BaseException]
    InternalServerError: type[BaseException]
    BadGatewayError: type[BaseException]
    ServiceUnavailableError: type[BaseException]
    AuthenticationError: type[BaseException]
    PermissionDeniedError: type[BaseException]
    NotFoundError: type[BaseException]
    APITimeoutError: type[BaseException]

    def completion(self, **kwargs: object) -> object: ...


@runtime_checkable
class _StatusCodeError(Protocol):
    status_code: int | None


def _litellm_module() -> _LiteLLMModule:
    return cast(_LiteLLMModule, importlib.import_module("litellm"))


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


def _is_configured_node(config_node: AgentNodeConfig) -> bool:
    return bool(config_node.name.strip() and config_node.base_url.strip() and config_node.model.strip())


def _collect_configured_nodes() -> list[RuntimeNode]:
    agent_config = get_config().agent
    config_nodes = [
        config_node
        for config_node in [agent_config.primary, *agent_config.candidates]
        if _is_configured_node(config_node)
    ]
    return _deduplicate_nodes(config_nodes)


def _probe_node(node: RuntimeNode) -> None:
    litellm_module = _litellm_module()
    litellm_module.completion(
        model=node.model,
        messages=_PROBE_MESSAGES,
        max_tokens=_PROBE_MAX_TOKENS,
        timeout=float(node.timeout_seconds),
        base_url=node.base_url,
        api_key=node.api_key,
        extra_headers=node.extra_headers,
        custom_llm_provider=node.provider,
    )


def _sanitize_probe_failure_reason(error: BaseException) -> str:
    status_code = error.status_code if isinstance(error, _StatusCodeError) else None
    if isinstance(status_code, int):
        return f"{type(error).__name__}(status={status_code})"
    return type(error).__name__


def _build_healthy_node_pool() -> list[RuntimeNode]:
    configured_nodes = _collect_configured_nodes()
    if not configured_nodes:
        raise LLMRuntimeInitializationError("LLM 运行时初始化失败：未配置任何 agent 节点")

    healthy_nodes: list[RuntimeNode] = []
    failed_reasons: list[str] = []
    for node in configured_nodes:
        try:
            _probe_node(node)
        except Exception as exc:
            failed_reasons.append(f"{node.name}({node.base_url}, {node.model}): {_sanitize_probe_failure_reason(exc)}")
            continue
        healthy_nodes.append(node)

    if not healthy_nodes:
        reason_text = "；".join(failed_reasons) if failed_reasons else "未知原因"
        raise LLMRuntimeNoHealthyNodeError(f"LLM 运行时初始化失败：没有可用的健康节点，探测失败原因：{reason_text}")

    return healthy_nodes


def create_llm_runtime() -> LLRuntime:
    return LLRuntime(healthy_nodes=_build_healthy_node_pool())


def get_llm_runtime() -> LLRuntime:
    global _runtime_instance
    if _runtime_instance is not None:
        return _runtime_instance

    with _runtime_lock:
        if _runtime_instance is None:
            _runtime_instance = create_llm_runtime()
    return _runtime_instance


def get_active_llm_node() -> RuntimeNode:
    return get_llm_runtime().get_active_node()


def mark_active_llm_node_failed(error: BaseException | None = None) -> bool:
    runtime = get_llm_runtime()
    return runtime.mark_node_failed(runtime.get_active_node(), error=error)


def reset_llm_runtime() -> None:
    global _runtime_instance
    with _runtime_lock:
        _runtime_instance = None


def _failure_error_types() -> tuple[type[BaseException], ...]:
    litellm_module = _litellm_module()
    failure_types: list[type[BaseException]] = [
        TimeoutError,
        litellm_module.APIConnectionError,
        litellm_module.InternalServerError,
        litellm_module.BadGatewayError,
        litellm_module.ServiceUnavailableError,
        litellm_module.AuthenticationError,
        litellm_module.PermissionDeniedError,
        litellm_module.NotFoundError,
    ]
    try:
        timeout_error_type = litellm_module.APITimeoutError
    except AttributeError:
        timeout_error_type = None
    if timeout_error_type is not None:
        failure_types.append(timeout_error_type)
    return tuple(failure_types)


def should_invalidate_node(error: BaseException) -> bool:
    if isinstance(error, _failure_error_types()):
        return True

    status_code = error.status_code if isinstance(error, _StatusCodeError) else None
    if isinstance(status_code, int) and status_code >= 500:
        return True

    message = str(error).lower()
    failure_keywords = (
        "timeout",
        "timed out",
        "connection",
        "connect error",
        "connection error",
        "connection refused",
        "connection reset",
        "connection aborted",
        "temporary failure in name resolution",
        "name or service not known",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "500",
        "502",
        "503",
        "504",
    )
    return any(keyword in message for keyword in failure_keywords)


__all__ = [
    "LLMRuntimeError",
    "LLMRuntimeInitializationError",
    "LLMRuntimeNoHealthyNodeError",
    "RuntimeNode",
    "LLRuntime",
    "create_llm_runtime",
    "get_llm_runtime",
    "get_active_llm_node",
    "mark_active_llm_node_failed",
    "reset_llm_runtime",
    "should_invalidate_node",
]
