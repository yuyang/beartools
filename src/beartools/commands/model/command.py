"""模型工具命令。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
import typer

from beartools.model_check import (
    DEFAULT_MODEL_CHECK_OUTPUT_DIR,
    DEFAULT_MODEL_CHECK_QUESTIONS_PATH,
    DEFAULT_MODEL_CHECK_REPORT_STEM,
    ModelCheckAnswerEvent,
    ModelCheckProgressEvent,
    ModelCheckReport,
    render_model_check_markdown,
    run_model_check,
)

model_app = typer.Typer(help="模型工具", add_completion=False)
console = Console()


def _print_report(report: ModelCheckReport) -> None:
    """输出模型评测总览表。"""

    table = Table(title="Model Check")
    table.add_column("Tier")
    table.add_column("Name")
    table.add_column("Model")
    table.add_column("Correct", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Duration", justify="right")

    for result in report.results:
        table.add_row(
            result.tier,
            result.node.name,
            result.node._model,
            f"{result.correct_count}/{result.total_count}",
            f"{result.accuracy:.2%}",
            str(result.error_count),
            f"{result.duration_seconds:.2f}s",
        )

    console.print(table)


def _print_progress(event: ModelCheckProgressEvent) -> None:
    """输出当前评测进度。"""

    current_step = event.completed_steps + 1
    console.print(
        "[dim]"
        f"[{current_step}/{event.total_steps}] "
        f"模型 {event.node_index}/{event.total_nodes}: "
        f"tier={event.tier} name={event.node.name} provider={event.node.provider}，"
        f"题目 {event.question_index}/{event.total_questions}: {event.question.id}"
        "[/dim]"
    )


def _print_answer(event: ModelCheckAnswerEvent) -> None:
    """输出单题评测结果。"""

    answer = event.answer
    if answer.correct:
        console.print(f"[green]正确: {answer.question_id}[/green]")
        return

    predicted = answer.predicted_answer or answer.raw_output or "无"
    error_suffix = f" error={answer.error}" if answer.error is not None else ""
    console.print(
        f"[red]错误: {answer.question_id} 模型结果={predicted} 正确答案={answer.expected_answer}{error_suffix}[/red]"
    )


def resolve_default_report_path(now: datetime | None = None) -> Path:
    """生成默认报告路径。"""

    resolved_now = now or datetime.now()
    timestamp = resolved_now.strftime("%Y%m%d-%H%M%S")
    return DEFAULT_MODEL_CHECK_OUTPUT_DIR / f"{DEFAULT_MODEL_CHECK_REPORT_STEM}-{timestamp}.md"


def check(
    questions_path: Path = typer.Argument(  # noqa: B008
        DEFAULT_MODEL_CHECK_QUESTIONS_PATH,
        help="选择题题库 YAML/JSON 文件路径",
    ),
    question_id: str | None = typer.Option(None, "--id", help="只测试指定题目 ID"),
    model_name: str | None = typer.Option(None, "--model-name", "-m", help="只测试指定模型 name 或 model"),
    output_file: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Markdown 报告输出文件，默认使用 output/report-YYYYMMDD-HHMMSS.md",
    ),
) -> None:
    """对配置中的所有 LLM 模型执行选择题评测。"""

    try:
        report = run_model_check(
            questions_path,
            question_id=question_id,
            model_name=model_name,
            progress_callback=_print_progress,
            answer_callback=_print_answer,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    _print_report(report)
    resolved_output_file = output_file or resolve_default_report_path()
    resolved_output_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_file.write_text(render_model_check_markdown(report), encoding="utf-8")
    console.print(f"报告已写入: {resolved_output_file}", style="green")


model_app.command("check", help="对配置中的所有 LLM 模型执行选择题评测")(check)
