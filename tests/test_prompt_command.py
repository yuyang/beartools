from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from beartools.cli import app

runner = CliRunner()


def test_check_command_group_registers_prompt_and_eval() -> None:
    result = runner.invoke(app, ["check", "--help"])

    assert result.exit_code == 0
    assert "prompt" in result.stdout
    assert "eval" in result.stdout


def test_check_prompt_command_filters_by_name() -> None:
    result = runner.invoke(app, ["check", "prompt", "--name", "bill_transaction_analysis"])

    assert result.exit_code == 0
    assert "bill_transaction_analysis" in result.stdout


def test_prompt_command_group_is_removed() -> None:
    result = runner.invoke(app, ["prompt", "--help"])

    assert result.exit_code != 0


def test_prompt_eval_requires_tier(tmp_path: Path) -> None:
    yaml_path = tmp_path / "cases.yaml"
    yaml_path.write_text("cases: []\n", encoding="utf-8")

    result = runner.invoke(app, ["check", "eval", str(yaml_path)])

    assert result.exit_code != 0
    assert "tier" in result.stdout.lower() or "tier" in result.stderr.lower()


def test_prompt_eval_missing_yaml_returns_error() -> None:
    result = runner.invoke(app, ["check", "eval", "/tmp/not-exists-prompt-eval.yaml", "--tier", "small"])

    assert result.exit_code == 1
    assert "YAML 文件不存在" in result.stdout


def test_prompt_eval_runs_existing_yaml_with_tier(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
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

    class FakeAgent:
        def run_sync(self, prompt: str) -> object:
            assert "喜茶" in prompt
            return SimpleNamespace(output='{"purpose":"外出吃饭","owner":"vv"}')

    def fake_create_eval_runner(tier: str) -> FakeAgent:
        assert tier == "small"
        return FakeAgent()

    monkeypatch.setattr("beartools.prompt.evaluator.create_eval_runner", fake_create_eval_runner)

    result = runner.invoke(app, ["check", "eval", str(yaml_path), "--tier", "small"])

    assert result.exit_code == 0
    assert "PASS food" in result.stdout
    assert "1 passed, 0 failed" in result.stdout
