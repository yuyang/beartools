from __future__ import annotations

from collections.abc import Callable
import importlib
from typing import Protocol, cast
from unittest.mock import patch

import httpx
from openai import APIConnectionError, APITimeoutError
from pydantic import BaseModel, ValidationError
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

pytest = importlib.import_module("pytest")


class _AgentNodeConfigProtocol(Protocol):
    name: str
    provider: str
    base_url: str
    model: str
    api_key: str
    extra_headers: dict[str, str]
    timeout_seconds: int


class _AgentConfigProtocol(Protocol):
    primary: _AgentNodeConfigProtocol
    candidates: list[_AgentNodeConfigProtocol]


class _ConfigProtocol(Protocol):
    agent: _AgentConfigProtocol


class _ConfigModule(Protocol):
    AgentConfig: object
    AgentNodeConfig: object
    Config: object


class _AgentNodeConfigClass(Protocol):
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
    ) -> _AgentNodeConfigProtocol: ...


class _AgentConfigClass(Protocol):
    def __call__(
        self,
        *,
        primary: _AgentNodeConfigProtocol,
        candidates: list[_AgentNodeConfigProtocol],
    ) -> _AgentConfigProtocol: ...


class _ConfigClass(Protocol):
    def __call__(self, *, agent: _AgentConfigProtocol) -> _ConfigProtocol: ...


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

    @classmethod
    def from_config(cls, config: _AgentNodeConfigProtocol) -> _RuntimeNodeProtocol: ...


class _LLRuntimeProtocol(Protocol):
    healthy_nodes: list[_RuntimeNodeProtocol]
    available_nodes: list[_RuntimeNodeProtocol]

    def get_active_node(self) -> _RuntimeNodeProtocol: ...

    def mark_node_failed(self, node: _RuntimeNodeProtocol, error: BaseException | None = None) -> bool: ...


class _LLRuntimeClass(Protocol):
    def __call__(self, *, healthy_nodes: list[_RuntimeNodeProtocol]) -> _LLRuntimeProtocol: ...


class _PytestRaisesContext(Protocol):
    value: BaseException


class _PytestRaisesManager(Protocol):
    def __enter__(self) -> _PytestRaisesContext: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None: ...


class _PytestMarkProtocol(Protocol):
    def parametrize(self, *args: object, **kwargs: object) -> Callable[[object], object]: ...


class _PytestModule(Protocol):
    mark: _PytestMarkProtocol

    def raises(
        self, expected_exception: type[BaseException], *args: object, **kwargs: object
    ) -> _PytestRaisesManager: ...


class _RuntimeModule(Protocol):
    RuntimeNode: _RuntimeNodeClass
    LLRuntime: _LLRuntimeClass
    LLMRuntimeNoHealthyNodeError: type[BaseException]

    def create_llm_runtime(self) -> _LLRuntimeProtocol: ...

    def should_invalidate_node(self, error: BaseException) -> bool: ...


_CONFIG_MODULE = cast(_ConfigModule, importlib.import_module("beartools.config"))
AgentConfig = cast(_AgentConfigClass, _CONFIG_MODULE.AgentConfig)
AgentNodeConfig = cast(_AgentNodeConfigClass, _CONFIG_MODULE.AgentNodeConfig)
Config = cast(_ConfigClass, _CONFIG_MODULE.Config)
runtime_module = cast(_RuntimeModule, importlib.import_module("beartools.llm.runtime"))
pytest = cast(_PytestModule, pytest)


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
) -> _AgentNodeConfigProtocol:
    return AgentNodeConfig(
        name=name,
        provider=provider,
        base_url=base_url or f"https://{name}.example.com/v1",
        model=model,
        api_key=api_key,
        extra_headers=extra_headers or {},
        timeout_seconds=timeout_seconds,
    )


def create_config(*nodes: _AgentNodeConfigProtocol) -> _ConfigProtocol:
    if not nodes:
        raise AssertionError("至少需要一个节点")
    return Config(agent=AgentConfig(primary=nodes[0], candidates=list(nodes[1:])))


def create_runtime_node(name: str, *, extra_headers: dict[str, str] | None = None) -> _RuntimeNodeProtocol:
    return runtime_module.RuntimeNode.from_config(create_agent_node_config(name, extra_headers=extra_headers))


class TestLLRuntime:
    def test_runtime_node_adapts_provider(self) -> None:
        config = create_agent_node_config("primary", provider="openrouter")

        runtime_node = runtime_module.RuntimeNode.from_config(config)

        assert runtime_node.provider == "openrouter"

    def test_sticky_selection_with_two_healthy_nodes(self) -> None:
        primary = create_agent_node_config("primary", provider="openai")
        candidate_a = create_agent_node_config("candidate-a", provider="openrouter")
        candidate_b = create_agent_node_config("candidate-b", provider="openai")
        config = create_config(primary, candidate_a, candidate_b)

        def probe_node(node: _RuntimeNodeProtocol) -> None:
            if node.name == "candidate-b":
                raise TimeoutError("probe timed out")

        chosen_node = runtime_module.RuntimeNode.from_config(candidate_a)
        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=probe_node),
            patch("beartools.llm.runtime.random.Random.choice", autospec=True, return_value=chosen_node) as mock_choice,
        ):
            runtime = runtime_module.create_llm_runtime()

        assert [node.name for node in runtime.healthy_nodes] == ["primary", "candidate-a"]
        assert runtime.get_active_node().name == "candidate-a"
        assert runtime.get_active_node().name == "candidate-a"
        assert [node.name for node in runtime.available_nodes] == ["primary", "candidate-a"]
        assert mock_choice.call_count == 1
        assert [
            node.name for node in runtime.healthy_nodes if node.fingerprint != runtime.get_active_node().fingerprint
        ] == ["primary"]

    def test_fail_current_call_then_reselect_future_node(self) -> None:
        primary = create_runtime_node("primary")
        candidate = create_runtime_node("candidate")

        with (
            patch(
                "beartools.llm.runtime.random.Random.choice",
                autospec=True,
                side_effect=lambda _self, seq: seq[0],
            ) as mock_choice,
        ):
            runtime = runtime_module.LLRuntime(healthy_nodes=[primary, candidate])
            current_call_node = runtime.get_active_node()
            changed = runtime.mark_node_failed(
                current_call_node,
                error=StatusCodeError(503, "503 service unavailable"),
            )

        assert changed is True
        assert current_call_node is primary
        assert runtime.get_active_node() is candidate
        assert [node.name for node in runtime.available_nodes] == ["candidate"]
        assert mock_choice.call_count == 2
        assert runtime.get_active_node().name == "candidate"

    def test_raise_when_all_nodes_unhealthy(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(primary, candidate)

        def probe_node(node: _RuntimeNodeProtocol) -> None:
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
        config = create_config(primary, candidate)

        def probe_node(node: _RuntimeNodeProtocol) -> None:
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
        config = create_config(primary, candidate)

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
        assert "service unavailable" not in str(exc_info.value)

    def test_probe_api_status_error_with_none_status_code_does_not_crash(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(primary, candidate)

        class FakeAPIStatusError(Exception):
            status_code = None

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "APIStatusError", FakeAPIStatusError),
            patch.object(runtime_module, "_probe_node", side_effect=FakeAPIStatusError("upstream error")),
        ):
            with pytest.raises(FakeAPIStatusError, match="upstream error"):
                runtime_module.create_llm_runtime()

    def test_probe_local_protocol_error_is_not_wrapped_as_no_healthy_node(self) -> None:
        primary = create_agent_node_config("primary")
        candidate = create_agent_node_config("candidate")
        config = create_config(primary, candidate)

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=httpx.LocalProtocolError("bad request framing")),
        ):
            with pytest.raises(httpx.LocalProtocolError, match="bad request framing"):
                runtime_module.create_llm_runtime()

    def test_probe_node_uses_openai_client_completion(self) -> None:
        node = create_runtime_node("primary")

        completion_calls: list[dict[str, object]] = []
        client_kwargs: list[dict[str, object]] = []

        class FakeChatCompletions:
            @staticmethod
            def create(**kwargs: object) -> object:
                completion_calls.append(kwargs)
                return object()

        class FakeChat:
            completions = FakeChatCompletions()

        class FakeOpenAIClient:
            chat = FakeChat()

        def fake_client_factory(**kwargs: object) -> FakeOpenAIClient:
            client_kwargs.append(kwargs)
            return FakeOpenAIClient()

        with patch.object(runtime_module, "_openai_client_factory", side_effect=fake_client_factory):
            runtime_module._probe_node(node)

        assert client_kwargs[0]["base_url"] == node.base_url
        assert client_kwargs[0]["api_key"] == node.api_key
        assert client_kwargs[0]["timeout"] == node.timeout_seconds
        assert client_kwargs[0]["default_headers"] == node.extra_headers
        assert completion_calls
        assert completion_calls[0]["model"] == node.model
        assert completion_calls[0]["messages"] == [{"role": "user", "content": "ping"}]
        assert completion_calls[0]["max_tokens"] == 1

    def test_validation_error_keeps_active_node(self) -> None:
        primary = create_runtime_node("primary")
        candidate = create_runtime_node("candidate")
        validation_error = build_validation_error()

        with patch(
            "beartools.llm.runtime.random.Random.choice",
            autospec=True,
            return_value=primary,
        ) as mock_choice:
            runtime = runtime_module.LLRuntime(healthy_nodes=[primary, candidate])
            current_node = runtime.get_active_node()
            changed = runtime.mark_node_failed(current_node, error=validation_error)

        assert runtime_module.should_invalidate_node(validation_error) is False
        assert changed is False
        assert runtime.get_active_node() is primary
        assert [node.name for node in runtime.available_nodes] == ["primary", "candidate"]
        mock_choice.assert_called_once()


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
