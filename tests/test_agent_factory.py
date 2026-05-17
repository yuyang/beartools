from __future__ import annotations

from unittest.mock import patch

import pytest

from beartools.llm import factory as factory_module
from beartools.llm.runtime import RuntimeNodeSummary


class FakeRuntime:
    def __init__(self, *, small_nodes: list[RuntimeNodeSummary], large_nodes: list[RuntimeNodeSummary]) -> None:
        self.small_nodes = small_nodes
        self.large_nodes = large_nodes
        self.created_sync: list[tuple[str, str]] = []
        self.created_async: list[tuple[str, str]] = []

    def list_models(self, provider: str, tier: str) -> list[RuntimeNodeSummary]:
        nodes = self.large_nodes if tier == "large" else self.small_nodes
        if provider == "any":
            return nodes
        return [node for node in nodes if node.provider == provider]

    def create_client(self, name: str, tier: str) -> str:
        self.created_sync.append((name, tier))
        return "openai-client"

    async def create_async_client(self, name: str, tier: str) -> str:
        self.created_async.append((name, tier))
        return "async-anthropic-client"


def create_summary(
    name: str, *, tier: str = "small", provider: str = "openai", model: str = "gpt-4o-mini"
) -> RuntimeNodeSummary:
    return RuntimeNodeSummary(
        name=name,
        tier=tier,
        provider=provider,
        _model=model,
        _base_url=f"https://{name}.example.com/v1",
        _timeout_seconds=30,
    )


class TestLLFactory:
    def test_create_client_returns_openai_client_for_first_matching_small_node(self) -> None:
        small_openai = create_summary("small-openai", provider="openai")
        runtime = FakeRuntime(small_nodes=[small_openai], large_nodes=[create_summary("large", tier="large")])

        with patch.object(factory_module, "get_llm_runtime", return_value=runtime):
            client = factory_module.LLFactory().create_client(type="openai", model_size="small")

        assert client == "openai-client"
        assert runtime.created_sync == [("small-openai", "small")]

    def test_create_client_with_model_is_limited_to_requested_model_size(self) -> None:
        small_node = create_summary("small-alias", model="same-model")
        large_node = create_summary("large-alias", tier="large", model="target-model")
        runtime = FakeRuntime(small_nodes=[small_node], large_nodes=[large_node])

        with patch.object(factory_module, "get_llm_runtime", return_value=runtime):
            with pytest.raises(factory_module.LLFactoryError, match="target-model"):
                factory_module.LLFactory().create_client(model="target-model", type="any", model_size="small")

    def test_create_client_matches_model_by_name_or_model_and_preserves_config_order(self) -> None:
        first = create_summary("first-alias", model="same-model")
        second = create_summary("second-alias", model="same-model")
        runtime = FakeRuntime(small_nodes=[first, second], large_nodes=[create_summary("large", tier="large")])

        with patch.object(factory_module, "get_llm_runtime", return_value=runtime):
            client = factory_module.LLFactory().create_client(model="same-model", type="any", model_size="small")

        assert client == "openai-client"
        assert runtime.created_sync == [("first-alias", "small")]

    def test_create_client_rejects_open_type(self) -> None:
        runtime = FakeRuntime(
            small_nodes=[create_summary("small")],
            large_nodes=[create_summary("large", tier="large")],
        )

        with patch.object(factory_module, "get_llm_runtime", return_value=runtime):
            with pytest.raises(factory_module.LLFactoryError, match="open"):
                factory_module.LLFactory().create_client(type="open")

    @pytest.mark.asyncio
    async def test_create_async_client_returns_anthropic_client(self) -> None:
        anthropic_node = create_summary("claude", tier="large", provider="anthropic", model="claude-sonnet")
        runtime = FakeRuntime(small_nodes=[create_summary("small")], large_nodes=[anthropic_node])

        with patch.object(factory_module, "get_llm_runtime", return_value=runtime):
            client = await factory_module.LLFactory().create_async_client(
                model="claude-sonnet",
                type="anthropic",
                model_size="large",
            )

        assert client == "async-anthropic-client"
        assert runtime.created_async == [("claude", "large")]

    def test_create_client_does_not_expose_legacy_pydantic_ai_methods(self) -> None:
        factory = factory_module.LLFactory()

        assert not hasattr(factory, "create")
        assert not hasattr(factory, "create_bundle")
        assert not hasattr(factory, "create_client_for_node")
        assert not hasattr(factory, "create_async_client_for_node")
