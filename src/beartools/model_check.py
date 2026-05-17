"""模型选择题评测功能。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import importlib
import json
from pathlib import Path
import time
from typing import Protocol, cast

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from beartools.llm.factory import LLFactory, LLMCandidate
from beartools.llm.runtime import AgentTier

DEFAULT_MODEL_CHECK_QUESTIONS_PATH = Path("check/questions.yaml")
DEFAULT_MODEL_CHECK_OUTPUT_DIR = Path("output")
DEFAULT_MODEL_CHECK_REPORT_STEM = "report"
ALLOWED_MODEL_CHECK_CHOICES = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


class _YamlModule(Protocol):
    def safe_load(self, stream: str) -> object: ...


class _OpenAIResponsesProtocol(Protocol):
    def create(self, **kwargs: object) -> object: ...


class _ResponseWithOutputText(Protocol):
    output_text: object


class _ResponseWithOutput(Protocol):
    output: object


class _ResponseOutputItemWithContent(Protocol):
    content: object


class _ResponseContentPartWithText(Protocol):
    text: object


@dataclass(frozen=True, slots=True)
class ModelCheckQuestion:
    """单道选择题。"""

    id: str
    question: str
    options: dict[str, str]
    answer: str


@dataclass(frozen=True, slots=True)
class ModelCheckAnswer:
    """单个模型对单题的回答结果。"""

    question_id: str
    expected_answer: str
    predicted_answer: str | None
    raw_output: str
    correct: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ModelCheckNodeResult:
    """单个模型节点的评测汇总。"""

    tier: AgentTier
    node: LLMCandidate
    answers: list[ModelCheckAnswer]
    duration_seconds: float

    @property
    def total_count(self) -> int:
        """题目总数。"""

        return len(self.answers)

    @property
    def correct_count(self) -> int:
        """答对题数。"""

        return sum(1 for answer in self.answers if answer.correct)

    @property
    def error_count(self) -> int:
        """调用失败题数。"""

        return sum(1 for answer in self.answers if answer.error is not None)

    @property
    def accuracy(self) -> float:
        """正确率。"""

        if not self.answers:
            return 0.0
        return self.correct_count / len(self.answers)


@dataclass(frozen=True, slots=True)
class ModelCheckReport:
    """模型评测总报告。"""

    questions: list[ModelCheckQuestion]
    results: list[ModelCheckNodeResult] = field(default_factory=list)

    @property
    def total_questions(self) -> int:
        """题目数量。"""

        return len(self.questions)


@dataclass(frozen=True, slots=True)
class ModelCheckProgressEvent:
    """模型评测进度事件。"""

    tier: AgentTier
    node: LLMCandidate
    question: ModelCheckQuestion
    node_index: int
    total_nodes: int
    question_index: int
    total_questions: int
    completed_steps: int
    total_steps: int


@dataclass(frozen=True, slots=True)
class ModelCheckAnswerEvent:
    """模型评测单题结果事件。"""

    tier: AgentTier
    node: LLMCandidate
    question: ModelCheckQuestion
    answer: ModelCheckAnswer
    node_index: int
    total_nodes: int
    question_index: int
    total_questions: int
    completed_steps: int
    total_steps: int


ModelCheckProgressCallback = Callable[[ModelCheckProgressEvent], None]
ModelCheckAnswerCallback = Callable[[ModelCheckAnswerEvent], None]


def _load_yaml(text: str) -> object:
    yaml_module = cast(_YamlModule, importlib.import_module("yaml"))
    return yaml_module.safe_load(text)


def _load_question_payload(path: Path) -> object:
    if not path.exists():
        raise FileNotFoundError(f"题库文件不存在: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload: object = json.loads(text)
        return payload
    return _load_yaml(text)


def _as_dict(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是对象")
    return {str(key): item for key, item in value.items()}


def _as_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{path} 必须是列表")
    return list(value)


def _as_non_empty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} 必须是非空字符串")
    return value.strip()


def _parse_options(value: object, path: str) -> dict[str, str]:
    raw_options = _as_dict(value, path)
    options: dict[str, str] = {}
    for raw_key, raw_value in raw_options.items():
        key = raw_key.strip().upper()
        if key not in ALLOWED_MODEL_CHECK_CHOICES:
            raise ValueError(f"{path}.{raw_key} 的选项名必须是 A-Z 之一")
        option_text = _as_non_empty_string(raw_value, f"{path}.{raw_key}")
        if key in options:
            raise ValueError(f"{path} 存在重复选项: {key}")
        options[key] = option_text
    if len(options) < 2:
        raise ValueError(f"{path} 至少需要两个选项")
    return dict(sorted(options.items()))


def _parse_question(value: object, index: int) -> ModelCheckQuestion:
    item = _as_dict(value, f"questions[{index}]")
    question_id = _as_non_empty_string(item.get("id", f"q{index + 1}"), f"questions[{index}].id")
    question = _as_non_empty_string(item.get("question"), f"questions[{index}].question")
    options = _parse_options(item.get("options"), f"questions[{index}].options")
    answer = _as_non_empty_string(item.get("answer"), f"questions[{index}].answer").upper()
    if answer not in options:
        raise ValueError(f"questions[{index}].answer 必须是 options 中的一个选项")
    return ModelCheckQuestion(id=question_id, question=question, options=options, answer=answer)


def load_model_check_questions(path: Path) -> list[ModelCheckQuestion]:
    """从 YAML/JSON 文件加载选择题。"""

    payload = _load_question_payload(path)
    if isinstance(payload, dict):
        payload_dict = _as_dict(payload, "题库")
        question_items = _as_list(payload_dict.get("questions"), "questions")
    else:
        question_items = _as_list(payload, "题库")

    questions = [_parse_question(item, index) for index, item in enumerate(question_items)]
    if not questions:
        raise ValueError("题库至少需要一道题")
    return questions


def filter_model_check_questions(
    questions: list[ModelCheckQuestion],
    question_id: str | None,
) -> list[ModelCheckQuestion]:
    """按题目 ID 过滤题库。"""

    if question_id is None or not question_id.strip():
        return questions

    normalized_question_id = question_id.strip()
    filtered_questions = [question for question in questions if question.id == normalized_question_id]
    if not filtered_questions:
        available_ids = ", ".join(question.id for question in questions)
        raise ValueError(f"未找到题目 ID: {normalized_question_id}，可用题目: {available_ids}")
    return filtered_questions


def collect_model_check_nodes() -> list[LLMCandidate]:
    """收集配置中的所有模型候选。"""

    factory = LLFactory()
    return factory.list_candidates(type="any", model_size="large") + factory.list_candidates(
        type="any", model_size="small"
    )


def filter_model_check_nodes(nodes: list[LLMCandidate], model_name: str | None) -> list[LLMCandidate]:
    """按模型 name 或 model 过滤节点。"""

    if model_name is None or not model_name.strip():
        return nodes

    normalized_model_name = model_name.strip()
    filtered_nodes = [
        node for node in nodes if node.name == normalized_model_name or node.model == normalized_model_name
    ]
    if not filtered_nodes:
        available_models = ", ".join(f"{node.tier}/{node.name}/{node.model}" for node in nodes)
        raise RuntimeError(f"未找到模型: {normalized_model_name}，可用模型: {available_models}")
    return filtered_nodes


def format_question_prompt(question: ModelCheckQuestion) -> str:
    """构造选择题评测提示词。"""

    option_lines = "\n".join(f"{key}. {text}" for key, text in question.options.items())
    valid_letters = "、".join(question.options)
    return (
        "请回答下面的单项选择题。\n"
        f"你必须只输出一个选项字母，只能是：{valid_letters}。\n"
        "不要解释，不要输出标点、空格、前后缀或其他任何文字。\n\n"
        f"题目：{question.question}\n"
        f"选项：\n{option_lines}"
    )


def _extract_response_text(response: object) -> str:
    """从 Responses API 响应中提取文本。"""

    if hasattr(response, "output_text"):
        response_with_output_text = cast(_ResponseWithOutputText, response)
        output_text = response_with_output_text.output_text
        if isinstance(output_text, str):
            return output_text.strip()

    if not hasattr(response, "output"):
        return ""

    response_with_output = cast(_ResponseWithOutput, response)
    output = response_with_output.output
    if not isinstance(output, list):
        return ""

    text_parts: list[str] = []
    for item in output:
        content = _get_output_item_content(item)
        if isinstance(content, str):
            text_parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        text_parts.extend(_extract_content_part_text(part) for part in content)
    return "".join(text_parts).strip()


def _get_output_item_content(item: object) -> object:
    """读取 Responses output item 的 content 字段。"""

    if isinstance(item, dict):
        return item.get("content")
    if hasattr(item, "content"):
        item_with_content = cast(_ResponseOutputItemWithContent, item)
        return item_with_content.content
    return ""


def _extract_content_part_text(part: object) -> str:
    """读取 Responses content part 的 text 字段。"""

    if isinstance(part, dict):
        text = part.get("text")
    elif hasattr(part, "text"):
        part_with_text = cast(_ResponseContentPartWithText, part)
        text = part_with_text.text
    else:
        return ""
    if isinstance(text, str):
        return text
    return ""


def parse_model_choice(raw_output: str, valid_options: set[str]) -> str | None:
    """从模型输出中提取选项字母。"""

    normalized_output = raw_output.strip().upper()
    if normalized_output in valid_options:
        return normalized_output
    return None


def _ask_question(client: OpenAI, node: LLMCandidate, question: ModelCheckQuestion) -> ModelCheckAnswer:
    prompt = format_question_prompt(question)
    response = client.responses.create(
        model=node.model,
        input=[
            {"role": "system", "content": "你是一个严谨的选择题答题器，只输出一个选项字母。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    raw_output = _extract_response_text(response)
    predicted_answer = parse_model_choice(raw_output, set(question.options.keys()))
    return ModelCheckAnswer(
        question_id=question.id,
        expected_answer=question.answer,
        predicted_answer=predicted_answer,
        raw_output=raw_output,
        correct=predicted_answer == question.answer,
    )


def _format_error(error: BaseException) -> str:
    if isinstance(error, APIStatusError):
        return f"{type(error).__name__}(status={error.status_code})"
    return type(error).__name__


def run_model_check_for_node(
    *,
    tier: AgentTier,
    node: LLMCandidate,
    questions: list[ModelCheckQuestion],
    progress_callback: ModelCheckProgressCallback | None = None,
    answer_callback: ModelCheckAnswerCallback | None = None,
    node_index: int = 1,
    total_nodes: int = 1,
    completed_steps_before_node: int = 0,
) -> ModelCheckNodeResult:
    """对单个模型节点执行所有题目。"""

    start_time = time.time()
    client = LLFactory().create_client(name=node.name, model_size=tier)
    if not isinstance(client, OpenAI):
        raise RuntimeError("model check 当前只支持 OpenAI 兼容 client")
    with client:
        answers: list[ModelCheckAnswer] = []
        total_steps = total_nodes * len(questions)
        for question_index, question in enumerate(questions, start=1):
            if progress_callback is not None:
                progress_callback(
                    ModelCheckProgressEvent(
                        tier=tier,
                        node=node,
                        question=question,
                        node_index=node_index,
                        total_nodes=total_nodes,
                        question_index=question_index,
                        total_questions=len(questions),
                        completed_steps=completed_steps_before_node + question_index - 1,
                        total_steps=total_steps,
                    )
                )
            try:
                answer = _ask_question(client, node, question)
            except (APIConnectionError, APITimeoutError, APIStatusError, TimeoutError) as exc:
                answer = ModelCheckAnswer(
                    question_id=question.id,
                    expected_answer=question.answer,
                    predicted_answer=None,
                    raw_output="",
                    correct=False,
                    error=_format_error(exc),
                )
            answers.append(answer)
            if answer_callback is not None:
                answer_callback(
                    ModelCheckAnswerEvent(
                        tier=tier,
                        node=node,
                        question=question,
                        answer=answer,
                        node_index=node_index,
                        total_nodes=total_nodes,
                        question_index=question_index,
                        total_questions=len(questions),
                        completed_steps=completed_steps_before_node + question_index,
                        total_steps=total_steps,
                    )
                )
    return ModelCheckNodeResult(
        tier=tier,
        node=node,
        answers=answers,
        duration_seconds=time.time() - start_time,
    )


def run_model_check(
    questions_path: Path,
    *,
    question_id: str | None = None,
    model_name: str | None = None,
    progress_callback: ModelCheckProgressCallback | None = None,
    answer_callback: ModelCheckAnswerCallback | None = None,
) -> ModelCheckReport:
    """执行模型选择题评测。"""

    questions = filter_model_check_questions(load_model_check_questions(questions_path), question_id)
    nodes = filter_model_check_nodes(collect_model_check_nodes(), model_name)
    if not nodes:
        raise RuntimeError("未配置任何 agent.large 或 agent.small 模型节点")

    results: list[ModelCheckNodeResult] = []
    total_nodes = len(nodes)
    for node_index, node in enumerate(nodes, start=1):
        results.append(
            run_model_check_for_node(
                tier=node.tier,
                node=node,
                questions=questions,
                progress_callback=progress_callback,
                answer_callback=answer_callback,
                node_index=node_index,
                total_nodes=total_nodes,
                completed_steps_before_node=(node_index - 1) * len(questions),
            )
        )
    return ModelCheckReport(questions=questions, results=results)


def render_model_check_markdown(report: ModelCheckReport) -> str:
    """将评测报告渲染为 Markdown。"""

    lines = [
        "# Model Check Report",
        "",
        f"- 题目数：{report.total_questions}",
        f"- 模型数：{len(report.results)}",
        "",
        "| Tier | Name | Model | Correct | Accuracy | Errors | Duration |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for result in report.results:
        lines.append(
            "| "
            f"{result.tier} | {result.node.name} | {result.node.model} | "
            f"{result.correct_count}/{result.total_count} | {result.accuracy:.2%} | "
            f"{result.error_count} | {result.duration_seconds:.2f}s |"
        )

    lines.extend(["", "## Details", ""])
    for result in report.results:
        lines.extend(
            [
                f"### {result.tier}/{result.node.name} ({result.node.model})",
                "",
                "| Question | Expected | Predicted | Correct | Raw Output | Error |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for answer in result.answers:
            predicted = answer.predicted_answer or ""
            raw_output = answer.raw_output.replace("|", "\\|").replace("\n", " ")
            error = answer.error or ""
            lines.append(
                "| "
                f"{answer.question_id} | {answer.expected_answer} | {predicted} | "
                f"{'yes' if answer.correct else 'no'} | {raw_output} | {error} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
