# Codex WebSearchTool 与 ShellTool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `src/beartools/codex.py` 挂载 `WebSearchTool` 与本地 `ShellTool`，让 Codex 具备联网搜索和在 `output/codex` 目录执行 shell 命令的能力。

**Architecture:** 保持现有 `codex.py` 作为 Codex 运行主入口，在该文件内新增工具构建与本地 shell executor，避免本次引入新的 runtime 抽象层。测试继续围绕 `tests/test_codex_command.py` 扩展，优先验证工具挂载、shell 工作目录和结果可消费性。

**Tech Stack:** Python 3.13+, openai-agents 0.7.x, pytest, typer, asyncio

---

## 文件结构

- Modify: `src/beartools/codex.py`
  - 新增 `WebSearchTool` / `ShellTool` 组装逻辑
  - 新增本地 shell executor
  - 保持现有流式事件输出与失败落盘逻辑
- Modify: `tests/test_codex_command.py`
  - 新增面向 codex 工具挂载和 shell executor 的单测
- Reference: `src/beartools/config.py:104`
  - 复用 `CodexConfig.output_dir` 与 `CodexConfig.timeout_seconds`

### Task 1: 为 ShellTool executor 写失败测试

**Files:**
- Modify: `tests/test_codex_command.py`
- Reference: `src/beartools/codex.py:56`

- [ ] **Step 1: 写一个失败测试，验证 shell executor 固定使用 `output/codex` 工作目录**

```python
def test_shell_executor_runs_in_output_codex_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"ok", b"")

    async def fake_create_subprocess_shell(
        command: str,
        *,
        cwd: Path,
        stdout: object,
        stderr: object,
    ) -> FakeProcess:
        executed["command"] = command
        executed["cwd"] = cwd
        executed["stdout"] = stdout
        executed["stderr"] = stderr
        return FakeProcess()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_create_subprocess_shell)

    from beartools.codex import _execute_shell_commands

    result = asyncio.run(_execute_shell_commands(["pwd"], timeout_seconds=5))

    assert executed["command"] == "pwd"
    assert executed["cwd"] == tmp_path / "output" / "codex"
    assert result.output[0].stdout == "ok"
```

- [ ] **Step 2: 运行单测，确认当前会失败**

Run: `uv run pytest tests/test_codex_command.py::test_shell_executor_runs_in_output_codex_directory -xvs`

Expected: FAIL，提示 `beartools.codex` 中不存在 `_execute_shell_commands`，或返回结构与断言不符。

- [ ] **Step 3: 在 `src/beartools/codex.py` 中写最小实现，增加 shell 执行辅助函数**

```python
from asyncio.subprocess import PIPE


async def _execute_shell_commands(commands: list[str], timeout_seconds: int) -> ShellResult:
    working_dir = Path.cwd() / "output" / "codex"
    working_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[ShellCommandOutput] = []
    for command in commands:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=working_dir,
            stdout=PIPE,
            stderr=PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        outputs.append(
            ShellCommandOutput(
                command=command,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                outcome=ShellCallOutcome(type="exit", exit_code=process.returncode),
            )
        )
    return ShellResult(output=outputs)
```

- [ ] **Step 4: 再跑单测，确认通过**

Run: `uv run pytest tests/test_codex_command.py::test_shell_executor_runs_in_output_codex_directory -xvs`

Expected: PASS

### Task 2: 为 ShellTool SDK executor 适配层写失败测试

**Files:**
- Modify: `tests/test_codex_command.py`
- Modify: `src/beartools/codex.py`

- [ ] **Step 1: 写失败测试，验证 `ShellCommandRequest` 会被转交给本地执行函数**

```python
def test_shell_tool_executor_uses_request_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_execute_shell_commands(commands: list[str], timeout_seconds: int):
        captured["commands"] = commands
        captured["timeout_seconds"] = timeout_seconds
        return "done"

    class FakeAction:
        commands = ["ls", "pwd"]

    class FakeData:
        action = FakeAction()

    class FakeRequest:
        data = FakeData()

    monkeypatch.setattr("beartools.codex._execute_shell_commands", fake_execute_shell_commands)

    from beartools.codex import _shell_tool_executor

    result = asyncio.run(_shell_tool_executor(FakeRequest()))

    assert captured["commands"] == ["ls", "pwd"]
    assert captured["timeout_seconds"] == 60
    assert result == "done"
```

- [ ] **Step 2: 运行单测，确认当前会失败**

Run: `uv run pytest tests/test_codex_command.py::test_shell_tool_executor_uses_request_commands -xvs`

Expected: FAIL，提示 `_shell_tool_executor` 不存在。

- [ ] **Step 3: 在 `src/beartools/codex.py` 中实现 `ShellTool` executor 适配层**

```python
async def _shell_tool_executor(request: ShellCommandRequest) -> str | ShellResult:
    config = get_config().codex
    commands = list(request.data.action.commands)
    return await _execute_shell_commands(commands, timeout_seconds=config.timeout_seconds)
```

- [ ] **Step 4: 再跑单测，确认通过**

Run: `uv run pytest tests/test_codex_command.py::test_shell_tool_executor_uses_request_commands -xvs`

Expected: PASS

### Task 3: 为 Agent 工具挂载写失败测试

**Files:**
- Modify: `tests/test_codex_command.py`
- Modify: `src/beartools/codex.py`

- [ ] **Step 1: 写失败测试，验证 Agent 创建时包含 `WebSearchTool` 与 `ShellTool`**

```python
def test_stream_codex_events_builds_agent_with_websearch_and_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, *, name: str, instructions: str, model: object, tools: list[object]) -> None:
            captured["name"] = name
            captured["instructions"] = instructions
            captured["model"] = model
            captured["tools"] = tools

    class FakeResult:
        def stream_events(self):
            async def _empty():
                if False:
                    yield {}
            return _empty

    class FakeRunner:
        @staticmethod
        def run_streamed(agent: object, input: str) -> FakeResult:
            captured["runner_agent"] = agent
            captured["input"] = input
            return FakeResult()

    monkeypatch.setattr("agents.Agent", FakeAgent)
    monkeypatch.setattr("agents.Runner", FakeRunner)

    from beartools.codex import _stream_codex_events

    asyncio.run(_collect_events(_stream_codex_events("hello")))

    tool_names = {tool.name for tool in captured["tools"]}
    assert "web_search" in tool_names
    assert "shell" in tool_names
```

- [ ] **Step 2: 运行单测，确认当前会失败**

Run: `uv run pytest tests/test_codex_command.py::test_stream_codex_events_builds_agent_with_websearch_and_shell -xvs`

Expected: FAIL，提示 Agent 未接收到 `tools`，或工具名断言不成立。

- [ ] **Step 3: 在 `src/beartools/codex.py` 中增加工具构建逻辑并挂到 Agent 上**

```python
def _build_codex_tools() -> list[object]:
    return [
        WebSearchTool(),
        ShellTool(executor=_shell_tool_executor),
    ]


agent = Agent(
    name="Codex Runner",
    instructions=config.instructions,
    model=model,
    tools=_build_codex_tools(),
)
```

- [ ] **Step 4: 再跑单测，确认通过**

Run: `uv run pytest tests/test_codex_command.py::test_stream_codex_events_builds_agent_with_websearch_and_shell -xvs`

Expected: PASS

### Task 4: 为现有 trace 消费能力补回归测试

**Files:**
- Modify: `tests/test_codex_command.py`
- Reference: `src/beartools/codex.py:111`

- [ ] **Step 1: 扩展现有流式测试，加入 shell tool 输出事件**

```python
fake_events = [
    {"type": "tool_called", "name": "shell"},
    {
        "type": "tool_output",
        "name": "shell",
        "output": "{\"stdout\": \"ok\", \"stderr\": \"\", \"exit_code\": 0}",
    },
    {"type": "response.output_text.delta", "delta": "最终回答"},
]
```

- [ ] **Step 2: 运行流式测试，确认当前失败或覆盖不足**

Run: `uv run pytest tests/test_codex_command.py::test_run_codex_markdown_streams_events_and_writes_outputs -xvs`

Expected: 如果当前断言不足，先补断言后观察失败；至少要看到测试不能证明 shell 输出被消费。

- [ ] **Step 3: 将断言补齐，明确校验 shell 工具事件被写入输出和 trace**

```python
trace_text = result.trace_output_file.read_text(encoding="utf-8")

assert any("tool:start" in chunk for chunk in final_chunks)
assert any("shell" in chunk for chunk in final_chunks)
assert "tool_output" in trace_text
assert "shell" in trace_text
```

- [ ] **Step 4: 再跑该测试，确认通过**

Run: `uv run pytest tests/test_codex_command.py::test_run_codex_markdown_streams_events_and_writes_outputs -xvs`

Expected: PASS

### Task 5: 全量验证与整理

**Files:**
- Modify: `src/beartools/codex.py`
- Modify: `tests/test_codex_command.py`

- [ ] **Step 1: 运行 codex 相关测试集**

Run: `uv run pytest tests/test_codex_command.py -xvs`

Expected: PASS

- [ ] **Step 2: 运行静态检查，确认新代码符合项目要求**

Run: `uv run ruff check src/beartools/codex.py tests/test_codex_command.py && uv run mypy src/beartools/codex.py tests/test_codex_command.py`

Expected: PASS

- [ ] **Step 3: 如静态检查失败，做最小修正并复跑**

```python
# 典型修正方向：
# - 为新增函数补足精确返回类型
# - 避免 Any，必要时引入协议类型或 object
# - 调整 monkeypatch 测试桩签名以匹配真实调用
```

- [ ] **Step 4: 记录最终变更范围，准备交付说明**

```text
- `src/beartools/codex.py`：新增 WebSearchTool/ShellTool 挂载、本地 shell executor
- `tests/test_codex_command.py`：新增工具挂载与 shell 工作目录测试
```

## 自检结果

- 已覆盖 spec 中的全部要求：工具挂载、固定工作目录、复用现有配置、最小测试范围。
- 计划中未保留 TBD/TODO 占位语句。
- 任务中的函数名保持一致：`_execute_shell_commands`、`_shell_tool_executor`、`_build_codex_tools`。
