from __future__ import annotations

from pathlib import Path

from beartools.prompt.checker import (
    PromptAsset,
    check_all_prompts,
    check_prompt_asset,
    collect_prompt_assets,
)


def test_collect_prompt_assets_includes_templates_and_dynamic_prompts() -> None:
    assets = collect_prompt_assets()
    names = {asset.name for asset in assets}

    assert "bill_transaction_analysis" in names
    assert "codex_novel_scene_select" in names
    assert "model_check_question" in names
    assert "gmail_summary" in names


def test_check_prompt_asset_reports_json_prompt_without_pure_json_contract() -> None:
    asset = PromptAsset(
        name="weak_json",
        source="请返回 JSON，字段为 purpose 和 owner。",
        path=None,
        kind="template",
    )

    result = check_prompt_asset(asset)

    assert result.status == "error"
    assert any(issue.rule == "json_pure_output" for issue in result.issues)


def test_check_project_json_prompt_contract_passes() -> None:
    asset = next(item for item in collect_prompt_assets() if item.name == "bill_transaction_analysis")

    result = check_prompt_asset(asset)

    assert result.status != "error"


def test_check_novel_scene_prompt_requires_consistency_anchors() -> None:
    asset = next(item for item in collect_prompt_assets() if item.name == "codex_novel_scene_select")

    result = check_prompt_asset(asset)

    assert result.status != "error"
    checked_rules = {issue.rule for issue in result.issues}
    assert "novel_scene_contract" not in checked_rules


def test_check_all_prompts_supports_name_filter() -> None:
    results = check_all_prompts(name="bill_transaction_analysis")

    assert [result.asset.name for result in results] == ["bill_transaction_analysis"]


def test_check_all_prompts_rejects_unknown_name() -> None:
    try:
        check_all_prompts(name="missing_prompt")
    except ValueError as exc:
        assert "missing_prompt" in str(exc)
    else:
        raise AssertionError("未知 prompt 名称应报错")


def test_sample_eval_yaml_exists() -> None:
    assert Path("check/prompts/bill-transaction-analysis-eval.yaml").exists()
