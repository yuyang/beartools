"""Prompt golden eval 执行器。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from openai import AsyncOpenAI
from pydantic_ai import Agent
import yaml

from beartools.llm.factory import LLFactory
from beartools.llm.pydantic_openai import create_openai_responses_model
from beartools.llm.runtime import AgentTier, get_openai_compatible_node
from beartools.prompt import PromptManager, TemplateNotFoundError


class _YamlModule(Protocol):
    def safe_load(self, stream: str) -> object: ...


class PromptEvalRunner(Protocol):
    """Prompt eval 运行器协议。"""

    def run_sync(self, prompt: str) -> object: ...


@runtime_checkable
class _ClosableRunner(Protocol):
    def close(self) -> None:
        """关闭 runner 持有的资源。"""


class _PydanticPromptEvalRunner:
    """持有 PydanticAI Agent 和底层 OpenAI client 的真实 eval runner。"""

    def __init__(self, *, client: AsyncOpenAI, agent: PromptEvalRunner) -> None:
        self._client = client
        self._agent = agent

    def run_sync(self, prompt: str) -> object:
        """同步运行 eval prompt。"""

        return self._agent.run_sync(prompt)

    def close(self) -> None:
        """关闭底层 SDK client。"""

        asyncio.run(self._client.__aexit__(None, None, None))


class _RunResultWithOutput(Protocol):
    output: object


@dataclass(frozen=True, slots=True)
class PromptEvalExpectation:
    """Prompt eval 期望结果。"""

    json: dict[str, object]


@dataclass(frozen=True, slots=True)
class PromptEvalCase:
    """单个 Prompt eval 用例。"""

    id: str
    prompt: str
    params: dict[str, object]
    expect: PromptEvalExpectation


@dataclass(frozen=True, slots=True)
class PromptEvalCaseResult:
    """单个 eval 用例结果。"""

    case: PromptEvalCase
    passed: bool
    raw_output: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PromptEvalReport:
    """Prompt eval 汇总结果。"""

    results: list[PromptEvalCaseResult]

    @property
    def passed_count(self) -> int:
        """通过数量。"""

        return sum(1 for result in self.results if result.passed)

    @property
    def failed_count(self) -> int:
        """失败数量。"""

        return sum(1 for result in self.results if not result.passed)


def _ensure_mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} 必须是对象")
    return cast(dict[str, object], value)


def _ensure_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} 必须是非空字符串")
    return value.strip()


def _parse_case(raw_case: object, case_index: int, manager: PromptManager) -> PromptEvalCase:
    case_context = f"cases[{case_index}]"
    case_data = _ensure_mapping(raw_case, case_context)
    case_id = _ensure_string(case_data.get("id"), f"{case_context}.id")
    prompt_name = _ensure_string(case_data.get("prompt"), f"{case_id}.prompt")

    try:
        manager.load(prompt_name)
    except TemplateNotFoundError as exc:
        raise ValueError(f"{case_id}: prompt 不存在: {prompt_name}") from exc

    params_value = case_data.get("params", {})
    params = _ensure_mapping(params_value, f"{case_id}.params")
    expect_data = _ensure_mapping(case_data.get("expect"), f"{case_id}.expect")
    expected_json = _ensure_mapping(expect_data.get("json"), f"{case_id}.expect.json")
    return PromptEvalCase(
        id=case_id,
        prompt=prompt_name,
        params=params,
        expect=PromptEvalExpectation(json=expected_json),
    )


def load_prompt_eval_cases(yaml_path: Path, manager: PromptManager | None = None) -> list[PromptEvalCase]:
    """从用户指定 YAML 文件读取 Prompt eval 用例。"""

    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML 文件不存在: {yaml_path}")

    yaml_module = cast(_YamlModule, yaml)
    raw_data = yaml_module.safe_load(yaml_path.read_text(encoding="utf-8"))
    data = _ensure_mapping(raw_data, "YAML 根节点")
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("YAML 必须包含 cases 列表")
    case_items = cast(list[object], raw_cases)

    resolved_manager = manager or PromptManager()
    return [_parse_case(raw_case, index, resolved_manager) for index, raw_case in enumerate(case_items)]


def extract_pure_json_object(raw_output: str) -> dict[str, object]:
    """解析纯 JSON 对象输出，不自动剥离 Markdown 或解释文字。"""

    stripped_output = raw_output.strip()
    if not stripped_output.startswith("{") or not stripped_output.endswith("}"):
        raise ValueError("模型输出必须是纯 JSON 对象")
    try:
        parsed = cast(object, json.loads(stripped_output))
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    return cast(dict[str, object], parsed)


def _matches_expected_subset(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        actual_mapping = cast(dict[str, object], actual)
        expected_mapping = cast(dict[str, object], expected)
        for key, expected_value in expected_mapping.items():
            if key not in actual_mapping:
                return False
            if not _matches_expected_subset(actual_mapping[key], expected_value):
                return False
        return True
    return actual == expected


def create_eval_runner(tier: AgentTier) -> PromptEvalRunner:
    """创建真实 Prompt eval 运行器。"""

    node = get_openai_compatible_node(tier)
    client = asyncio.run(LLFactory().create_async_client_for_node(node))
    if not isinstance(client, AsyncOpenAI):
        raise RuntimeError("Prompt eval 当前只支持 OpenAI 兼容 client")
    asyncio.run(client.__aenter__())
    model = create_openai_responses_model(
        client,
        model_name=node.model,
        timeout_seconds=float(node.timeout_seconds),
    )
    agent: Agent[None, str] = Agent(model=model, output_type=str)
    return _PydanticPromptEvalRunner(client=client, agent=agent)


def _extract_result_output(result: object) -> str:
    if not hasattr(result, "output"):
        return str(result)
    output = cast(_RunResultWithOutput, result).output
    return str(output)


def run_prompt_eval(
    cases: list[PromptEvalCase],
    *,
    tier: AgentTier,
    manager: PromptManager | None = None,
    runner_factory: Callable[[AgentTier], PromptEvalRunner] | None = None,
) -> PromptEvalReport:
    """执行 Prompt eval，跑完所有 case 后统一汇总。"""

    resolved_manager = manager or PromptManager()
    resolved_runner_factory = runner_factory or create_eval_runner
    results: list[PromptEvalCaseResult] = []
    runner = resolved_runner_factory(tier)

    try:
        for case in cases:
            prompt = resolved_manager.render(case.prompt, case.params)
            raw_output = ""
            try:
                raw_output = _extract_result_output(runner.run_sync(prompt))
                parsed_output = extract_pure_json_object(raw_output)
                if not _matches_expected_subset(parsed_output, case.expect.json):
                    results.append(
                        PromptEvalCaseResult(
                            case=case,
                            passed=False,
                            raw_output=raw_output,
                            error=f"JSON 输出不匹配，期望子集: {case.expect.json}",
                        )
                    )
                    continue
                results.append(PromptEvalCaseResult(case=case, passed=True, raw_output=raw_output))
            except (ValueError, RuntimeError) as exc:
                results.append(PromptEvalCaseResult(case=case, passed=False, raw_output=raw_output, error=str(exc)))
    finally:
        if isinstance(runner, _ClosableRunner):
            runner.close()

    return PromptEvalReport(results=results)
