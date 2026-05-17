from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from anthropic import Anthropic, AsyncAnthropic
from anthropic.types import Message
from openai import AsyncOpenAI, OpenAI
from openai.types.responses.response import Response

from beartools.config import AgentNodeConfig

AgentTier = Literal["large", "small"]
ProviderType = Literal["openai", "anthropic", "any"]
type SyncLLMClient = OpenAI | Anthropic
type AsyncLLMClient = AsyncOpenAI | AsyncAnthropic


class LLMRuntimeError(RuntimeError):
    pass


class LLMRuntimeInitializationError(LLMRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeNode:
    name: str
    provider: str
    base_url: str
    model: str
    api_key: str
    extra_headers: dict[str, str]
    timeout_seconds: int
    fingerprint: str

    @classmethod
    def from_config(cls, config: AgentNodeConfig) -> RuntimeNode:
        normalized_headers = dict(sorted(config.extra_headers.items()))
        fingerprint = _build_node_fingerprint(
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            extra_headers=normalized_headers,
        )
        return cls(
            name=config.name,
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            extra_headers=normalized_headers,
            timeout_seconds=config.timeout_seconds,
            fingerprint=fingerprint,
        )


def _build_node_fingerprint(base_url: str, model: str, api_key: str, extra_headers: dict[str, str]) -> str:
    header_part = "&".join(f"{key}={value}" for key, value in sorted(extra_headers.items()))
    return "|".join([base_url.strip(), model.strip(), api_key, header_part])


def _ensure_openai_response_has_text(response: Response) -> None:
    """确保 Responses API 探测响应至少包含一段可识别文本。"""

    if response.output_text.strip():
        return None

    for item in response.output:
        if item.type != "message":
            continue
        for part in item.content:
            if part.type == "output_text" and part.text.strip():
                return None

    raise LLMRuntimeInitializationError("LLM 节点探测失败：未返回可识别的最小生成结果")


def _ensure_anthropic_message_has_text(message: Message) -> None:
    for part in message.content:
        if part.type == "text" and part.text.strip():
            return None
    raise LLMRuntimeInitializationError("LLM 节点探测失败：未返回可识别的最小生成结果")


def _probe_openai_client(client: OpenAI, model: str) -> None:
    response = client.responses.create(
        model=model,
        input="ping",
    )
    _ensure_openai_response_has_text(response)


def _probe_anthropic_client(client: Anthropic, model: str) -> None:
    """使用 Anthropic Messages API 探测 Anthropic 节点。"""

    message = client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )
    _ensure_anthropic_message_has_text(message)


async def _probe_async_openai_client(client: AsyncOpenAI, model: str) -> None:
    response = await client.responses.create(
        model=model,
        input="ping",
    )
    _ensure_openai_response_has_text(response)


async def _probe_async_anthropic_client(client: AsyncAnthropic, model: str) -> None:
    message = await client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )
    _ensure_anthropic_message_has_text(message)


def probe_runtime_node(client: SyncLLMClient, model: str) -> None:
    """探测同步 SDK client 当前是否可用。"""

    if isinstance(client, Anthropic):
        _probe_anthropic_client(client, model)
        return None
    _probe_openai_client(client, model)


async def probe_async_runtime_node(client: AsyncLLMClient, model: str) -> None:
    """探测异步 SDK client 当前是否可用。"""

    if isinstance(client, AsyncAnthropic):
        await _probe_async_anthropic_client(client, model)
        return None
    await _probe_async_openai_client(client, model)


__all__ = [
    "LLMRuntimeError",
    "LLMRuntimeInitializationError",
    "RuntimeNode",
    "ProviderType",
    "SyncLLMClient",
    "AsyncLLMClient",
    "probe_async_runtime_node",
    "probe_runtime_node",
]
