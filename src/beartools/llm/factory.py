"""LLM 模型工厂。

根据运行时当前活动节点构造 PydanticAI 的 OpenAIResponsesModel。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import importlib
import inspect
from typing import Protocol, cast

from pydantic_ai.models import Model

from beartools.llm.runtime import AgentTier, LLRuntime, RuntimeNode, get_llm_runtime, probe_runtime_node
from beartools.logger import get_logger


class _AsyncOpenAIFactory(Protocol):
    def __call__(
        self,
        *,
        base_url: str | None = ...,
        api_key: str | None = ...,
        timeout: float | None = ...,
        default_headers: Mapping[str, str] | None = ...,
    ) -> object: ...


class _OpenAIModule(Protocol):
    AsyncOpenAI: _AsyncOpenAIFactory


class _OpenAIProviderFactory(Protocol):
    def __call__(
        self,
        *,
        base_url: str | None = ...,
        api_key: str | None = ...,
        openai_client: object | None = ...,
    ) -> object: ...


class _OpenAIResponsesModelFactory(Protocol):
    def __call__(self, *, model_name: str, provider: object, settings: dict[str, float]) -> Model[object]: ...


class _PydanticAIModelsOpenAIModule(Protocol):
    OpenAIResponsesModel: _OpenAIResponsesModelFactory


class _PydanticAIProvidersOpenAIModule(Protocol):
    OpenAIProvider: _OpenAIProviderFactory


class _LoggerProtocol(Protocol):
    def info(self, msg: str, *args: object) -> None: ...


class LLFactoryError(RuntimeError):
    """LLM 工厂配置错误。"""


def _get_logger() -> _LoggerProtocol:
    """延迟获取日志器，避免模块导入阶段触发配置加载。"""

    return cast(_LoggerProtocol, get_logger(__name__))


def _supports_default_headers() -> bool:
    """判断当前底层客户端是否支持默认请求头。"""

    openai_module = cast(_OpenAIModule, importlib.import_module("openai"))
    async_openai = openai_module.AsyncOpenAI
    return "default_headers" in inspect.signature(async_openai).parameters


@dataclass
class LLFactory:
    """基于运行时活动节点构造模型实例的轻量工厂。"""

    provider: str = "openai"
    logger: _LoggerProtocol | None = None

    def create(self, node: RuntimeNode | None = None, tier: AgentTier = "small") -> Model[object]:
        """创建并返回当前活动节点对应的 PydanticAI 模型。"""

        runtime_node = node or self._select_valid_node(get_llm_runtime(), tier=tier)
        if node is not None:
            probe_runtime_node(node)
        active_logger = self.logger or _get_logger()
        active_logger.info(
            "LLM 选择节点: name=%s provider=%s base_url=%s model=%s",
            runtime_node.name,
            runtime_node.provider,
            runtime_node.base_url,
            runtime_node.model,
        )
        pydantic_ai_models_openai = cast(
            _PydanticAIModelsOpenAIModule,
            importlib.import_module("pydantic_ai.models.openai"),
        )
        pydantic_ai_providers_openai = cast(
            _PydanticAIProvidersOpenAIModule,
            importlib.import_module("pydantic_ai.providers.openai"),
        )
        openai_module = cast(_OpenAIModule, importlib.import_module("openai"))

        async_openai = openai_module.AsyncOpenAI
        openai_responses_model = pydantic_ai_models_openai.OpenAIResponsesModel
        openai_provider = pydantic_ai_providers_openai.OpenAIProvider

        if runtime_node.extra_headers and not _supports_default_headers():
            raise LLFactoryError("当前环境的 OpenAI 客户端不支持 extra_headers，无法安全传递请求头")

        openai_client = async_openai(
            base_url=runtime_node.base_url,
            api_key=runtime_node.api_key,
            timeout=float(runtime_node.timeout_seconds),
            default_headers=runtime_node.extra_headers,
        )
        provider = openai_provider(openai_client=openai_client)

        return openai_responses_model(
            model_name=runtime_node.model,
            provider=provider,
            settings={"timeout": float(runtime_node.timeout_seconds)},
        )

    def _select_valid_node(self, runtime: LLRuntime, tier: AgentTier) -> RuntimeNode:
        """选择并探测当前可用节点，失败时切换到下一个节点。"""

        while True:
            runtime_node = runtime.get_active_node(tier)
            try:
                probe_runtime_node(runtime_node)
            except Exception as exc:
                changed = runtime.mark_node_failed(runtime_node, error=exc, tier=tier)
                if not changed:
                    raise
                continue
            return runtime_node
