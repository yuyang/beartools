from __future__ import annotations

from collections.abc import Callable
import importlib
from typing import Protocol, cast
from unittest.mock import patch

from pydantic import BaseModel, ValidationError

pytest = importlib.import_module("pytest")


class _AgentNodeConfigProtocol(Protocol):
    name: str
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


class FakeLiteLLMModule:
    class APIConnectionError(Exception):
        pass

    class InternalServerError(Exception):
        pass

    class BadGatewayError(Exception):
        pass

    class ServiceUnavailableError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class PermissionDeniedError(Exception):
        pass

    class NotFoundError(Exception):
        pass

    class APITimeoutError(Exception):
        pass


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
) -> _AgentNodeConfigProtocol:
    return AgentNodeConfig(
        name=name,
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
    def test_sticky_selection_with_two_healthy_nodes(self) -> None:
        primary = create_agent_node_config("primary")
        candidate_a = create_agent_node_config("candidate-a")
        candidate_b = create_agent_node_config("candidate-b")
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
        candidate_names = [node.name for node in mock_choice.call_args.args[1]]
        assert candidate_names == ["primary", "candidate-a"]

    def test_fail_current_call_then_reselect_future_node(self) -> None:
        primary = create_runtime_node("primary")
        candidate = create_runtime_node("candidate")

        with (
            patch(
                "beartools.llm.runtime.random.Random.choice",
                autospec=True,
                side_effect=[primary, candidate],
            ) as mock_choice,
            patch.object(runtime_module, "_litellm_module", return_value=FakeLiteLLMModule()),
        ):
            runtime = runtime_module.LLRuntime(healthy_nodes=[primary, candidate])
            current_call_node = runtime.get_active_node()
            changed = runtime.mark_node_failed(
                current_call_node,
                error=FakeLiteLLMModule.AuthenticationError("401 unauthorized"),
            )

        assert changed is True
        assert current_call_node is primary
        assert runtime.get_active_node() is candidate
        assert [node.name for node in runtime.available_nodes] == ["candidate"]
        assert mock_choice.call_count == 2
        reselected_names = [node.name for node in mock_choice.call_args_list[1].args[1]]
        assert reselected_names == ["candidate"]

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
            with pytest.raises(runtime_module.LLMRuntimeNoHealthyNodeError, match="没有可用的健康节点") as exc_info:
                runtime_module.create_llm_runtime()

        assert "primary(https://primary.example.com/v1, gpt-4o-mini)" in str(exc_info.value)
        assert "candidate(https://candidate.example.com/v1, gpt-4o-mini)" in str(exc_info.value)
        assert "RuntimeError" in str(exc_info.value)
        assert "secret-detail-for-primary" not in str(exc_info.value)
        assert "secret-detail-for-candidate" not in str(exc_info.value)

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
            (FakeLiteLLMModule.APITimeoutError("api timeout"), True),
            (FakeLiteLLMModule.APIConnectionError("connection refused"), True),
            (FakeLiteLLMModule.AuthenticationError("401 unauthorized"), True),
            (FakeLiteLLMModule.PermissionDeniedError("403 forbidden"), True),
            (StatusCodeError(503, "upstream unavailable"), True),
            (FakeLiteLLMModule.NotFoundError("model not found"), True),
            (Exception("connection refused by upstream"), True),
            (StatusCodeError(429, "rate limit exceeded"), False),
            (StatusCodeError(400, "bad request"), False),
            (Exception("api key is missing in business payload"), False),
            (Exception("domain validation failed with 401 code"), False),
            (Exception("404 record not found in local business table"), False),
        ],
    )
    def test_should_invalidate_node_classifications(self, error: Exception, expected: bool) -> None:
        with patch.object(runtime_module, "_litellm_module", return_value=FakeLiteLLMModule()):
            assert runtime_module.should_invalidate_node(error) is expected
