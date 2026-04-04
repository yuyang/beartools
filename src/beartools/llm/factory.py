"""LLM 模型工厂。

根据运行时当前活动节点构造 PydanticAI 的 OpenAIChatModel，底层使用 LiteLLMProvider。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import importlib
import inspect
from typing import Protocol, cast

from pydantic_ai.models import Model

from beartools.llm.runtime import RuntimeNode, get_llm_runtime


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


class _LiteLLMProviderFactory(Protocol):
    def __call__(
        self,
        *,
        api_key: str | None = ...,
        api_base: str | None = ...,
        openai_client: object | None = ...,
        http_client: object | None = ...,
    ) -> object: ...


class _OpenAIChatModelFactory(Protocol):
    def __call__(self, *, model_name: str, provider: object, settings: dict[str, float]) -> Model: ...


class _PydanticAIModelsOpenAIModule(Protocol):
    OpenAIChatModel: _OpenAIChatModelFactory


class _PydanticAIProvidersLiteLLMModule(Protocol):
    LiteLLMProvider: _LiteLLMProviderFactory


class LLFactoryError(RuntimeError):
    """LLM 工厂配置错误。"""


def _supports_default_headers() -> bool:
    """判断当前底层客户端是否支持默认请求头。"""

    openai_module = cast(_OpenAIModule, importlib.import_module("openai"))
    async_openai = openai_module.AsyncOpenAI
    return "default_headers" in inspect.signature(async_openai).parameters


@dataclass
class LLFactory:
    """基于运行时活动节点构造模型实例的轻量工厂。"""

    provider: str = "litellm"

    def create(self, node: RuntimeNode | None = None) -> Model:
        """创建并返回当前活动节点对应的 PydanticAI 模型。"""

        runtime_node = node or get_llm_runtime().get_active_node()
        pydantic_ai_models_openai = cast(
            _PydanticAIModelsOpenAIModule,
            importlib.import_module("pydantic_ai.models.openai"),
        )
        pydantic_ai_providers_litellm = cast(
            _PydanticAIProvidersLiteLLMModule,
            importlib.import_module("pydantic_ai.providers.litellm"),
        )
        openai_module = cast(_OpenAIModule, importlib.import_module("openai"))

        async_openai = openai_module.AsyncOpenAI
        openai_chat_model = pydantic_ai_models_openai.OpenAIChatModel
        litellm_provider = pydantic_ai_providers_litellm.LiteLLMProvider

        if runtime_node.extra_headers:
            if not _supports_default_headers():
                raise LLFactoryError("当前环境的 OpenAI 客户端不支持 extra_headers，无法安全传递请求头")
            openai_client = async_openai(
                base_url=runtime_node.base_url,
                api_key=runtime_node.api_key,
                timeout=float(runtime_node.timeout_seconds),
                default_headers=runtime_node.extra_headers,
            )
            provider = litellm_provider(openai_client=openai_client)
        else:
            provider = litellm_provider(api_base=runtime_node.base_url, api_key=runtime_node.api_key)

        return openai_chat_model(
            model_name=runtime_node.model,
            provider=provider,
            settings={"timeout": float(runtime_node.timeout_seconds)},
        )
