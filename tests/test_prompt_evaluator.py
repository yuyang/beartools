from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from beartools.llm.runtime import AgentTier
from beartools.prompt.evaluator import (
    PromptEvalCase,
    PromptEvalExpectation,
    extract_pure_json_object,
    load_prompt_eval_cases,
    run_prompt_eval,
)


class _FakeRunner:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def run_sync(self, prompt: str) -> object:
        self.calls.append({"prompt": prompt})
        return SimpleNamespace(output=self.outputs.pop(0))


class _FlakyRunner:
    def __init__(self) -> None:
        self.call_count = 0

    def run_sync(self, prompt: str) -> object:
        del prompt
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("model unavailable")
        return SimpleNamespace(output='{"purpose":"外出吃饭"}')


def test_load_prompt_eval_cases_rejects_missing_yaml(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="YAML 文件不存在"):
        load_prompt_eval_cases(tmp_path / "missing.yaml")


def test_load_prompt_eval_cases_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "cases.yaml"
    yaml_path.write_text(
        """
cases:
  - id: food
    prompt: bill_transaction_analysis
    params:
      counterparty: 喜茶
      remark: 多肉葡萄
      status: 交易成功
      amount: "19.00"
    expect:
      json:
        purpose: 外出吃饭
""",
        encoding="utf-8",
    )

    cases = load_prompt_eval_cases(yaml_path)

    assert cases == [
        PromptEvalCase(
            id="food",
            prompt="bill_transaction_analysis",
            params={
                "counterparty": "喜茶",
                "remark": "多肉葡萄",
                "status": "交易成功",
                "amount": "19.00",
            },
            expect=PromptEvalExpectation(json={"purpose": "外出吃饭"}),
        )
    ]


def test_load_prompt_eval_cases_rejects_unknown_prompt(tmp_path: Path) -> None:
    yaml_path = tmp_path / "cases.yaml"
    yaml_path.write_text(
        """
cases:
  - id: unknown
    prompt: missing_prompt
    params: {}
    expect:
      json:
        ok: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown"):
        load_prompt_eval_cases(yaml_path)


def test_extract_pure_json_object_rejects_markdown_wrapped_json() -> None:
    assert extract_pure_json_object('{"purpose":"食物"}') == {"purpose": "食物"}

    with pytest.raises(ValueError, match="纯 JSON"):
        extract_pure_json_object('```json\n{"purpose":"食物"}\n```')

    with pytest.raises(ValueError, match="纯 JSON"):
        extract_pure_json_object('结果是 {"purpose":"食物"}')


def test_run_prompt_eval_uses_tier_and_continues_after_failed_case() -> None:
    cases = [
        PromptEvalCase(
            id="pass",
            prompt="bill_transaction_analysis",
            params={"counterparty": "喜茶", "remark": "多肉葡萄", "status": "交易成功", "amount": "19.00"},
            expect=PromptEvalExpectation(json={"purpose": "外出吃饭"}),
        ),
        PromptEvalCase(
            id="fail",
            prompt="bill_transaction_analysis",
            params={"counterparty": "孩子王", "remark": "儿童内裤", "status": "交易成功", "amount": "59.90"},
            expect=PromptEvalExpectation(json={"owner": "团团"}),
        ),
    ]
    runner = _FakeRunner(['{"purpose":"外出吃饭","owner":"vv"}', '{"purpose":"衣服","owner":"all"}'])
    requested_tiers: list[AgentTier] = []

    def runner_factory(tier: AgentTier) -> _FakeRunner:
        requested_tiers.append(tier)
        return runner

    report = run_prompt_eval(cases, tier="large", runner_factory=runner_factory)

    assert requested_tiers == ["large"]
    assert [result.case.id for result in report.results] == ["pass", "fail"]
    assert report.passed_count == 1
    assert report.failed_count == 1
    assert runner.calls[0]["prompt"].startswith("你是家庭交易分类助手")


def test_run_prompt_eval_records_model_errors_and_continues() -> None:
    cases = [
        PromptEvalCase(
            id="model-error",
            prompt="bill_transaction_analysis",
            params={"counterparty": "喜茶", "remark": "多肉葡萄", "status": "交易成功", "amount": "19.00"},
            expect=PromptEvalExpectation(json={"purpose": "外出吃饭"}),
        ),
        PromptEvalCase(
            id="after-error",
            prompt="bill_transaction_analysis",
            params={"counterparty": "喜茶", "remark": "多肉葡萄", "status": "交易成功", "amount": "19.00"},
            expect=PromptEvalExpectation(json={"purpose": "外出吃饭"}),
        ),
    ]
    runner = _FlakyRunner()

    report = run_prompt_eval(cases, tier="small", runner_factory=lambda _tier: runner)

    assert [result.case.id for result in report.results] == ["model-error", "after-error"]
    assert report.failed_count == 1
    assert report.passed_count == 1
    assert report.results[0].error == "model unavailable"
