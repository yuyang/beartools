from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from beartools.cli import app
from beartools.commands.model.command import _print_answer, _print_progress
from beartools.llm.runtime import RuntimeNode
from beartools.model_check import (
    ALLOWED_MODEL_CHECK_CHOICES,
    DEFAULT_MODEL_CHECK_OUTPUT_PATH,
    DEFAULT_MODEL_CHECK_QUESTIONS_PATH,
    ModelCheckProgressEvent,
    ModelCheckQuestion,
    format_question_prompt,
    load_model_check_questions,
    parse_model_choice,
    render_model_check_markdown,
    run_model_check_for_node,
)


class _FakeChatCompletions:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=output),
                )
            ]
        )


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.completions = _FakeChatCompletions(outputs)
        self.chat = SimpleNamespace(completions=self.completions)


def _node() -> RuntimeNode:
    return RuntimeNode(
        name="small-1",
        provider="openai",
        base_url="https://example.com/v1",
        model="gpt-test",
        api_key="key",
        extra_headers={},
        timeout_seconds=30,
        fingerprint="fp",
    )


def test_load_model_check_questions_from_yaml(tmp_path: Path) -> None:
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        """
questions:
  - id: math-1
    question: 1+1 等于几？
    options:
      A: "1"
      B: "2"
    answer: B
""",
        encoding="utf-8",
    )

    questions = load_model_check_questions(questions_path)

    assert questions == [
        ModelCheckQuestion(
            id="math-1",
            question="1+1 等于几？",
            options={"A": "1", "B": "2"},
            answer="B",
        )
    ]


def test_parse_model_choice_only_accepts_single_letter() -> None:
    assert parse_model_choice("B", {"A", "B", "C"}) == "B"
    assert parse_model_choice("Z", ALLOWED_MODEL_CHECK_CHOICES) == "Z"
    assert parse_model_choice("答案：B", {"A", "B", "C"}) is None
    assert parse_model_choice("B。", {"A", "B", "C"}) is None


def test_load_model_check_questions_rejects_choice_outside_a_to_z(tmp_path: Path) -> None:
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        """
questions:
  - id: bad-1
    question: 数字选项是否允许？
    options:
      A: "允许"
      "1": "不允许"
    answer: A
""",
        encoding="utf-8",
    )

    try:
        load_model_check_questions(questions_path)
    except ValueError as exc:
        assert "A-Z" in str(exc)
    else:
        raise AssertionError("题库不应接受 A-Z 之外的选项")


def test_format_question_prompt_requires_single_letter_output() -> None:
    question = ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B")

    prompt = format_question_prompt(question)

    assert "只输出一个选项字母" in prompt
    assert "不要解释" in prompt
    assert "A、B" in prompt


def test_run_model_check_for_node_summarizes_answers(monkeypatch) -> None:
    fake_client = _FakeClient(["B", "A"])
    monkeypatch.setattr("beartools.model_check._openai_client_factory", lambda node: fake_client)
    questions = [
        ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B"),
        ModelCheckQuestion(id="q2", question="2+2?", options={"A": "3", "B": "4"}, answer="B"),
    ]

    result = run_model_check_for_node(tier="small", node=_node(), questions=questions)

    assert result.correct_count == 1
    assert result.total_count == 2
    assert result.accuracy == 0.5
    assert fake_client.completions.calls[0]["model"] == "gpt-test"


def test_run_model_check_for_node_reports_progress(monkeypatch) -> None:
    fake_client = _FakeClient(["B", "A"])
    monkeypatch.setattr("beartools.model_check._openai_client_factory", lambda node: fake_client)
    questions = [
        ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B"),
        ModelCheckQuestion(id="q2", question="2+2?", options={"A": "3", "B": "4"}, answer="B"),
    ]
    events: list[ModelCheckProgressEvent] = []

    run_model_check_for_node(
        tier="small",
        node=_node(),
        questions=questions,
        progress_callback=events.append,
        node_index=2,
        total_nodes=3,
        completed_steps_before_node=2,
    )

    assert [event.question.id for event in events] == ["q1", "q2"]
    assert events[0].completed_steps == 2
    assert events[0].total_steps == 6
    assert events[0].node_index == 2
    assert events[1].completed_steps == 3


def test_run_model_check_for_node_reports_answers(monkeypatch) -> None:
    fake_client = _FakeClient(["B", "A"])
    monkeypatch.setattr("beartools.model_check._openai_client_factory", lambda node: fake_client)
    questions = [
        ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B"),
        ModelCheckQuestion(id="q2", question="2+2?", options={"A": "3", "B": "4"}, answer="B"),
    ]
    events = []

    run_model_check_for_node(tier="small", node=_node(), questions=questions, answer_callback=events.append)

    assert [event.answer.correct for event in events] == [True, False]
    assert events[0].completed_steps == 1
    assert events[1].answer.question_id == "q2"
    assert events[1].answer.predicted_answer == "A"
    assert events[1].answer.expected_answer == "B"


def test_render_model_check_markdown_includes_summary(monkeypatch) -> None:
    fake_client = _FakeClient(["B"])
    monkeypatch.setattr("beartools.model_check._openai_client_factory", lambda node: fake_client)
    questions = [ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B")]
    result = run_model_check_for_node(tier="small", node=_node(), questions=questions)

    markdown = render_model_check_markdown(SimpleNamespace(total_questions=1, results=[result], questions=questions))

    assert "| small | small-1 | gpt-test | 1/1 | 100.00% | 0 |" in markdown
    assert "### small/small-1 (gpt-test)" in markdown


def test_cli_registers_model_check_command() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["model", "check", "--help"])

    assert result.exit_code == 0
    assert "选择题题库" in result.stdout


def test_model_check_defaults() -> None:
    assert DEFAULT_MODEL_CHECK_QUESTIONS_PATH == Path("check/questions.yaml")
    assert DEFAULT_MODEL_CHECK_OUTPUT_PATH == Path("output/report.md")


def test_cli_progress_prints_name_model_and_base_url(monkeypatch) -> None:
    calls: list[str] = []
    question = ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B")
    event = ModelCheckProgressEvent(
        tier="small",
        node=_node(),
        question=question,
        node_index=1,
        total_nodes=2,
        question_index=1,
        total_questions=3,
        completed_steps=0,
        total_steps=6,
    )

    monkeypatch.setattr("beartools.commands.model.command.console.print", calls.append)

    _print_progress(event)

    assert "name=small-1" in calls[0]
    assert "model=gpt-test" in calls[0]
    assert "base_url=https://example.com/v1" in calls[0]


def test_cli_answer_prints_correct_or_wrong_result(monkeypatch) -> None:
    calls: list[str] = []
    question = ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B")
    node = _node()
    monkeypatch.setattr("beartools.commands.model.command.console.print", calls.append)

    _print_answer(
        SimpleNamespace(
            answer=SimpleNamespace(correct=True, question_id="q1"),
        )
    )
    _print_answer(
        SimpleNamespace(
            answer=SimpleNamespace(
                correct=False,
                question_id="q2",
                predicted_answer="A",
                raw_output="A",
                expected_answer="B",
                error=None,
            ),
            question=question,
            node=node,
        )
    )

    assert "正确: q1" in calls[0]
    assert "错误: q2" in calls[1]
    assert "模型结果=A" in calls[1]
    assert "正确答案=B" in calls[1]
