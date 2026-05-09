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

from beartools.config import AgentNodeConfig, get_config
from beartools.llm.runtime import RuntimeNode

DEFAULT_MODEL_CHECK_QUESTIONS_PATH = Path("check/questions.yaml")
DEFAULT_MODEL_CHECK_OUTPUT_PATH = Path("output/report.md")
ALLOWED_MODEL_CHECK_CHOICES = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


class _YamlModule(Protocol):
    def safe_load(self, stream: str) -> object: ...


class _OpenAIChatCompletionsProtocol(Protocol):
    def create(self, **kwargs: object) -> object: ...


class _OpenAIChatProtocol(Protocol):
    completions: _OpenAIChatCompletionsProtocol


class _OpenAIClientProtocol(Protocol):
    chat: _OpenAIChatProtocol


class _ChatResponseWithChoices(Protocol):
    choices: object


class _ChatChoiceWithMessage(Protocol):
    message: object


class _ChatMessageWithContent(Protocol):
    content: object


class _ChatContentPartWithText(Protocol):
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

    tier: str
    node: RuntimeNode
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

    tier: str
    node: RuntimeNode
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

    tier: str
    node: RuntimeNode
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


def _runtime_nodes_from_config_nodes(config_nodes: list[AgentNodeConfig]) -> list[RuntimeNode]:
    nodes: list[RuntimeNode] = []
    seen_fingerprints: set[str] = set()
    for config_node in config_nodes:
        node = RuntimeNode.from_config(config_node)
        if node.fingerprint in seen_fingerprints:
            continue
        nodes.append(node)
        seen_fingerprints.add(node.fingerprint)
    return nodes


def collect_model_check_nodes() -> list[tuple[str, RuntimeNode]]:
    """收集配置里的所有去重模型节点。"""

    agent_config = get_config().agent
    candidates: list[tuple[str, RuntimeNode]] = []
    seen_fingerprints: set[str] = set()
    for tier, config_nodes in (("large", agent_config.large), ("small", agent_config.small)):
        for node in _runtime_nodes_from_config_nodes(config_nodes):
            if node.fingerprint in seen_fingerprints:
                continue
            candidates.append((tier, node))
            seen_fingerprints.add(node.fingerprint)
    return candidates


def _openai_client_factory(node: RuntimeNode) -> _OpenAIClientProtocol:
    return cast(
        _OpenAIClientProtocol,
        OpenAI(
            base_url=node.base_url,
            api_key=node.api_key,
            timeout=float(node.timeout_seconds),
            default_headers=node.extra_headers,
        ),
    )


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
    if not hasattr(response, "choices"):
        return ""
    response_with_choices = cast(_ChatResponseWithChoices, response)
    choices = response_with_choices.choices
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not hasattr(first_choice, "message"):
        return ""
    choice_with_message = cast(_ChatChoiceWithMessage, first_choice)
    message = choice_with_message.message
    if not hasattr(message, "content"):
        return ""
    message_with_content = cast(_ChatMessageWithContent, message)
    content = message_with_content.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not hasattr(part, "text"):
                continue
            part_with_text = cast(_ChatContentPartWithText, part)
            text = part_with_text.text
            if isinstance(text, str):
                text_parts.append(text)
        return "".join(text_parts).strip()
    return ""


def parse_model_choice(raw_output: str, valid_options: set[str]) -> str | None:
    """从模型输出中提取选项字母。"""

    normalized_output = raw_output.strip().upper()
    if normalized_output in valid_options:
        return normalized_output
    return None


def _ask_question(client: _OpenAIClientProtocol, node: RuntimeNode, question: ModelCheckQuestion) -> ModelCheckAnswer:
    prompt = format_question_prompt(question)
    response = client.chat.completions.create(
        model=node.model,
        messages=[
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
    tier: str,
    node: RuntimeNode,
    questions: list[ModelCheckQuestion],
    progress_callback: ModelCheckProgressCallback | None = None,
    answer_callback: ModelCheckAnswerCallback | None = None,
    node_index: int = 1,
    total_nodes: int = 1,
    completed_steps_before_node: int = 0,
) -> ModelCheckNodeResult:
    """对单个模型节点执行所有题目。"""

    start_time = time.time()
    client = _openai_client_factory(node)
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
    progress_callback: ModelCheckProgressCallback | None = None,
    answer_callback: ModelCheckAnswerCallback | None = None,
) -> ModelCheckReport:
    """执行模型选择题评测。"""

    questions = load_model_check_questions(questions_path)
    nodes = collect_model_check_nodes()
    if not nodes:
        raise RuntimeError("未配置任何 agent.large 或 agent.small 模型节点")

    results: list[ModelCheckNodeResult] = []
    total_nodes = len(nodes)
    for node_index, (tier, node) in enumerate(nodes, start=1):
        results.append(
            run_model_check_for_node(
                tier=tier,
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
