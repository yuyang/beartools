"""调用方侧 PydanticAI OpenAI 封装工具。"""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings


def create_openai_responses_model(
    client: AsyncOpenAI,
    *,
    model_name: str,
    timeout_seconds: float,
) -> OpenAIResponsesModel:
    """用调用方持有的 OpenAI 兼容 client 构建 PydanticAI Responses model。"""

    provider = OpenAIProvider(openai_client=client)
    settings: ModelSettings = {"timeout": timeout_seconds}
    return OpenAIResponsesModel(
        model_name=model_name,
        provider=provider,
        settings=settings,
    )
