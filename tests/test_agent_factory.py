from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from beartools.llm import factory as factory_module
from beartools.llm import runtime as runtime_module
from beartools.llm.runtime import RuntimeNode


def create_runtime_node(
    name: str,
    *,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    extra_headers: dict[str, str] | None = None,
) -> RuntimeNode:
    return runtime_module.RuntimeNode(
        name=name,
        provider=provider,
        base_url=f"https://{name}.example.com/v1",
        model=model,
        api_key=f"{name}-key",
        extra_headers=extra_headers or {},
        timeout_seconds=30,
        fingerprint=f"fp-{name}",
    )


class FakeRuntime:
    def __init__(self, *, small_nodes: list[RuntimeNode], large_nodes: list[RuntimeNode]) -> None:
        self.small_nodes = small_nodes
        self.large_nodes = large_nodes
        self.requested_tiers: list[str] = []
        self.failed_nodes: list[RuntimeNode] = []

    def get_active_node(self, tier: str = "small") -> RuntimeNode:
        self.requested_tiers.append(tier)
        return self.available_nodes_for_tier(tier)[0]

    def available_nodes_for_tier(self, tier: str) -> list[RuntimeNode]:
        nodes = self.large_nodes if tier == "large" else self.small_nodes
        return [node for node in nodes if node not in self.failed_nodes]

    def mark_node_failed(
        self,
        node: RuntimeNode,
        error: BaseException | None = None,
        tier: str = "small",
    ) -> bool:
        del error
        self.requested_tiers.append(f"mark:{tier}")
        self.failed_nodes.append(node)
        return True


class TestLLFactory:
    def test_create_client_returns_openai_client_for_first_matching_small_node(self) -> None:
        small_openrouter = create_runtime_node("small-router", provider="openrouter")
        runtime = FakeRuntime(small_nodes=[small_openrouter], large_nodes=[create_runtime_node("large")])
        openai_client = Mock(name="OpenAI", return_value="openai-client")
        async_openai_client = Mock(name="AsyncOpenAI")
        anthropic_client = Mock(name="Anthropic")
        async_anthropic_client = Mock(name="AsyncAnthropic")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(factory_module, "_supports_default_headers", return_value=True),
            patch.object(factory_module, "OpenAI", openai_client),
            patch.object(factory_module, "AsyncOpenAI", async_openai_client),
            patch.object(factory_module, "Anthropic", anthropic_client),
            patch.object(factory_module, "AsyncAnthropic", async_anthropic_client),
        ):
            client = factory_module.LLFactory().create_client(type="openai", model_size="small")

        assert client == "openai-client"
        openai_client.assert_called_once_with(
            base_url=small_openrouter.base_url,
            api_key=small_openrouter.api_key,
            timeout=30.0,
            default_headers=small_openrouter.extra_headers,
        )
        anthropic_client.assert_not_called()

    def test_create_client_with_model_is_limited_to_requested_model_size(self) -> None:
        small_node = create_runtime_node("small-alias", model="same-model")
        large_node = create_runtime_node("large-alias", model="target-model")
        runtime = FakeRuntime(small_nodes=[small_node], large_nodes=[large_node])

        with patch.object(factory_module, "get_llm_runtime", return_value=runtime):
            with pytest.raises(factory_module.LLFactoryError, match="target-model"):
                factory_module.LLFactory().create_client(model="target-model", type="any", model_size="small")

    def test_create_client_matches_model_by_name_or_model_and_preserves_config_order(self) -> None:
        first = create_runtime_node("first-alias", model="same-model")
        second = create_runtime_node("second-alias", model="same-model")
        runtime = FakeRuntime(small_nodes=[first, second], large_nodes=[create_runtime_node("large")])
        openai_client = Mock(name="OpenAI", return_value="openai-client")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(factory_module, "_supports_default_headers", return_value=True),
            patch.object(factory_module, "OpenAI", openai_client),
        ):
            client = factory_module.LLFactory().create_client(model="same-model", type="any", model_size="small")

        assert client == "openai-client"
        openai_client.assert_called_once_with(
            base_url=first.base_url,
            api_key=first.api_key,
            timeout=30.0,
            default_headers=first.extra_headers,
        )

    def test_create_client_rejects_open_type(self) -> None:
        runtime = FakeRuntime(small_nodes=[create_runtime_node("small")], large_nodes=[create_runtime_node("large")])

        with patch.object(factory_module, "get_llm_runtime", return_value=runtime):
            with pytest.raises(factory_module.LLFactoryError, match="open"):
                factory_module.LLFactory().create_client(type="open")

    def test_create_client_for_node_probes_and_returns_client_for_exact_node(self) -> None:
        node = create_runtime_node("exact", provider="openrouter", model="same-model")
        openai_client = Mock(name="OpenAI", return_value="openai-client")
        probe = Mock(name="probe")

        with (
            patch.object(factory_module, "probe_runtime_node", probe),
            patch.object(factory_module, "_supports_default_headers", return_value=True),
            patch.object(factory_module, "OpenAI", openai_client),
        ):
            client = factory_module.LLFactory().create_client_for_node(node)

        assert client == "openai-client"
        probe.assert_called_once_with(node)
        openai_client.assert_called_once_with(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=30.0,
            default_headers=node.extra_headers,
        )

    @pytest.mark.asyncio
    async def test_create_async_client_returns_anthropic_client(self) -> None:
        anthropic_node = create_runtime_node("claude", provider="anthropic", model="claude-sonnet")
        runtime = FakeRuntime(small_nodes=[create_runtime_node("small")], large_nodes=[anthropic_node])
        async_anthropic_client = Mock(name="AsyncAnthropic", return_value="async-anthropic-client")

        with (
            patch.object(factory_module, "get_llm_runtime", return_value=runtime),
            patch.object(factory_module, "probe_runtime_node", return_value=None),
            patch.object(factory_module, "AsyncAnthropic", async_anthropic_client),
        ):
            client = await factory_module.LLFactory().create_async_client(
                model="claude-sonnet",
                type="anthropic",
                model_size="large",
            )

        assert client == "async-anthropic-client"
        async_anthropic_client.assert_called_once_with(
            base_url=anthropic_node.base_url,
            api_key=anthropic_node.api_key,
            timeout=30.0,
            default_headers=anthropic_node.extra_headers,
        )

    def test_create_client_does_not_expose_legacy_pydantic_ai_methods(self) -> None:
        factory = factory_module.LLFactory()

        assert not hasattr(factory, "create")
        assert not hasattr(factory, "create_bundle")
