from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import APIConnectionError, APITimeoutError
from pydantic import BaseModel, ValidationError
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
import pytest

from beartools.config import AgentConfig, AgentNodeConfig, Config
from beartools.llm import runtime as runtime_module
from beartools.llm.runtime import RuntimeNode


class StatusCodeError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ValidationPayload(BaseModel):
    value: int


def build_validation_error() -> ValidationError:
    try:
        ValidationPayload.model_validate({"value": "not-an-int"})
    except ValidationError as exc:
        return exc
    raise AssertionError("预期生成 ValidationError")


def create_agent_node_config(
    name: str,
    *,
    base_url: str | None = None,
    model: str = "gpt-4o-mini",
    api_key: str = "test-key",
    extra_headers: dict[str, str] | None = None,
    timeout_seconds: int = 30,
    provider: str = "openai",
) -> AgentNodeConfig:
    return AgentNodeConfig(
        name=name,
        provider=provider,
        base_url=base_url or f"https://{name}.example.com/v1",
        model=model,
        api_key=api_key,
        extra_headers=extra_headers or {},
        timeout_seconds=timeout_seconds,
    )


def create_config(*, large: list[AgentNodeConfig], small: list[AgentNodeConfig]) -> Config:
    return Config(agent=AgentConfig(large=large, small=small))


def create_runtime_node(name: str, *, extra_headers: dict[str, str] | None = None) -> RuntimeNode:
    return runtime_module.RuntimeNode.from_config(create_agent_node_config(name, extra_headers=extra_headers))


class TestLLRuntime:
    def test_runtime_node_adapts_provider(self) -> None:
        config = create_agent_node_config("primary", provider="openai")

        runtime_node = runtime_module.RuntimeNode.from_config(config)

        assert runtime_node.provider == "openai"

    def test_runtime_prefers_primary_node_by_default(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(large_nodes=[primary], small_nodes=[candidate_a, candidate_b])

        assert runtime.get_active_node("large") is primary
        assert runtime.get_active_node() is candidate_a
        assert [node.name for node in runtime.available_nodes] == ["candidate-a", "candidate-b"]

    def test_runtime_falls_back_to_first_candidate_after_primary_failure(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(large_nodes=[primary], small_nodes=[candidate_a, candidate_b])
        changed = runtime.mark_node_failed(candidate_a, error=StatusCodeError(503, "candidate-a unavailable"))

        assert changed is True
        assert runtime.get_active_node() is candidate_b
        assert [node.name for node in runtime.available_nodes] == ["candidate-b"]

    def test_runtime_skips_failed_candidate_and_uses_next_candidate(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(large_nodes=[primary], small_nodes=[candidate_a, candidate_b])
        changed = runtime.mark_node_failed(candidate_a, error=StatusCodeError(503, "candidate-a unavailable"))

        assert changed is True
        assert runtime.get_active_node("large") is primary
        assert runtime.get_active_node() is candidate_b

    def test_runtime_keeps_active_node_when_non_active_candidate_fails(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(large_nodes=[primary], small_nodes=[candidate_a, candidate_b])
        changed = runtime.mark_node_failed(candidate_b, error=StatusCodeError(503, "candidate-b unavailable"))

        assert changed is True
        assert runtime.get_active_node("large") is primary
        assert [node.name for node in runtime.available_nodes] == ["candidate-a"]

    def test_runtime_uses_only_primary_when_primary_probe_succeeds(self) -> None:
        primary = create_agent_node_config("primary", provider="openai")
        candidate_a = create_agent_node_config("candidate-a", provider="openai")
        candidate_b = create_agent_node_config("candidate-b", provider="openai")
        config = create_config(large=[primary], small=[candidate_a, candidate_b])

        probed_names: list[str] = []

        def probe_node(node: RuntimeNode) -> None:
            probed_names.append(node.name)

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=probe_node),
        ):
            runtime = runtime_module.create_llm_runtime()

        assert probed_names == ["primary", "candidate-a", "candidate-b"]
        assert [node.name for node in runtime.large_nodes] == ["primary"]
        assert [node.name for node in runtime.small_nodes] == ["candidate-a", "candidate-b"]
        assert runtime.get_active_node("large").name == "primary"
        assert runtime.get_active_node().name == "candidate-a"

    def test_runtime_raises_when_large_pool_has_no_healthy_node(self) -> None:
        primary = create_agent_node_config("primary", provider="openai")
        candidate_a = create_agent_node_config("candidate-a", provider="openai")
        candidate_b = create_agent_node_config("candidate-b", provider="openai")
        config = create_config(large=[primary], small=[candidate_a, candidate_b])

        probed_names: list[str] = []

        def probe_node(node: RuntimeNode) -> None:
            probed_names.append(node.name)
            if node.name == "primary":
                raise TimeoutError("primary probe timed out")
            if node.name == "candidate-b":
                raise TimeoutError("candidate-b probe timed out")

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=probe_node),
        ):
            with pytest.raises(runtime_module.LLMRuntimeNoHealthyNodeError, match="large"):
                runtime_module.create_llm_runtime()

        assert probed_names == ["primary"]

    def test_fail_current_call_then_reselect_future_node(self) -> None:
        primary = create_runtime_node("primary")
        candidate = create_runtime_node("candidate")
        backup = create_runtime_node("backup")

        runtime = runtime_module.LLRuntime(large_nodes=[primary], small_nodes=[candidate, backup])
        current_call_node = runtime.get_active_node()
        changed = runtime.mark_node_failed(
            current_call_node,
            error=StatusCodeError(503, "503 service unavailable"),
        )

        assert changed is True
        assert current_call_node is candidate
        assert runtime.get_active_node() is backup
        assert [node.name for node in runtime.available_nodes] == ["backup"]
        assert runtime.get_active_node().name == "backup"

    def test_raise_when_all_nodes_unhealthy(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(large=[primary], small=[candidate])

        def probe_node(node: RuntimeNode) -> None:
            raise RuntimeError(f"secret-detail-for-{node.name}")

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=probe_node),
        ):
            with pytest.raises(RuntimeError, match="secret-detail-for-primary"):
                runtime_module.create_llm_runtime()

    def test_probe_failure_returns_sanitized_no_healthy_node_error(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(large=[primary], small=[candidate])

        def probe_node(node: RuntimeNode) -> None:
            raise TimeoutError(f"probe timed out for {node.name}")

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=probe_node),
        ):
            with pytest.raises(runtime_module.LLMRuntimeNoHealthyNodeError, match="没有可用的健康节点") as exc_info:
                runtime_module.create_llm_runtime()

        assert "secret-detail" not in str(exc_info.value)

    def test_probe_openai_sdk_failures_are_sanitized(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(large=[primary], small=[candidate])

        class FakeAPIStatusError(Exception):
            status_code = 502

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "APIStatusError", FakeAPIStatusError),
            patch.object(runtime_module, "_probe_node", side_effect=FakeAPIStatusError("service unavailable")),
        ):
            with pytest.raises(runtime_module.LLMRuntimeNoHealthyNodeError, match="没有可用的健康节点") as exc_info:
                runtime_module.create_llm_runtime()

        assert "FakeAPIStatusError" in str(exc_info.value)
        assert "service unavailable" in str(exc_info.value)

    def test_probe_api_status_error_with_none_status_code_does_not_crash(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(large=[primary], small=[candidate])

        class FakeAPIStatusError(Exception):
            status_code = None

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "APIStatusError", FakeAPIStatusError),
            patch.object(runtime_module, "_probe_node", side_effect=FakeAPIStatusError("upstream error")),
        ):
            with pytest.raises(runtime_module.LLMRuntimeNoHealthyNodeError, match="没有可用的健康节点") as exc_info:
                runtime_module.create_llm_runtime()

        assert "FakeAPIStatusError" in str(exc_info.value)
        assert "upstream error" in str(exc_info.value)

    def test_probe_local_protocol_error_is_not_wrapped_as_no_healthy_node(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(large=[primary], small=[candidate])

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=httpx.LocalProtocolError("bad request framing")),
        ):
            with pytest.raises(httpx.LocalProtocolError, match="bad request framing"):
                runtime_module.create_llm_runtime()

    def test_probe_node_uses_minimal_openai_responses_request(self) -> None:
        node = create_runtime_node("primary")

        response_calls: list[dict[str, object]] = []
        client_kwargs: list[dict[str, object]] = []

        class FakeResponses:
            @staticmethod
            def create(**kwargs: object) -> object:
                response_calls.append(kwargs)
                return SimpleNamespace(output_text="pong")

        class FakeOpenAIClient:
            responses = FakeResponses()

            def __enter__(self) -> FakeOpenAIClient:
                return self

            def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
                return None

        def fake_client_factory(**kwargs: object) -> FakeOpenAIClient:
            client_kwargs.append(kwargs)
            return FakeOpenAIClient()

        with patch.object(runtime_module, "_openai_client_factory", side_effect=fake_client_factory):
            runtime_module._probe_node(node)

        assert client_kwargs[0]["base_url"] == node.base_url
        assert client_kwargs[0]["api_key"] == node.api_key
        assert client_kwargs[0]["timeout"] == node.timeout_seconds
        assert client_kwargs[0]["default_headers"] == node.extra_headers
        assert response_calls
        assert response_calls[0]["model"] == node.model
        assert response_calls[0]["input"] == "ping"
        assert "max_output_tokens" not in response_calls[0]

    def test_probe_node_accepts_response_with_text_content(self) -> None:
        node = create_runtime_node("primary")

        class FakeResponses:
            @staticmethod
            def create(**_: object) -> object:
                return SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            content=[
                                SimpleNamespace(text="pong"),
                            ],
                        )
                    ],
                )

        class FakeOpenAIClient:
            responses = FakeResponses()

            def __enter__(self) -> FakeOpenAIClient:
                return self

            def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
                return None

        with patch.object(runtime_module, "_openai_client_factory", return_value=FakeOpenAIClient()):
            runtime_module._probe_node(node)

    def test_probe_node_accepts_response_with_output_text(self) -> None:
        node = create_runtime_node("primary")

        class FakeResponses:
            @staticmethod
            def create(**_: object) -> object:
                return SimpleNamespace(output_text="pong")

        class FakeOpenAIClient:
            responses = FakeResponses()

            def __enter__(self) -> FakeOpenAIClient:
                return self

            def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
                return None

        with patch.object(runtime_module, "_openai_client_factory", return_value=FakeOpenAIClient()):
            runtime_module._probe_node(node)

    def test_probe_node_rejects_response_without_text_content(self) -> None:
        node = create_runtime_node("primary")

        class FakeResponses:
            @staticmethod
            def create(**_: object) -> object:
                return SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            content=[
                                SimpleNamespace(text=""),
                            ],
                        )
                    ],
                )

        class FakeOpenAIClient:
            responses = FakeResponses()

            def __enter__(self) -> FakeOpenAIClient:
                return self

            def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
                return None

        with patch.object(runtime_module, "_openai_client_factory", return_value=FakeOpenAIClient()):
            with pytest.raises(
                runtime_module.LLMRuntimeInitializationError,
                match="未返回可识别的最小生成结果",
            ):
                runtime_module._probe_node(node)

    def test_validation_error_keeps_active_node(self) -> None:
        primary = create_runtime_node("primary")
        candidate = create_runtime_node("candidate")
        validation_error = build_validation_error()

        runtime = runtime_module.LLRuntime(large_nodes=[primary], small_nodes=[candidate])
        current_node = runtime.get_active_node()
        changed = runtime.mark_node_failed(current_node, error=validation_error)

        assert runtime_module.should_invalidate_node(validation_error) is False
        assert changed is False
        assert runtime.get_active_node() is candidate
        assert runtime.get_active_node("large") is primary
        assert [node.name for node in runtime.available_nodes] == ["candidate"]


class TestShouldInvalidateNode:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (TimeoutError("timed out"), True),
            (StatusCodeError(504, "gateway timeout"), True),
            (ConnectionError("connection refused"), False),
            (StatusCodeError(503, "upstream unavailable"), True),
            (Exception("connection refused by upstream"), False),
            (StatusCodeError(429, "rate limit exceeded"), False),
            (StatusCodeError(400, "bad request"), False),
            (Exception("api key is missing in business payload"), False),
            (UnexpectedModelBehavior("invalid chat completion response"), True),
            (Exception("domain validation failed with 401 code"), False),
            (Exception("404 record not found in local business table"), False),
        ],
    )
    def test_should_invalidate_node_classifications(self, error: Exception, expected: bool) -> None:
        assert runtime_module.should_invalidate_node(error) is expected

    @pytest.mark.parametrize(
        "error",
        [
            Exception("service unavailable"),
            RuntimeError("gateway timeout"),
            Exception("temporary failure in name resolution"),
            ConnectionError("connection refused"),
            OSError("bad gateway"),
        ],
    )
    def test_plain_exception_text_does_not_invalidate_node(self, error: Exception) -> None:
        assert runtime_module.should_invalidate_node(error) is False

    def test_model_http_error_invalidation_by_status_code(self) -> None:
        assert runtime_module.should_invalidate_node(ModelHTTPError(503, "service unavailable")) is True
        assert runtime_module.should_invalidate_node(ModelHTTPError(400, "bad request")) is False

    def test_model_api_error_invalidation_from_real_network_causes(self) -> None:
        request = httpx.Request("GET", "https://example.com")
        cases = [
            APIConnectionError(message="connect failed", request=request),
            APITimeoutError(request=request),
            httpx.PoolTimeout("pool timeout"),
            httpx.WriteTimeout("write timeout"),
            httpx.ConnectError("connect error"),
            httpx.ReadTimeout("read timeout"),
            httpx.ConnectTimeout("connect timeout"),
            httpx.RemoteProtocolError("remote protocol error"),
            httpx.NetworkError("network error"),
            TimeoutError("timeout"),
        ]

        for cause in cases:
            error = ModelAPIError("model", "model api error")
            error.__cause__ = cause
            assert runtime_module.should_invalidate_node(error) is True

    def test_model_api_error_without_network_cause_does_not_invalidate(self) -> None:
        error = ModelAPIError("model", "model api error")
        error.__cause__ = ValueError("validation failed")

        assert runtime_module.should_invalidate_node(error) is False

    def test_model_api_error_traverses_cause_chain(self) -> None:
        deepest = httpx.PoolTimeout("pool timeout")
        middle = RuntimeError("middle")
        middle.__cause__ = deepest
        error = ModelAPIError("model", "model api error")
        error.__cause__ = middle

        assert runtime_module.should_invalidate_node(error) is True

    def test_model_api_error_traverses_context_chain(self) -> None:
        deepest = httpx.WriteTimeout("write timeout")
        middle = RuntimeError("middle")
        middle.__context__ = deepest
        error = ModelAPIError("model", "model api error")
        error.__context__ = middle

        assert runtime_module.should_invalidate_node(error) is True

    def test_model_api_error_handles_cycle_in_exception_chain(self) -> None:
        error = ModelAPIError("model", "model api error")
        middle = RuntimeError("middle")
        deepest = RuntimeError("deepest")
        error.__cause__ = middle
        middle.__context__ = deepest
        deepest.__cause__ = error

        assert runtime_module.should_invalidate_node(error) is False
