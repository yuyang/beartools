from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from beartools.cli import app
from beartools.commands.model.command import _print_answer, _print_progress, resolve_default_report_path
from beartools.llm.runtime import RuntimeNode, RuntimeNodeSummary
from beartools.model_check import (
    ALLOWED_MODEL_CHECK_CHOICES,
    DEFAULT_MODEL_CHECK_OUTPUT_DIR,
    DEFAULT_MODEL_CHECK_QUESTIONS_PATH,
    DEFAULT_MODEL_CHECK_REPORT_STEM,
    ModelCheckProgressEvent,
    ModelCheckQuestion,
    _extract_response_text,
    filter_model_check_nodes,
    filter_model_check_questions,
    format_question_prompt,
    load_model_check_questions,
    parse_model_choice,
    render_model_check_markdown,
    run_model_check,
    run_model_check_for_node,
)


class _FakeResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        return SimpleNamespace(output_text=output)


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.responses = _FakeResponses(outputs)
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        self.close()


class _FakeLLFactory:
    clients: list[_FakeClient] = []
    requests: list[tuple[str, str]] = []

    def create_client(self, *, name: str, model_size: str) -> _FakeClient:
        self.requests.append((name, model_size))
        return self.clients.pop(0)


def _node(name: str = "small-1", model: str = "gpt-test", fingerprint: str = "fp") -> RuntimeNode:
    return RuntimeNode(
        name=name,
        provider="openai",
        base_url="https://example.com/v1",
        model=model,
        api_key="key",
        extra_headers={},
        timeout_seconds=30,
        fingerprint=fingerprint,
    )


def _summary(name: str = "small-1", tier: str = "small", model: str = "gpt-test") -> RuntimeNodeSummary:
    return RuntimeNodeSummary(
        name=name,
        tier=tier,
        provider="openai",
        _model=model,
        _base_url="https://example.com/v1",
        _timeout_seconds=30,
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


def test_filter_model_check_questions_by_id() -> None:
    questions = [
        ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B"),
        ModelCheckQuestion(id="q2", question="2+2?", options={"A": "3", "B": "4"}, answer="B"),
    ]

    filtered_questions = filter_model_check_questions(questions, "q2")

    assert [question.id for question in filtered_questions] == ["q2"]


def test_filter_model_check_nodes_by_name_or_model() -> None:
    nodes = [
        _summary(name="node-a", tier="small", model="model-a"),
        _summary(name="node-b", tier="large", model="model-b"),
    ]

    assert [node.name for node in filter_model_check_nodes(nodes, "node-b")] == ["node-b"]
    assert [node._model for node in filter_model_check_nodes(nodes, "model-a")] == ["model-a"]


def test_format_question_prompt_requires_single_letter_output() -> None:
    question = ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B")

    prompt = format_question_prompt(question)

    assert "只输出一个选项字母" in prompt
    assert "不要解释" in prompt
    assert "A、B" in prompt


def test_run_model_check_for_node_summarizes_answers(monkeypatch) -> None:
    fake_client = _FakeClient(["B", "A"])
    _FakeLLFactory.clients = [fake_client]
    _FakeLLFactory.requests = []
    monkeypatch.setattr("beartools.model_check.LLFactory", _FakeLLFactory)
    monkeypatch.setattr("beartools.model_check.OpenAI", _FakeClient)
    questions = [
        ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B"),
        ModelCheckQuestion(id="q2", question="2+2?", options={"A": "3", "B": "4"}, answer="B"),
    ]

    result = run_model_check_for_node(tier="small", node=_summary(), questions=questions)

    assert result.correct_count == 1
    assert result.total_count == 2
    assert result.accuracy == 0.5
    assert _FakeLLFactory.requests == [("small-1", "small")]
    assert fake_client.responses.calls[0]["model"] == "gpt-test"
    assert fake_client.responses.calls[0]["temperature"] == 0
    response_input = fake_client.responses.calls[0]["input"]
    assert isinstance(response_input, list)
    assert response_input[0]["role"] == "system"
    assert response_input[1]["role"] == "user"
    assert "只输出一个选项字母" in response_input[1]["content"]


def test_extract_response_text_from_output_items() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(text="B"),
                ],
            )
        ]
    )

    assert _extract_response_text(response) == "B"


def test_run_model_check_for_node_reports_progress(monkeypatch) -> None:
    fake_client = _FakeClient(["B", "A"])
    _FakeLLFactory.clients = [fake_client]
    _FakeLLFactory.requests = []
    monkeypatch.setattr("beartools.model_check.LLFactory", _FakeLLFactory)
    monkeypatch.setattr("beartools.model_check.OpenAI", _FakeClient)
    questions = [
        ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B"),
        ModelCheckQuestion(id="q2", question="2+2?", options={"A": "3", "B": "4"}, answer="B"),
    ]
    events: list[ModelCheckProgressEvent] = []

    run_model_check_for_node(
        tier="small",
        node=_summary(),
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
    _FakeLLFactory.clients = [fake_client]
    _FakeLLFactory.nodes = []
    monkeypatch.setattr("beartools.model_check.LLFactory", _FakeLLFactory)
    monkeypatch.setattr("beartools.model_check.OpenAI", _FakeClient)
    questions = [
        ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B"),
        ModelCheckQuestion(id="q2", question="2+2?", options={"A": "3", "B": "4"}, answer="B"),
    ]
    events = []

    run_model_check_for_node(tier="small", node=_summary(), questions=questions, answer_callback=events.append)

    assert [event.answer.correct for event in events] == [True, False]
    assert events[0].completed_steps == 1
    assert events[1].answer.question_id == "q2"
    assert events[1].answer.predicted_answer == "A"
    assert events[1].answer.expected_answer == "B"


def test_run_model_check_filters_question_id_and_model_name(monkeypatch, tmp_path: Path) -> None:
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        """
questions:
  - id: q1
    question: 1+1?
    options:
      A: "1"
      B: "2"
    answer: B
  - id: q2
    question: 2+2?
    options:
      A: "3"
      B: "4"
    answer: B
""",
        encoding="utf-8",
    )
    fake_client = _FakeClient(["B"])
    _FakeLLFactory.clients = [fake_client]
    _FakeLLFactory.requests = []
    nodes = [
        _summary(name="node-a", tier="small", model="model-a"),
        _summary(name="node-b", tier="large", model="model-b"),
    ]
    monkeypatch.setattr("beartools.model_check.LLFactory", _FakeLLFactory)
    monkeypatch.setattr("beartools.model_check.OpenAI", _FakeClient)
    monkeypatch.setattr(
        "beartools.model_check.get_llm_runtime",
        lambda: SimpleNamespace(list_models=lambda provider, tier: [node for node in nodes if node.tier == tier]),
    )

    report = run_model_check(questions_path, question_id="q2", model_name="model-b")

    assert report.total_questions == 1
    assert report.questions[0].id == "q2"
    assert len(report.results) == 1
    assert report.results[0].node.name == "node-b"
    assert _FakeLLFactory.requests == [("node-b", "large")]


def test_render_model_check_markdown_includes_summary(monkeypatch) -> None:
    fake_client = _FakeClient(["B"])
    _FakeLLFactory.clients = [fake_client]
    _FakeLLFactory.nodes = []
    monkeypatch.setattr("beartools.model_check.LLFactory", _FakeLLFactory)
    monkeypatch.setattr("beartools.model_check.OpenAI", _FakeClient)
    questions = [ModelCheckQuestion(id="q1", question="1+1?", options={"A": "1", "B": "2"}, answer="B")]
    result = run_model_check_for_node(tier="small", node=_summary(), questions=questions)

    markdown = render_model_check_markdown(SimpleNamespace(total_questions=1, results=[result], questions=questions))

    assert "| small | small-1 | gpt-test | 1/1 | 100.00% | 0 |" in markdown
    assert "### small/small-1 (gpt-test)" in markdown


def test_cli_registers_model_check_command() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["model", "check", "--help"])

    assert result.exit_code == 0
    assert "选择题题库" in result.stdout
    assert "--id" in result.stdout
    assert "--model-name" in result.stdout


def test_model_check_defaults() -> None:
    assert DEFAULT_MODEL_CHECK_QUESTIONS_PATH == Path("check/questions.yaml")
    assert DEFAULT_MODEL_CHECK_OUTPUT_DIR == Path("output")
    assert DEFAULT_MODEL_CHECK_REPORT_STEM == "report"


def test_resolve_default_report_path_uses_timestamp() -> None:
    from datetime import datetime

    report_path = resolve_default_report_path(datetime(2026, 5, 9, 20, 30, 45))

    assert report_path == Path("output/report-20260509-203045.md")


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
    assert "provider=openai" in calls[0]
    assert "base_url" not in calls[0]


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
