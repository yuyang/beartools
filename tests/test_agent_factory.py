from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Protocol, cast
from unittest.mock import Mock, patch


class _RuntimeNodeProtocol(Protocol):
    name: str
    base_url: str
    model: str
    api_key: str
    extra_headers: dict[str, str]
    timeout_seconds: int
    fingerprint: str


class _RuntimeNodeClass(Protocol):
    def __call__(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: str,
        extra_headers: dict[str, str],
        timeout_seconds: int,
        fingerprint: str,
    ) -> _RuntimeNodeProtocol: ...


class _RuntimeModule(Protocol):
    RuntimeNode: _RuntimeNodeClass


class _LLFactoryProtocol(Protocol):
    def create(self) -> object: ...


class _LLFactoryClass(Protocol):
    def __call__(self) -> _LLFactoryProtocol: ...


class _FactoryModule(Protocol):
    importlib: object
    LLFactory: _LLFactoryClass

    def get_llm_runtime(self) -> object: ...

    def _supports_default_headers(self) -> bool: ...


factory_module = cast(_FactoryModule, importlib.import_module("beartools.llm.factory"))
runtime_module = cast(_RuntimeModule, importlib.import_module("beartools.llm.runtime"))


def create_runtime_node(name: str, *, extra_headers: dict[str, str] | None = None) -> _RuntimeNodeProtocol:
    return runtime_module.RuntimeNode(
        name=name,
        base_url=f"https://{name}.example.com/v1",
        model="gpt-4o-mini",
        api_key=f"{name}-key",
        extra_headers=extra_headers or {},
        timeout_seconds=30,
        fingerprint=f"fp-{name}",
    )


class FakeRuntime:
    def __init__(self, node: _RuntimeNodeProtocol) -> None:
        self._node = node
        self.get_active_node_call_count = 0

    def get_active_node(self) -> _RuntimeNodeProtocol:
        self.get_active_node_call_count += 1
        if self.get_active_node_call_count > 1:
            raise AssertionError("factory 不应二次触发活动节点选择")
        return self._node


def create_import_module_side_effect(
    *,
    async_openai: Mock,
    openai_chat_model: Mock,
    litellm_provider: Mock,
) -> object:
    modules = {
        "openai": SimpleNamespace(AsyncOpenAI=async_openai),
        "pydantic_ai.models.openai": SimpleNamespace(OpenAIChatModel=openai_chat_model),
        "pydantic_ai.providers.litellm": SimpleNamespace(LiteLLMProvider=litellm_provider),
    }

    def import_module(name: str) -> object:
        return modules[name]

    return import_module


class TestLLFactory:
    def test_build_model_uses_runtime_active_node(self) -> None:
        node = create_runtime_node("primary")
        runtime = FakeRuntime(node)
        async_openai = Mock(name="AsyncOpenAI")
        openai_chat_model = Mock(name="OpenAIChatModel", return_value="chat-model")
        litellm_provider = Mock(name="LiteLLMProvider", return_value="provider")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_chat_model=openai_chat_model,
                    litellm_provider=litellm_provider,
                ),
            ),
        ):
            model = factory_module.LLFactory().create()

        assert model == "chat-model"
        assert runtime.get_active_node_call_count == 1
        async_openai.assert_not_called()
        litellm_provider.assert_called_once_with(api_base=node.base_url, api_key=node.api_key)
        openai_chat_model.assert_called_once_with(
            model_name=node.model,
            provider="provider",
            settings={"timeout": 30.0},
        )

    def test_factory_does_not_trigger_second_random_selection(self) -> None:
        node = create_runtime_node("sticky", extra_headers={"X-Env": "test"})
        runtime = FakeRuntime(node)
        async_openai = Mock(name="AsyncOpenAI", return_value="openai-client")
        openai_chat_model = Mock(name="OpenAIChatModel", return_value="chat-model")
        litellm_provider = Mock(name="LiteLLMProvider", return_value="provider")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "_supports_default_headers", return_value=True),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_chat_model=openai_chat_model,
                    litellm_provider=litellm_provider,
                ),
            ),
        ):
            model = factory_module.LLFactory().create()

        assert model == "chat-model"
        assert runtime.get_active_node_call_count == 1
        async_openai.assert_called_once_with(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=30.0,
            default_headers=node.extra_headers,
        )
        litellm_provider.assert_called_once_with(openai_client="openai-client")
        openai_chat_model.assert_called_once_with(
            model_name=node.model,
            provider="provider",
            settings={"timeout": 30.0},
        )
