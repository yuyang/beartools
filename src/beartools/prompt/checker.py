"""Prompt 可靠性静态检查。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from beartools.gmail import GmailMessageSummaryInput, _build_summary_prompt
from beartools.model_check import ModelCheckQuestion, format_question_prompt
from beartools.prompt import PromptManager, PromptTemplate

IssueLevel = Literal["error", "warning"]
PromptAssetKind = Literal["template", "dynamic"]
PromptCheckStatus = Literal["pass", "warning", "error"]


@dataclass(frozen=True, slots=True)
class PromptAsset:
    """待检查的 Prompt 资产。"""

    name: str
    source: str
    path: Path | None
    kind: PromptAssetKind


@dataclass(frozen=True, slots=True)
class PromptCheckIssue:
    """单条 Prompt 检查问题。"""

    level: IssueLevel
    rule: str
    message: str


@dataclass(frozen=True, slots=True)
class PromptCheckResult:
    """单个 Prompt 的检查结果。"""

    asset: PromptAsset
    issues: list[PromptCheckIssue]

    @property
    def status(self) -> PromptCheckStatus:
        """根据 issue 级别汇总状态。"""

        if any(issue.level == "error" for issue in self.issues):
            return "error"
        if self.issues:
            return "warning"
        return "pass"


def _collect_template_assets(manager: PromptManager) -> list[PromptAsset]:
    assets: list[PromptAsset] = []
    for template_name in sorted(manager.list_templates()):
        template = manager.load(template_name)
        assets.append(
            PromptAsset(
                name=template.name,
                source=template.source,
                path=manager.prompt_dir / f"{template_name}.md",
                kind="template",
            )
        )
    return assets


def _collect_dynamic_assets() -> list[PromptAsset]:
    question_prompt = format_question_prompt(
        ModelCheckQuestion(
            id="sample",
            question="1+1 等于几？",
            options={"A": "1", "B": "2"},
            answer="B",
        )
    )
    gmail_prompt = _build_summary_prompt(
        [
            GmailMessageSummaryInput(
                message_id="sample",
                subject="示例主题",
                sender="sender@example.com",
                received_at="2026-05-13T10:00:00+08:00",
                body_text="示例正文",
            )
        ],
        fetched_days=1,
    )
    return [
        PromptAsset(name="model_check_question", source=question_prompt, path=None, kind="dynamic"),
        PromptAsset(name="gmail_summary", source=gmail_prompt, path=None, kind="dynamic"),
    ]


def collect_prompt_assets(manager: PromptManager | None = None) -> list[PromptAsset]:
    """收集项目中的 Prompt 模板和已知动态 Prompt。"""

    resolved_manager = manager or PromptManager()
    return [*_collect_template_assets(resolved_manager), *_collect_dynamic_assets()]


def _contains_any(source: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in source for keyword in keywords)


def _check_template_render(asset: PromptAsset) -> PromptCheckIssue | None:
    try:
        PromptTemplate(name=asset.name, source=asset.source).extract_variables()
    except ValueError as exc:
        return PromptCheckIssue(
            level="error",
            rule="template_parse",
            message=f"模板变量解析失败: {exc}",
        )
    return None


def _looks_like_json_prompt(source: str) -> bool:
    return _contains_any(source, ("JSON", "json", "字段名", "schema", "输出结构", "最终格式"))


def _check_json_contract(source: str) -> list[PromptCheckIssue]:
    if not _looks_like_json_prompt(source):
        return []

    issues: list[PromptCheckIssue] = []
    if not _contains_any(source, ("只返回 JSON", "严格输出 JSON", "只输出 JSON")):
        issues.append(
            PromptCheckIssue(
                level="error",
                rule="json_pure_output",
                message="JSON 类 prompt 必须明确要求只输出 JSON。",
            )
        )
    if not _contains_any(source, ("不要解释", "不要输出任何额外说明", "不要返回 Markdown", "不要 markdown")):
        issues.append(
            PromptCheckIssue(
                level="warning",
                rule="json_no_extra_text",
                message="建议明确禁止解释、Markdown 或额外说明。",
            )
        )
    return issues


def _check_novel_scene_contract(asset: PromptAsset) -> list[PromptCheckIssue]:
    if asset.name != "codex_novel_scene_select":
        return []

    required_keywords = (
        "{{ n }}",
        "JSON 数组",
        "pic_prompt",
        "全局角色锚点",
        "全局视觉风格锚点",
        "性别",
        "年龄段",
        "身材体型",
        "面容特点",
    )
    missing_keywords = [keyword for keyword in required_keywords if keyword not in asset.source]
    if not missing_keywords:
        return []
    return [
        PromptCheckIssue(
            level="error",
            rule="novel_scene_contract",
            message=f"小说分镜 prompt 缺少关键约束: {', '.join(missing_keywords)}",
        )
    ]


def _check_output_contract(source: str) -> list[PromptCheckIssue]:
    if _contains_any(source, ("只输出", "只返回", "输出要求", "最终格式", "必须输出")):
        return []
    return [
        PromptCheckIssue(
            level="warning",
            rule="output_contract",
            message="建议补充明确的输出格式约束。",
        )
    ]


def check_prompt_asset(asset: PromptAsset) -> PromptCheckResult:
    """检查单个 Prompt 资产。"""

    issues: list[PromptCheckIssue] = []
    render_issue = _check_template_render(asset)
    if render_issue is not None:
        issues.append(render_issue)
    issues.extend(_check_output_contract(asset.source))
    issues.extend(_check_json_contract(asset.source))
    issues.extend(_check_novel_scene_contract(asset))
    return PromptCheckResult(asset=asset, issues=issues)


def check_all_prompts(name: str | None = None, manager: PromptManager | None = None) -> list[PromptCheckResult]:
    """检查全部 Prompt，支持按名称过滤。"""

    assets = collect_prompt_assets(manager=manager)
    if name is not None:
        assets = [asset for asset in assets if asset.name == name]
        if not assets:
            raise ValueError(f"未找到 prompt: {name}")
    return [check_prompt_asset(asset) for asset in assets]
