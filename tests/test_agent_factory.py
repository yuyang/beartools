from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from beartools.config import AgentConfig, AgentNodeConfig, Config
from beartools.llm import factory as factory_module


def create_agent_node_config(
    name: str,
    *,
    tier_model: str = "gpt-4o-mini",
    provider: str = "openai",
    base_url: str | None = None,
) -> AgentNodeConfig:
    return AgentNodeConfig(
        name=name,
        provider=provider,
        base_url=base_url or f"https://{name}.example.com/v1",
        model=tier_model,
        api_key=f"{name}-key",
        extra_headers={"X-Node": name},
        timeout_seconds=30,
    )


def create_config(*, large: list[AgentNodeConfig], small: list[AgentNodeConfig]) -> Config:
    return Config(agent=AgentConfig(large=large, small=small))


class TestLLFactory:
    def test_list_candidates_returns_configured_small_candidates_without_sensitive_fields(self) -> None:
        config = create_config(
            large=[create_agent_node_config("large-a", tier_model="gpt-5")],
            small=[
                create_agent_node_config("small-a", tier_model="gpt-4o-mini"),
                create_agent_node_config("small-b", tier_model="claude-haiku", provider="anthropic"),
            ],
        )

        with (
            patch.object(factory_module, "get_config", return_value=config),
            patch.object(factory_module, "probe_runtime_node", side_effect=AssertionError("不应探活")),
        ):
            candidates = factory_module.LLFactory().list_candidates(type="any", model_size="small")

        assert [(candidate.name, candidate.tier, candidate.provider, candidate.model) for candidate in candidates] == [
            ("small-a", "small", "openai", "gpt-4o-mini"),
            ("small-b", "small", "anthropic", "claude-haiku"),
        ]
        assert not hasattr(candidates[0], "base_url")
        assert not hasattr(candidates[0], "api_key")
        assert not hasattr(candidates[0], "extra_headers")

    def test_list_candidates_requires_model_size(self) -> None:
        with pytest.raises(TypeError):
            factory_module.LLFactory().list_candidates(type="any")

    def test_create_client_falls_back_to_next_probe_success_when_name_is_omitted(self) -> None:
        first = create_agent_node_config("first")
        second = create_agent_node_config("second")
        config = create_config(
            large=[create_agent_node_config("large-a", tier_model="gpt-5")],
            small=[first, second],
        )
        probed_names: list[str] = []

        def probe_client(client: object, model: str) -> None:
            assert model == "gpt-4o-mini"
            probed_names.append(client.name)
            if client.name == "first":
                raise TimeoutError("first unavailable")

        def create_client_for_node(node: object) -> object:
            return SimpleNamespace(name=node.name)

        with (
            patch.object(factory_module, "get_config", return_value=config),
            patch.object(factory_module, "probe_runtime_node", side_effect=probe_client),
            patch.object(factory_module, "_create_client_for_node", side_effect=create_client_for_node),
        ):
            client = factory_module.LLFactory().create_client(type="openai", model_size="small")

        assert client.name == "second"
        assert probed_names == ["first", "second"]

    def test_create_client_with_name_does_not_fallback_after_probe_failure(self) -> None:
        target = create_agent_node_config("target")
        backup = create_agent_node_config("backup")
        config = create_config(
            large=[create_agent_node_config("large-a", tier_model="gpt-5")],
            small=[target, backup],
        )
        probed_names: list[str] = []

        def probe_client(client: object, model: str) -> None:
            assert model == "gpt-4o-mini"
            probed_names.append(client.name)
            raise TimeoutError(f"{client.name} unavailable")

        def create_client_for_node(node: object) -> object:
            return SimpleNamespace(name=node.name)

        with (
            patch.object(factory_module, "get_config", return_value=config),
            patch.object(factory_module, "probe_runtime_node", side_effect=probe_client),
            patch.object(factory_module, "_create_client_for_node", side_effect=create_client_for_node),
        ):
            with pytest.raises(TimeoutError, match="target unavailable"):
                factory_module.LLFactory().create_client(name="target", type="openai", model_size="small")

        assert probed_names == ["target"]

    @pytest.mark.asyncio
    async def test_create_async_client_uses_first_probe_success(self) -> None:
        anthropic = create_agent_node_config("claude", provider="anthropic", tier_model="claude-haiku")
        openai = create_agent_node_config("openai")
        config = create_config(
            large=[create_agent_node_config("large-a", tier_model="gpt-5")],
            small=[openai, anthropic],
        )
        probed_names: list[str] = []

        async def probe_client(client: object, model: str) -> None:
            assert model == "claude-haiku"
            probed_names.append(client.name)

        def create_async_client_for_node(node: object) -> object:
            return SimpleNamespace(name=node.name)

        with (
            patch.object(factory_module, "get_config", return_value=config),
            patch.object(factory_module, "probe_async_runtime_node", side_effect=probe_client),
            patch.object(factory_module, "_create_async_client_for_node", side_effect=create_async_client_for_node),
        ):
            client = await factory_module.LLFactory().create_async_client(type="anthropic", model_size="small")

        assert client.name == "claude"
        assert probed_names == ["claude"]

    def test_create_client_rejects_open_type(self) -> None:
        config = create_config(
            large=[create_agent_node_config("large-a", tier_model="gpt-5")],
            small=[create_agent_node_config("small-a")],
        )

        with patch.object(factory_module, "get_config", return_value=config):
            with pytest.raises(factory_module.LLFactoryError, match="open"):
                factory_module.LLFactory().create_client(type="open")

    def test_create_client_no_longer_accepts_model_argument(self) -> None:
        assert "model" not in inspect.signature(factory_module.LLFactory.create_client).parameters
        assert "model" not in inspect.signature(factory_module.LLFactory.create_async_client).parameters

    def test_create_client_does_not_expose_legacy_pydantic_ai_methods(self) -> None:
        factory = factory_module.LLFactory()

        assert not hasattr(factory, "create")
        assert not hasattr(factory, "create_bundle")
        assert not hasattr(factory, "create_client_for_node")
        assert not hasattr(factory, "create_async_client_for_node")
