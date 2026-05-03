# Codex Responses API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `src/beartools/codex.py` 从 ChatCompletions 路线切换到 Responses API，保留 `WebSearchTool + ShellTool`、CLI、trace 和 final output 的现有能力。

**Architecture:** 保留当前 `Runner.run_streamed(...).stream_events()` 结构与 `AsyncOpenAI(base_url, api_key)` 初始化方式，只把 model 明确切到 `OpenAIResponsesModel`。流式事件消费改为尽量基于官方 `RawResponsesStreamEvent`、`RunItemStreamEvent`、`ToolCallItem`、`ToolCallOutputItem`、`ReasoningItem` 和 `ResponseTextDeltaEvent` 来分支处理，而不是继续扩张自定义 dict 协议。

**Tech Stack:** Python 3.13+, openai-agents 0.7.x, OpenAI Responses API, pytest, typer, asyncio

---

## 文件结构

- Modify: `src/beartools/codex.py`
  - 将 `OpenAIChatCompletionsModel` 替换为 `OpenAIResponsesModel`
  - 直接消费官方流式事件 / item 类型
  - 保留 shell 执行器与输出落盘逻辑
- Modify: `tests/test_codex_command.py`
  - 更新 model patch 目标
  - 将流式测试改成更接近官方 Responses 事件结构
  - 保留 shell executor / tool 挂载测试
- Reference: `docs/superpowers/specs/2026-05-02-codex-responses-api-design.md`
  - 作为本次迁移设计依据

### Task 1: 为 Responses model 切换写失败测试

**Files:**
- Modify: `tests/test_codex_command.py`
- Modify: `src/beartools/codex.py`

- [ ] **Step 1: 将现有 model patch 目标改成 Responses 路线并写失败断言**

```python
def test_stream_codex_events_builds_agent_with_responses_model_and_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponsesModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["model_kwargs"] = kwargs

    monkeypatch.setattr("agents.models.OpenAIResponsesModel", FakeResponsesModel)
    _patch_codex_stream_dependencies(monkeypatch, captured)

    from beartools.codex import _stream_codex_events

    async def collect() -> None:
        async for _event in _stream_codex_events("hello"):
            pass

    asyncio.run(collect())

    assert captured["model_kwargs"] == {"model": "demo-model", "openai_client": captured["client"]}
```

- [ ] **Step 2: 运行单测，确认当前失败**

Run: `uv run pytest tests/test_codex_command.py::test_stream_codex_events_builds_agent_with_responses_model_and_tools -xvs`

Expected: FAIL，因为当前实现仍使用 `OpenAIChatCompletionsModel`。

- [ ] **Step 3: 在 `src/beartools/codex.py` 中将 model 初始化切到 `OpenAIResponsesModel`**

```python
from agents.models import OpenAIResponsesModel


model = OpenAIResponsesModel(
    model=config.model,
    openai_client=client,
)
```

- [ ] **Step 4: 再跑该测试，确认通过**

Run: `uv run pytest tests/test_codex_command.py::test_stream_codex_events_builds_agent_with_responses_model_and_tools -xvs`

Expected: PASS

### Task 2: 为官方事件消费方式写失败测试

**Files:**
- Modify: `tests/test_codex_command.py`
- Modify: `src/beartools/codex.py`

- [ ] **Step 1: 写失败测试，要求 `_stream_codex_events()` 能消费官方 Responses 事件对象而不是预构造 dict**

```python
def test_stream_codex_events_consumes_official_response_events(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks: list[str] = []

    class FakeTextDelta:
        delta = "最终回答"

    class FakeRawResponsesStreamEvent:
        type = "raw_response_event"

        def __init__(self) -> None:
            self.data = FakeTextDelta()

    class FakeToolCallItem:
        type = "tool_call_item"
        tool_name = "shell"

    class FakeToolCallOutputItem:
        type = "tool_call_output_item"
        output = '{"stdout": "ok"}'

    class FakeReasoningItem:
        type = "reasoning_item"
        raw_item = "思考中"

    class FakeRunItemStreamEvent:
        type = "run_item_stream_event"

        def __init__(self, name: str, item: object) -> None:
            self.name = name
            self.item = item

    fake_events = [
        FakeRunItemStreamEvent("reasoning_item_created", FakeReasoningItem()),
        FakeRunItemStreamEvent("tool_called", FakeToolCallItem()),
        FakeRunItemStreamEvent("tool_output", FakeToolCallOutputItem()),
        FakeRawResponsesStreamEvent(),
    ]

    async def fake_stream_events() -> AsyncIterator[object]:
        for event in fake_events:
            yield event
```

- [ ] **Step 2: 运行相关流式测试，确认当前失败或覆盖不到官方事件对象**

Run: `uv run pytest tests/test_codex_command.py::test_run_codex_markdown_streams_events_and_writes_outputs -xvs`

Expected: FAIL，或说明当前实现仍依赖中间 dict。

- [ ] **Step 3: 在 `src/beartools/codex.py` 中改为基于官方事件 / item 类型分发**

```python
from agents.items import ReasoningItem, ToolCallItem, ToolCallOutputItem
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from openai.types.responses import ResponseTextDeltaEvent


async for event in stream_events():
    if isinstance(event, RawResponsesStreamEvent) and isinstance(event.data, ResponseTextDeltaEvent):
        ...
    elif isinstance(event, RunItemStreamEvent):
        if isinstance(event.item, ToolCallItem):
            ...
        elif isinstance(event.item, ToolCallOutputItem):
            ...
        elif isinstance(event.item, ReasoningItem):
            ...
```

- [ ] **Step 4: 再跑流式测试，确认通过**

Run: `uv run pytest tests/test_codex_command.py::test_run_codex_markdown_streams_events_and_writes_outputs -xvs`

Expected: PASS

### Task 3: 更新测试桩与挂载断言

**Files:**
- Modify: `tests/test_codex_command.py`

- [ ] **Step 1: 调整 `_patch_codex_stream_dependencies()`，从 patch ChatCompletionsModel 改为 patch ResponsesModel**

```python
monkeypatch.setattr("agents.models.OpenAIResponsesModel", FakeResponsesModel)
```

- [ ] **Step 2: 保留并加强工具挂载测试，确认 `WebSearchTool + ShellTool` 仍一起挂载**

```python
tools = cast(list[object], captured["tools"])
tool_classes = {tool.__class__.__name__ for tool in tools}

assert "WebSearchTool" in tool_classes
assert "ShellTool" in tool_classes
```

- [ ] **Step 3: 运行挂载测试，确认通过**

Run: `uv run pytest tests/test_codex_command.py::test_stream_codex_events_builds_agent_with_responses_model_and_tools -xvs`

Expected: PASS

### Task 4: 回归 shell 行为与 CLI 行为

**Files:**
- Modify: `tests/test_codex_command.py`
- Reference: `src/beartools/codex.py:60`

- [ ] **Step 1: 保留 shell executor 工作目录测试，不改行为**

```python
assert executed["cwd"] == tmp_path / "output" / "codex"
assert result.output[0].stdout == "ok"
```

- [ ] **Step 2: 保留 CLI 缺文件错误测试和默认输出测试**

Run: `uv run pytest tests/test_codex_command.py::test_codex_run_reads_markdown_and_writes_default_outputs tests/test_codex_command.py::test_codex_run_missing_markdown_file_exits_with_error -xvs`

Expected: PASS

- [ ] **Step 3: 跑全部 codex 测试，确认 Responses 迁移未破坏现有功能**

Run: `uv run pytest tests/test_codex_command.py -xvs`

Expected: PASS

### Task 5: 静态检查与联调验证

**Files:**
- Modify: `src/beartools/codex.py`
- Modify: `tests/test_codex_command.py`

- [ ] **Step 1: 运行静态检查**

Run: `uv run ruff check src/beartools/codex.py tests/test_codex_command.py && uv run mypy src/beartools/codex.py tests/test_codex_command.py`

Expected: PASS

- [ ] **Step 2: 如果本地配置可用，运行一次真实命令验证不再报 hosted tools / ChatCompletions 不兼容错误**

Run: `uv run beartools codex run ./input/m1.md`

Expected: 不再出现 `Hosted tools are not supported with the ChatCompletions API` 报错；如果仍失败，应是网络、鉴权或模型侧问题，而不是 API 路线不兼容。

- [ ] **Step 3: 如命令仍失败，记录新的真实错误并停止，不要继续猜测修复**

```text
重点确认：是否已从 ChatCompletions 路线迁移成功；如果成功，新错误应属于 Hosted tool 真正执行阶段，而不是 model/tool 不兼容阶段。
```

## 自检结果

- 已覆盖 spec 中的全部要求：Responses model 切换、保留 tool 组合、官方事件消费、保留 CLI/shell/trace 行为。
- 计划未保留 TBD/TODO 占位项。
- 关键名称保持一致：`OpenAIResponsesModel`、`RawResponsesStreamEvent`、`RunItemStreamEvent`、`ToolCallItem`、`ToolCallOutputItem`、`ReasoningItem`、`ResponseTextDeltaEvent`。
