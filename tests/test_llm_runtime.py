from __future__ import annotations

from anthropic.types import Message, TextBlock
from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
import pytest

from beartools.config import AgentNodeConfig
from beartools.llm import runtime as runtime_module
from beartools.llm.runtime import ANTHROPIC_PROBE_MAX_TOKENS, RuntimeNode


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


def create_runtime_node(name: str, *, provider: str = "openai") -> RuntimeNode:
    return runtime_module.RuntimeNode.from_config(create_agent_node_config(name, provider=provider))


def create_openai_probe_response(text: str) -> Response:
    output_text = ResponseOutputText.model_construct(annotations=[], text=text, type="output_text")
    message = ResponseOutputMessage.model_construct(
        id="msg_1",
        content=[output_text],
        role="assistant",
        status="completed",
        type="message",
    )
    return Response.model_construct(id="resp_1", object="response", created_at=0, model="gpt-probe", output=[message])


def create_anthropic_probe_message(text: str) -> Message:
    text_block = TextBlock.model_construct(text=text, type="text")
    return Message.model_construct(
        id="msg_1",
        content=[text_block],
        model="claude-probe",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=None,
    )


def test_runtime_node_builds_stable_fingerprint_from_config() -> None:
    config = create_agent_node_config(
        "primary",
        extra_headers={"X-B": "2", "X-A": "1"},
    )

    node = runtime_module.RuntimeNode.from_config(config)

    assert node.name == "primary"
    assert node.provider == "openai"
    assert node.extra_headers == {"X-A": "1", "X-B": "2"}
    assert node.fingerprint == "https://primary.example.com/v1|gpt-4o-mini|test-key|X-A=1&X-B=2"


def test_probe_node_uses_minimal_openai_responses_request() -> None:
    node = create_runtime_node("primary")
    response_calls: list[dict[str, object]] = []

    class FakeResponses:
        @staticmethod
        def create(**kwargs: object) -> object:
            response_calls.append(kwargs)
            return create_openai_probe_response("pong")

    class FakeOpenAIClient:
        responses = FakeResponses()

    runtime_module.probe_runtime_node(FakeOpenAIClient(), node.model)

    assert response_calls[0]["model"] == node.model
    assert response_calls[0]["input"] == "ping"
    assert "max_output_tokens" not in response_calls[0]


def test_probe_node_accepts_response_with_text_content() -> None:
    node = create_runtime_node("primary")

    class FakeResponses:
        @staticmethod
        def create(**_: object) -> object:
            return create_openai_probe_response("pong")

    class FakeOpenAIClient:
        responses = FakeResponses()

    runtime_module.probe_runtime_node(FakeOpenAIClient(), node.model)


def test_probe_node_rejects_response_without_text_content() -> None:
    node = create_runtime_node("primary")

    class FakeResponses:
        @staticmethod
        def create(**_: object) -> object:
            return create_openai_probe_response("")

    class FakeOpenAIClient:
        responses = FakeResponses()

    with pytest.raises(runtime_module.LLMRuntimeInitializationError, match="未返回可识别的最小生成结果"):
        runtime_module.probe_runtime_node(FakeOpenAIClient(), node.model)


def test_probe_anthropic_node_uses_messages_api() -> None:
    node = create_runtime_node("claude", provider="anthropic")
    message_calls: list[dict[str, object]] = []

    class FakeMessages:
        @staticmethod
        def create(**kwargs: object) -> object:
            message_calls.append(kwargs)
            return create_anthropic_probe_message("pong")

    class FakeAnthropicClient:
        messages = FakeMessages()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(runtime_module, "Anthropic", FakeAnthropicClient)
        runtime_module.probe_runtime_node(FakeAnthropicClient(), node.model)

    assert message_calls[0]["model"] == node.model
    assert message_calls[0]["max_tokens"] == ANTHROPIC_PROBE_MAX_TOKENS
    assert message_calls[0]["messages"] == [{"role": "user", "content": "只输出 pong"}]


def test_probe_anthropic_node_rejects_response_without_text_content() -> None:
    node = create_runtime_node("claude", provider="anthropic")

    class FakeMessages:
        @staticmethod
        def create(**_: object) -> object:
            return create_anthropic_probe_message("")

    class FakeAnthropicClient:
        messages = FakeMessages()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(runtime_module, "Anthropic", FakeAnthropicClient)
        with pytest.raises(runtime_module.LLMRuntimeInitializationError, match="未返回可识别的最小生成结果"):
            runtime_module.probe_runtime_node(FakeAnthropicClient(), node.model)


@pytest.mark.asyncio
async def test_probe_async_openai_node_uses_async_responses_api() -> None:
    node = create_runtime_node("primary")
    response_calls: list[dict[str, object]] = []

    class FakeResponses:
        @staticmethod
        async def create(**kwargs: object) -> object:
            response_calls.append(kwargs)
            return create_openai_probe_response("pong")

    class FakeAsyncOpenAIClient:
        responses = FakeResponses()

    await runtime_module.probe_async_runtime_node(FakeAsyncOpenAIClient(), node.model)

    assert response_calls[0]["model"] == node.model
    assert response_calls[0]["input"] == "ping"


@pytest.mark.asyncio
async def test_probe_async_anthropic_node_uses_async_messages_api() -> None:
    node = create_runtime_node("claude", provider="anthropic")
    message_calls: list[dict[str, object]] = []

    class FakeMessages:
        @staticmethod
        async def create(**kwargs: object) -> object:
            message_calls.append(kwargs)
            return create_anthropic_probe_message("pong")

    class FakeAsyncAnthropicClient:
        messages = FakeMessages()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(runtime_module, "AsyncAnthropic", FakeAsyncAnthropicClient)
        await runtime_module.probe_async_runtime_node(FakeAsyncAnthropicClient(), node.model)

    assert message_calls[0]["model"] == node.model
    assert message_calls[0]["max_tokens"] == ANTHROPIC_PROBE_MAX_TOKENS
    assert message_calls[0]["messages"] == [{"role": "user", "content": "只输出 pong"}]
