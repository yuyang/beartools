# Codex Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 beartools 增加 `codex run <md_path>` 子命令，读取本地 Markdown 作为 prompt，调用 Codex 官方流式 SDK，并同时输出 console、日志、最终回答文件与 trace 文件。

**Architecture:** 在现有 CLI 上新增独立 `codex` 命令组，通过 `CodexConfig` 解析专用配置，业务层集中处理 Markdown 读取、SDK 初始化、流式事件消费和双文件输出。实现过程中保持 `agent`/`llm` 运行时不变，降低回归风险。

**Tech Stack:** Python 3.13、Typer、Dynaconf、Rich、标准库 logging/pathlib/json、Codex 官方 Python SDK

---

### Task 1: 先补配置与 CLI 的失败测试

**Files:**
- Modify: `tests/test_cli_entrypoint.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_codex_command.py`

- [ ] **Step 1: 写 `codex` 命令组注册的失败测试**

```python
def test_cli_registers_codex_group() -> None:
    from typer.testing import CliRunner

    from beartools.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["codex", "--help"])

    assert result.exit_code == 0
    assert "run" in result.stdout
```

- [ ] **Step 2: 运行单测，确认因为命令未注册而失败**

Run: `uv run pytest tests/test_cli_entrypoint.py::test_cli_registers_codex_group -v`
Expected: FAIL，提示 `No such command 'codex'` 或断言 `run` 不存在

- [ ] **Step 3: 写 `codex` 独立配置解析的失败测试**

```python
def test_load_config_parses_codex_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "beartools.yaml").write_text(
        """
codex:
  base_url: https://codex.example.com
  model: codex-mini-latest
  output_dir: codex-output
  timeout_seconds: 45
""".strip(),
        encoding="utf-8",
    )
    (config_dir / "beartools.secrets.yaml").write_text(
        """
codex:
  api_key: secret-key
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from beartools.config import load_config, reset_config

    reset_config()
    config = load_config()

    assert config.codex.base_url == "https://codex.example.com"
    assert config.codex.api_key == "secret-key"
    assert config.codex.model == "codex-mini-latest"
    assert config.codex.output_dir == Path("codex-output")
    assert config.codex.timeout_seconds == 45
```

- [ ] **Step 4: 运行单测，确认因为 `Config` 尚无 `codex` 字段而失败**

Run: `uv run pytest tests/test_config.py::test_load_config_parses_codex_section -v`
Expected: FAIL，提示 `Config` 没有 `codex`

- [ ] **Step 5: 写 `codex run` 成功路径的失败测试**

```python
def test_codex_run_reads_markdown_and_writes_default_outputs(tmp_path: Path) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("# 标题\n\n请总结这段内容", encoding="utf-8")

    output_dir = tmp_path / "codex-output"

    from beartools.codex import CodexRunResult

    def fake_run_codex_markdown(*, md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
        assert md_path == md_file
        assert output_file is None
        assert trace_file is None
        final_file = output_dir / "prompt.codex.md"
        trace_out = output_dir / "prompt.codex.trace.log"
        final_file.parent.mkdir(parents=True, exist_ok=True)
        final_file.write_text("最终回答", encoding="utf-8")
        trace_out.write_text("trace", encoding="utf-8")
        return CodexRunResult(final_output_file=final_file, trace_output_file=trace_out, final_text="最终回答")

    with patch("beartools.commands.codex.command.run_codex_markdown", side_effect=fake_run_codex_markdown):
        result = runner.invoke(app, ["codex", "run", str(md_file)])

    assert result.exit_code == 0
    assert "prompt.codex.md" in result.stdout
    assert "prompt.codex.trace.log" in result.stdout
```

- [ ] **Step 6: 运行单测，确认因为命令模块与结果类型不存在而失败**

Run: `uv run pytest tests/test_codex_command.py::test_codex_run_reads_markdown_and_writes_default_outputs -v`
Expected: FAIL，提示导入 `beartools.codex` 或 `codex` 子命令失败

### Task 2: 实现配置模型与样例配置

**Files:**
- Modify: `src/beartools/config.py`
- Modify: `config/beartools.yaml.sample`
- Modify: `config/beartools.secrets.yaml.sample`

- [ ] **Step 1: 实现 `CodexConfig` 数据类与解析函数**

```python
@dataclass
class CodexConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    output_dir: Path = Path("output/codex")
    timeout_seconds: int = 60
    bin_path: str = ""
```

并增加：

```python
def _parse_codex_config(settings: _SettingsLike) -> CodexConfig:
    codex_settings = _as_dict(settings.get("codex", {}), "codex")
    return CodexConfig(
        base_url=_require_non_empty_string(codex_settings.get("base_url"), "codex.base_url"),
        api_key=_require_non_empty_string(codex_settings.get("api_key"), "codex.api_key"),
        model=_require_non_empty_string(codex_settings.get("model"), "codex.model"),
        output_dir=Path(str(codex_settings.get("output_dir", "output/codex"))),
        timeout_seconds=_parse_positive_int(codex_settings.get("timeout_seconds", 60), "codex.timeout_seconds", 60),
        bin_path=str(codex_settings.get("bin_path", "")),
    )
```

- [ ] **Step 2: 将 `codex` 挂入主配置对象**

```python
@dataclass
class Config:
    log: LogConfig = field(default_factory=LogConfig)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    siyuan: SiyuanConfig = field(default_factory=SiyuanConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)
```

并在 `_convert_to_dataclass()` 中调用 `_parse_codex_config(settings)`。

- [ ] **Step 3: 更新样例配置文件**

`config/beartools.yaml.sample` 增加：

```yaml
codex:
  base_url: "https://codex.example.com"
  model: "codex-mini-latest"
  output_dir: "output/codex"
  timeout_seconds: 60
  # bin_path: "/usr/local/bin/codex"
```

`config/beartools.secrets.yaml.sample` 增加：

```yaml
codex:
  api_key: "REPLACE_ME"
```

- [ ] **Step 4: 运行前面两条测试，确认转绿**

Run: `uv run pytest tests/test_cli_entrypoint.py::test_cli_registers_codex_group tests/test_config.py::test_load_config_parses_codex_section -v`
Expected: `test_load_config_parses_codex_section` PASS；CLI 测试此时仍可能 FAIL

### Task 3: 实现 Codex 业务模块

**Files:**
- Create: `src/beartools/codex.py`
- Test: `tests/test_codex_command.py`

- [ ] **Step 1: 写流式聚合与输出文件生成的失败测试**

```python
def test_run_codex_markdown_streams_events_and_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md_file = tmp_path / "prompt.md"
    md_file.write_text("请执行", encoding="utf-8")

    final_chunks: list[str] = []

    class FakeConsole:
        def print(self, message: str = "", end: str = "\n", style: str | None = None) -> None:
            del style
            final_chunks.append(message + end)

    class FakeLogger:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, message: str, *args: object) -> None:
            self.messages.append(message % args if args else message)

        def error(self, message: str, *args: object) -> None:
            self.messages.append(message % args if args else message)

    fake_events = [
        {"type": "item/agentMessage/delta", "delta": "思考中"},
        {"type": "item.started", "item": {"type": "command_execution", "command": "ls"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "status": "completed", "output": "file.txt"}},
        {"type": "response.output_text.delta", "delta": "最终回答"},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ]

    async def fake_stream_events(prompt: str) -> AsyncIterator[dict[str, object]]:
        assert prompt == "请执行"
        for event in fake_events:
            yield event

    monkeypatch.setattr("beartools.codex._stream_codex_events", fake_stream_events)
    monkeypatch.setattr("beartools.codex.console", FakeConsole())
    monkeypatch.setattr("beartools.codex.logger", FakeLogger())
```

并断言：

```python
    result = run_awaitable(run_codex_markdown_async(md_file, None, None))

    assert result.final_text == "最终回答"
    assert result.final_output_file.read_text(encoding="utf-8")
    assert result.trace_output_file.read_text(encoding="utf-8")
    assert any("tool:start" in chunk for chunk in final_chunks)
    assert any("thinking" in chunk for chunk in final_chunks)
```

- [ ] **Step 2: 运行单测，确认因为业务模块未实现而失败**

Run: `uv run pytest tests/test_codex_command.py::test_run_codex_markdown_streams_events_and_writes_outputs -v`
Expected: FAIL，提示 `beartools.codex` 中函数不存在

- [ ] **Step 3: 用最小实现补齐业务模块**

实现以下核心类型与函数：

```python
@dataclass
class CodexRunResult:
    final_output_file: Path
    trace_output_file: Path
    final_text: str

async def run_codex_markdown_async(md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
    ...

def run_codex_markdown(*, md_path: Path, output_file: Path | None, trace_file: Path | None) -> CodexRunResult:
    return asyncio.run(run_codex_markdown_async(md_path, output_file, trace_file))
```

最小逻辑要求：

- 读取 Markdown 全文
- 从配置推导默认输出路径
- 遍历 `_stream_codex_events(prompt)`
- reasoning 事件打印 `[thinking]`
- tool 开始/结束事件打印 `[tool:start]` / `[tool:done]`
- 文本 delta 追加到 `final_text_parts`
- 每个事件写入 trace 文件
- turn 完成后写最终回答文件

- [ ] **Step 4: 运行业务测试，确认转绿**

Run: `uv run pytest tests/test_codex_command.py::test_run_codex_markdown_streams_events_and_writes_outputs -v`
Expected: PASS

### Task 4: 接入官方 Codex SDK 与 CLI 命令

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/beartools/cli.py`
- Create: `src/beartools/commands/codex/__init__.py`
- Create: `src/beartools/commands/codex/command.py`
- Modify: `src/beartools/codex.py`
- Test: `tests/test_codex_command.py`

- [ ] **Step 1: 将官方 Codex SDK 依赖加入 `pyproject.toml`**

在依赖列表追加精确版本：

```toml
"openai-codex-app-server-sdk==0.2.0",
```

如果最终查到实际导入名不同，以官方文档对应的精确包名为准，但仍必须锁定 `==` 版本。

- [ ] **Step 2: 实现 `_stream_codex_events()` 真实接入**

```python
async def _stream_codex_events(prompt: str) -> AsyncIterator[dict[str, object]]:
    config = get_config().codex
    async with AsyncCodex(base_url=config.base_url, api_key=config.api_key, bin_path=config.bin_path or None) as codex:
        thread = await codex.thread_start(model=config.model)
        stream = thread.run_stream(prompt)
        async for event in stream:
            yield event
```

如果官方 SDK 的构造函数或事件对象不是 dict，则在这一层统一转成 `dict[str, object]` 或等价可序列化结构，避免业务层散落 SDK 细节。

- [ ] **Step 3: 实现 `codex run` 命令**

```python
codex_app = typer.Typer(help="Codex 相关操作")

@codex_app.command("run")
def codex_run(
    md_path: Path = typer.Argument(..., help="本地 Markdown 文件路径"),
    output_file: Path | None = typer.Option(None, help="最终回答输出文件"),
    trace_file: Path | None = typer.Option(None, help="trace 输出文件"),
) -> None:
    try:
        result = run_codex_markdown(md_path=md_path, output_file=output_file, trace_file=trace_file)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        console.print(f"错误: {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"回答已写入: {result.final_output_file}", style="green")
    console.print(f"Trace 已写入: {result.trace_output_file}", style="green")
```

- [ ] **Step 4: 在主 CLI 注册命令组**

```python
from beartools.commands.codex import codex_app

app.add_typer(codex_app, name="codex", help="Codex 相关操作")
```

- [ ] **Step 5: 运行 CLI 测试，确认命令注册与成功路径转绿**

Run: `uv run pytest tests/test_cli_entrypoint.py::test_cli_registers_codex_group tests/test_codex_command.py::test_codex_run_reads_markdown_and_writes_default_outputs -v`
Expected: PASS

### Task 5: 补失败路径测试与完善异常处理

**Files:**
- Modify: `tests/test_codex_command.py`
- Modify: `src/beartools/codex.py`
- Modify: `src/beartools/commands/codex/command.py`

- [ ] **Step 1: 写输入文件不存在的失败测试**

```python
def test_codex_run_missing_markdown_file_exits_with_error(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.md"

    result = runner.invoke(app, ["codex", "run", str(missing_file)])

    assert result.exit_code == 1
    assert "错误:" in result.stdout
```

- [ ] **Step 2: 运行单测，确认失败原因准确**

Run: `uv run pytest tests/test_codex_command.py::test_codex_run_missing_markdown_file_exits_with_error -v`
Expected: 初次 FAIL 时应明确暴露当前错误路径

- [ ] **Step 3: 用最小代码补齐输入校验与中途中断处理**

最小实现要求：

- `md_path` 不存在时抛 `FileNotFoundError`
- `md_path` 不是文件时抛 `ValueError`
- 流式执行异常时：
  - trace 文件追加异常信息
  - 若已有部分 `final_text`，结果文件写入已累计文本并标记未完成
  - 重新抛出 `RuntimeError`

- [ ] **Step 4: 运行失败路径测试，确认转绿**

Run: `uv run pytest tests/test_codex_command.py::test_codex_run_missing_markdown_file_exits_with_error -v`
Expected: PASS

### Task 6: 全量校验当前改动

**Files:**
- Verify: `src/beartools/cli.py`
- Verify: `src/beartools/config.py`
- Verify: `src/beartools/codex.py`
- Verify: `src/beartools/commands/codex/command.py`
- Verify: `tests/test_cli_entrypoint.py`
- Verify: `tests/test_codex_command.py`
- Verify: `tests/test_config.py`

- [ ] **Step 1: 运行 codex 相关测试**

Run: `uv run pytest tests/test_cli_entrypoint.py tests/test_config.py tests/test_codex_command.py -xvs`
Expected: 全部 PASS

- [ ] **Step 2: 运行 Ruff 检查**

Run: `uv run ruff check src/beartools/cli.py src/beartools/config.py src/beartools/codex.py src/beartools/commands/codex tests/test_cli_entrypoint.py tests/test_config.py tests/test_codex_command.py`
Expected: exit 0

- [ ] **Step 3: 运行 MyPy 检查**

Run: `uv run mypy src/beartools/cli.py src/beartools/config.py src/beartools/codex.py src/beartools/commands/codex`
Expected: Success, no issues found

- [ ] **Step 4: 人工回看 spec 覆盖情况**

核对以下要求都已覆盖：

- `codex run <md_path>` 已实现
- 只支持本地 Markdown
- 独立 `codex` 配置已实现
- stream 事件同时输出到 console 和日志
- tool 与 thinking 可见
- 最终回答文件与 trace 文件双输出
