from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Protocol, cast
from unittest.mock import Mock, patch


class _RuntimeNodeProtocol(Protocol):
    name: str
    provider: str
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
        provider: str,
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
    def __call__(self, *, provider: str = ..., logger: object | None = ...) -> _LLFactoryProtocol: ...


class _FactoryModule(Protocol):
    importlib: object
    LLFactory: _LLFactoryClass

    def get_llm_runtime(self) -> object: ...

    def _supports_default_headers(self) -> bool: ...


def _load_module(module_name: str, relative_path: str) -> object:
    existing_module = sys.modules.get(module_name)
    if existing_module is not None:
        return existing_module

    module_path = Path(__file__).resolve().parents[1] / "src" / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


runtime_module = cast(
    _RuntimeModule, _load_module("beartools_llm_runtime_for_factory_tests", "beartools/llm/runtime.py")
)
factory_module = cast(_FactoryModule, _load_module("beartools_llm_factory_for_tests", "beartools/llm/factory.py"))


def create_runtime_node(name: str, *, extra_headers: dict[str, str] | None = None) -> _RuntimeNodeProtocol:
    return runtime_module.RuntimeNode(
        name=name,
        provider="openai",
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
        self.requested_tiers: list[str] = []

    def get_active_node(self, tier: str = "small") -> _RuntimeNodeProtocol:
        self.get_active_node_call_count += 1
        self.requested_tiers.append(tier)
        if self.get_active_node_call_count > 1:
            raise AssertionError("factory 不应二次触发活动节点选择")
        return self._node


def create_import_module_side_effect(
    *,
    async_openai: Mock,
    openai_chat_model: Mock,
    openai_provider: Mock,
) -> object:
    modules = {
        "openai": SimpleNamespace(AsyncOpenAI=async_openai),
        "pydantic_ai.models.openai": SimpleNamespace(OpenAIChatModel=openai_chat_model),
        "pydantic_ai.providers.openai": SimpleNamespace(OpenAIProvider=openai_provider),
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
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_chat_model=openai_chat_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            model = factory_module.LLFactory(logger=logger).create()

        assert model == "chat-model"
        assert runtime.get_active_node_call_count == 1
        assert runtime.requested_tiers == ["small"]
        async_openai.assert_not_called()
        openai_provider.assert_called_once_with(base_url=node.base_url, api_key=node.api_key)
        openai_chat_model.assert_called_once_with(
            model_name=node.model,
            provider="provider",
            settings={"timeout": 30.0},
        )

    def test_factory_logs_selected_runtime_node(self) -> None:
        node = create_runtime_node("logged")
        runtime = FakeRuntime(node)
        async_openai = Mock(name="AsyncOpenAI")
        openai_chat_model = Mock(name="OpenAIChatModel", return_value="chat-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "logger", logger, create=True),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_chat_model=openai_chat_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            factory_module.LLFactory(logger=logger).create()

        logger.info.assert_called_once_with(
            "LLM 选择节点: name=%s provider=%s base_url=%s model=%s",
            node.name,
            node.provider,
            node.base_url,
            node.model,
        )

    def test_factory_does_not_trigger_second_random_selection(self) -> None:
        node = create_runtime_node("sticky", extra_headers={"X-Env": "test"})
        runtime = FakeRuntime(node)
        async_openai = Mock(name="AsyncOpenAI", return_value="openai-client")
        openai_chat_model = Mock(name="OpenAIChatModel", return_value="chat-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "_supports_default_headers", return_value=True),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_chat_model=openai_chat_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            model = factory_module.LLFactory(logger=logger).create()

        assert model == "chat-model"
        assert runtime.get_active_node_call_count == 1
        assert runtime.requested_tiers == ["small"]
        async_openai.assert_called_once_with(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=30.0,
            default_headers=node.extra_headers,
        )
        openai_provider.assert_called_once_with(openai_client="openai-client")
        openai_chat_model.assert_called_once_with(
            model_name=node.model,
            provider="provider",
            settings={"timeout": 30.0},
        )

    def test_factory_defaults_to_small_tier(self) -> None:
        node = create_runtime_node("small-default")
        runtime = FakeRuntime(node)
        async_openai = Mock(name="AsyncOpenAI")
        openai_chat_model = Mock(name="OpenAIChatModel", return_value="chat-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_chat_model=openai_chat_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            factory_module.LLFactory(logger=logger).create()

        assert runtime.requested_tiers == ["small"]
