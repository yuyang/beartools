from __future__ import annotations

import asyncio
import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Protocol, cast
from unittest.mock import ANY, Mock, patch


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


class _LLModelBundleProtocol(Protocol):
    model: object

    def close(self) -> None: ...


class _LLFactoryProtocol(Protocol):
    def create(self, *, tier: str = ...) -> object: ...

    def create_bundle(self) -> _LLModelBundleProtocol: ...


class _LLFactoryClass(Protocol):
    def __call__(self, *, provider: str = ..., logger: object | None = ...) -> _LLFactoryProtocol: ...


class _FactoryModule(Protocol):
    importlib: object
    LLFactory: _LLFactoryClass

    def get_llm_runtime(self) -> object: ...

    def probe_runtime_node(self, node: _RuntimeNodeProtocol) -> None: ...

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
    def __init__(self, node: _RuntimeNodeProtocol, fallback_node: _RuntimeNodeProtocol | None = None) -> None:
        self._node = node
        self._fallback_node = fallback_node
        self.get_active_node_call_count = 0
        self.requested_tiers: list[str] = []
        self.failed_nodes: list[_RuntimeNodeProtocol] = []

    def get_active_node(self, tier: str = "small") -> _RuntimeNodeProtocol:
        self.get_active_node_call_count += 1
        self.requested_tiers.append(tier)
        if self.failed_nodes and self._fallback_node is not None:
            return self._fallback_node
        return self._node

    def mark_node_failed(
        self,
        node: _RuntimeNodeProtocol,
        error: BaseException | None = None,
        tier: str = "small",
    ) -> bool:
        del error
        self.requested_tiers.append(f"mark:{tier}")
        self.failed_nodes.append(node)
        return True


def create_import_module_side_effect(
    *,
    async_openai: Mock,
    openai_responses_model: Mock,
    openai_provider: Mock,
) -> object:
    modules = {
        "openai": SimpleNamespace(AsyncOpenAI=async_openai),
        "pydantic_ai.models.openai": SimpleNamespace(OpenAIResponsesModel=openai_responses_model),
        "pydantic_ai.providers.openai": SimpleNamespace(OpenAIProvider=openai_provider),
    }

    def import_module(name: str) -> object:
        return modules[name]

    return import_module


class TestLLFactory:
    def test_build_model_uses_runtime_active_node(self) -> None:
        node = create_runtime_node("primary")
        runtime = FakeRuntime(node)
        async_openai = Mock(
            name="AsyncOpenAI", return_value=SimpleNamespace(base_url=node.base_url, chat=SimpleNamespace())
        )
        openai_responses_model = Mock(name="OpenAIResponsesModel", return_value="responses-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_responses_model=openai_responses_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            model = factory_module.LLFactory(logger=logger).create()
        assert model == "responses-model"
        assert runtime.get_active_node_call_count == 1
        assert runtime.requested_tiers == ["small"]
        async_openai.assert_called_once_with(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=30.0,
            default_headers=node.extra_headers,
        )
        openai_provider.assert_called_once_with(openai_client=ANY)
        openai_responses_model.assert_called_once_with(
            model_name=node.model,
            provider="provider",
            settings={"timeout": 30.0},
        )

    def test_model_bundle_closes_openai_client(self) -> None:
        node = create_runtime_node("closable")
        runtime = FakeRuntime(node)
        close_calls: list[str] = []

        class FakeAsyncOpenAI:
            def __init__(
                self,
                *,
                base_url: str | None = None,
                api_key: str | None = None,
                timeout: float | None = None,
                default_headers: dict[str, str] | None = None,
            ) -> None:
                self.base_url = base_url
                self.api_key = api_key
                self.timeout = timeout
                self.default_headers = default_headers

            async def close(self) -> None:
                await asyncio.sleep(0)
                close_calls.append("closed")

        async_openai = Mock(name="AsyncOpenAI", side_effect=FakeAsyncOpenAI)
        openai_responses_model = Mock(name="OpenAIResponsesModel", return_value="responses-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_responses_model=openai_responses_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            bundle = factory_module.LLFactory(logger=logger).create_bundle()
            bundle.close()

        assert bundle.model == "responses-model"
        assert close_calls == ["closed"]

    def test_factory_logs_selected_runtime_node(self) -> None:
        node = create_runtime_node("logged")
        runtime = FakeRuntime(node)
        async_openai = Mock(
            name="AsyncOpenAI", return_value=SimpleNamespace(base_url=node.base_url, chat=SimpleNamespace())
        )
        openai_responses_model = Mock(name="OpenAIResponsesModel", return_value="responses-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(factory_module, "logger", logger, create=True),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_responses_model=openai_responses_model,
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
        async_openai = Mock(
            name="AsyncOpenAI", return_value=SimpleNamespace(base_url=node.base_url, chat=SimpleNamespace())
        )
        openai_responses_model = Mock(name="OpenAIResponsesModel", return_value="responses-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(factory_module, "_supports_default_headers", return_value=True),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_responses_model=openai_responses_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            model = factory_module.LLFactory(logger=logger).create()

        assert model == "responses-model"
        assert runtime.get_active_node_call_count == 1
        assert runtime.requested_tiers == ["small"]
        async_openai.assert_called_once_with(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=30.0,
            default_headers=node.extra_headers,
        )
        openai_provider.assert_called_once_with(openai_client=ANY)
        openai_responses_model.assert_called_once_with(
            model_name=node.model,
            provider="provider",
            settings={"timeout": 30.0},
        )

    def test_factory_defaults_to_small_tier(self) -> None:
        node = create_runtime_node("small-default")
        runtime = FakeRuntime(node)
        async_openai = Mock(
            name="AsyncOpenAI", return_value=SimpleNamespace(base_url=node.base_url, chat=SimpleNamespace())
        )
        openai_responses_model = Mock(name="OpenAIResponsesModel", return_value="responses-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_responses_model=openai_responses_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            factory_module.LLFactory(logger=logger).create()

        assert runtime.requested_tiers == ["small"]

    def test_factory_accepts_explicit_large_tier(self) -> None:
        node = create_runtime_node("large-default")
        runtime = FakeRuntime(node)
        async_openai = Mock(
            name="AsyncOpenAI", return_value=SimpleNamespace(base_url=node.base_url, chat=SimpleNamespace())
        )
        openai_responses_model = Mock(name="OpenAIResponsesModel", return_value="responses-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_responses_model=openai_responses_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            factory_module.LLFactory(logger=logger).create(tier="large")

        assert runtime.requested_tiers == ["large"]

    def test_factory_reprobes_active_node_and_falls_back_when_probe_fails(self) -> None:
        primary = create_runtime_node("primary")
        backup = create_runtime_node("backup")
        runtime = FakeRuntime(primary, fallback_node=backup)
        async_openai = Mock(
            name="AsyncOpenAI", return_value=SimpleNamespace(base_url=backup.base_url, chat=SimpleNamespace())
        )
        openai_responses_model = Mock(name="OpenAIResponsesModel", return_value="responses-model")
        openai_provider = Mock(name="OpenAIProvider", return_value="provider")
        logger = Mock(name="logger")

        probe_calls: list[str] = []

        def probe_node(node: _RuntimeNodeProtocol) -> None:
            probe_calls.append(node.name)
            if node.name == "primary":
                raise TimeoutError("probe timed out")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", side_effect=probe_node),
            patch.object(
                factory_module.importlib,
                "import_module",
                side_effect=create_import_module_side_effect(
                    async_openai=async_openai,
                    openai_responses_model=openai_responses_model,
                    openai_provider=openai_provider,
                ),
            ),
        ):
            model = factory_module.LLFactory(logger=logger).create()

        assert model == "responses-model"
        assert probe_calls == ["primary", "backup"]
        assert runtime.failed_nodes == [primary]
        openai_provider.assert_called_once_with(openai_client=ANY)
        openai_responses_model.assert_called_once_with(
            model_name=backup.model,
            provider="provider",
            settings={"timeout": 30.0},
        )
