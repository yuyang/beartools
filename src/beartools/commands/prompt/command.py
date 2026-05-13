"""Prompt 工具命令。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.table import Table
import typer

from beartools.llm.runtime import AgentTier
from beartools.prompt.checker import PromptCheckResult, check_all_prompts
from beartools.prompt.evaluator import PromptEvalReport, load_prompt_eval_cases, run_prompt_eval

console = Console()


def _print_check_results(results: list[PromptCheckResult]) -> None:
    """输出 Prompt 静态检查结果。"""

    table = Table(title="Prompt Check")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Status")
    table.add_column("Issues", justify="right")

    for result in results:
        status_style = {"pass": "green", "warning": "yellow", "error": "red"}[result.status]
        table.add_row(
            result.asset.name,
            result.asset.kind,
            f"[{status_style}]{result.status}[/{status_style}]",
            str(len(result.issues)),
        )
        for issue in result.issues:
            console.print(f"[{issue.level}] {result.asset.name} {issue.rule}: {issue.message}")

    console.print(table)


def _has_check_failure(results: list[PromptCheckResult], strict: bool) -> bool:
    if any(result.status == "error" for result in results):
        return True
    return strict and any(result.status == "warning" for result in results)


def check(
    name: str | None = typer.Option(None, "--name", help="只检查指定 prompt 名称"),
    strict: bool = typer.Option(False, "--strict", help="将 warning 视为失败"),
) -> None:
    """静态检查 Prompt 资产。"""

    try:
        results = check_all_prompts(name=name)
    except ValueError as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    _print_check_results(results)
    console.print(f"prompt check: {len(results)} checked", style="green")
    if _has_check_failure(results, strict=strict):
        raise typer.Exit(1)


def _truncate_raw_output(raw_output: str, limit: int = 300) -> str:
    stripped_output = raw_output.replace("\n", "\\n")
    if len(stripped_output) <= limit:
        return stripped_output
    return f"{stripped_output[:limit]}..."


def _print_eval_report(report: PromptEvalReport) -> None:
    """输出 Prompt eval 结果。"""

    for result in report.results:
        if result.passed:
            console.print(f"PASS {result.case.id}", style="green")
            continue
        raw_suffix = f" raw={_truncate_raw_output(result.raw_output)}" if result.raw_output else ""
        console.print(f"FAIL {result.case.id}: {result.error}{raw_suffix}", style="red")

    console.print(f"prompt eval: {report.passed_count} passed, {report.failed_count} failed")


def eval_command(
    yaml_path: Annotated[Path, typer.Argument(help="Prompt eval YAML 文件路径")],
    tier: Annotated[AgentTier, typer.Option("--tier", help="必须指定 small 或 large")],
) -> None:
    """运行用户指定 YAML 中的 Prompt golden eval。"""

    try:
        cases = load_prompt_eval_cases(yaml_path)
        report = run_prompt_eval(cases, tier=tier)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    _print_eval_report(report)
    if report.failed_count:
        raise typer.Exit(1)
