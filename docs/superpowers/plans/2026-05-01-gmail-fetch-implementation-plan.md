# Gmail Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 beartools 增加 `gmail fetch` 子命令，抓取最近 `n` 天内的 `INBOX` 邮件，最多处理前 100 封，使用现有 LLM 生成最重要 10 封邮件与总体概览，并同时打印到终端与保存到 `./email/` 目录。

**Architecture:** 新功能拆为三层：CLI 命令层负责参数与展示；`beartools.gmail` 负责 OAuth、Gmail API 查询、正文提取、Markdown 输出；摘要逻辑复用现有 LLM 工厂，统一对整批邮件生成结果。配置扩展走现有 `Config` dataclass + Dynaconf 解析模式，测试遵循 TDD，先写失败测试，再补最小实现。

**Tech Stack:** Python 3.13+, Typer, Google Gmail API client, OAuth 本地浏览器授权, PydanticAI/OpenAI 兼容模型, pytest, unittest.mock

---

## File Structure

- Create: `src/beartools/commands/gmail/__init__.py`
  - 注册 `gmail_app`，供主 CLI 挂载。
- Create: `src/beartools/commands/gmail/command.py`
  - 暴露 `gmail fetch` 命令，处理 `--days`、`--max-results`、终端输出与异常转译。
- Create: `src/beartools/gmail.py`
  - 放置 Gmail 配置类型、OAuth 客户端构建、邮件列表查询、详情解析、正文提取、批量摘要、Markdown 落盘。
- Modify: `src/beartools/config.py`
  - 增加 Gmail 配置 dataclass 与解析逻辑。
- Modify: `src/beartools/cli.py`
  - 注册 `gmail` 命令组。
- Modify: `config/beartools.yaml.sample`
  - 增加非敏感 Gmail 配置示例。
- Modify: `config/beartools.secrets.yaml.sample`
  - 增加 OAuth 私密配置示例。
- Modify: `pyproject.toml`
  - 增加 Gmail API/OAuth 所需精确版本依赖。
- Create: `tests/test_gmail.py`
  - Gmail 业务与 CLI 测试。
- Modify: `tests/test_cli_entrypoint.py`
  - 验证 `gmail` 命令组已注册。

### Task 1: 配置与 CLI 骨架

**Files:**
- Create: `src/beartools/commands/gmail/__init__.py`
- Create: `src/beartools/commands/gmail/command.py`
- Modify: `src/beartools/cli.py`
- Modify: `src/beartools/config.py`
- Modify: `tests/test_cli_entrypoint.py`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: 写配置与 CLI 注册的失败测试**

```python
from typer.testing import CliRunner

from beartools.cli import app

runner = CliRunner()


def test_gmail_command_group_is_registered() -> None:
    result = runner.invoke(app, ["gmail", "--help"])

    assert result.exit_code == 0
    assert "fetch" in result.stdout


def test_gmail_fetch_uses_default_days() -> None:
    result = runner.invoke(app, ["gmail", "fetch", "--help"])

    assert result.exit_code == 0
    assert "--days" in result.stdout
    assert "默认" in result.stdout
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_cli_entrypoint.py tests/test_gmail.py -xvs`
Expected: FAIL，因为 `gmail` 命令组和测试文件尚不存在。

- [ ] **Step 3: 写最小 CLI 骨架与 Gmail 配置结构**

```python
# src/beartools/commands/gmail/__init__.py
from beartools.commands.gmail.command import gmail_app

__all__ = ["gmail_app"]
```

```python
# src/beartools/commands/gmail/command.py
from __future__ import annotations

import typer

gmail_app = typer.Typer(help="Gmail 邮件相关操作", add_completion=False)


@gmail_app.command("fetch")
def fetch(
    days: int = typer.Option(3, "--days", min=1, help="抓取最近多少天的 INBOX 邮件，默认 3 天"),
    max_results: int = typer.Option(100, "--max-results", min=1, help="最多处理多少封邮件，默认 100 封"),
) -> None:
    del days, max_results
    raise typer.Exit(0)
```

```python
# src/beartools/config.py
@dataclass
class GmailConfig:
    """Gmail 配置"""

    client_secret_file: Path = Path("config/client_secret.json")
    token_file: Path = Path("config/gmail.token.json")
    output_dir: Path = Path("email")
    default_days: int = 3
    max_results: int = 100


@dataclass
class Config:
    log: LogConfig = field(default_factory=LogConfig)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    siyuan: SiyuanConfig = field(default_factory=SiyuanConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
```

```python
# src/beartools/cli.py
from beartools.commands.gmail import gmail_app

app.add_typer(gmail_app, name="gmail", help="Gmail 邮件相关操作")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cli_entrypoint.py tests/test_gmail.py -xvs`
Expected: PASS，`gmail` 命令组可见，`fetch --help` 展示默认参数说明。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/commands/gmail/__init__.py src/beartools/commands/gmail/command.py src/beartools/cli.py src/beartools/config.py tests/test_cli_entrypoint.py tests/test_gmail.py
git commit -m "ADD: 添加 gmail 命令骨架"
```

### Task 2: 配置解析与样例配置

**Files:**
- Modify: `src/beartools/config.py`
- Modify: `config/beartools.yaml.sample`
- Modify: `config/beartools.secrets.yaml.sample`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: 写 Gmail 配置解析失败测试**

```python
from pathlib import Path

from beartools.config import load_config, reset_config


def test_load_config_reads_gmail_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "beartools.yaml").write_text(
        """
gmail:
  output_dir: email-cache
  default_days: 5
  max_results: 100
""".strip(),
        encoding="utf-8",
    )
    (config_dir / "beartools.secrets.yaml").write_text(
        """
gmail:
  client_secret_file: config/client_secret.json
  token_file: config/gmail.token.json
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    reset_config()

    config = load_config()

    assert config.gmail.output_dir == Path("email-cache")
    assert config.gmail.default_days == 5
    assert config.gmail.max_results == 100
    assert config.gmail.client_secret_file == Path("config/client_secret.json")
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_gmail.py::test_load_config_reads_gmail_section -xvs`
Expected: FAIL，因为 `gmail` 配置解析尚未完整实现。

- [ ] **Step 3: 实现 Gmail 配置解析与样例配置**

```python
# src/beartools/config.py
def _parse_positive_int(value: object, path: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise RuntimeError(f"{path} 必须是正整数")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str):
        parsed = int(value)
        if parsed > 0:
            return parsed
    raise RuntimeError(f"{path} 必须是正整数")


def _parse_gmail_config(settings: _SettingsLike) -> GmailConfig:
    gmail_settings = _as_dict(settings.get("gmail", {}), "gmail")
    return GmailConfig(
        client_secret_file=Path(str(gmail_settings.get("client_secret_file", "config/client_secret.json"))),
        token_file=Path(str(gmail_settings.get("token_file", "config/gmail.token.json"))),
        output_dir=Path(str(gmail_settings.get("output_dir", "email"))),
        default_days=_parse_positive_int(gmail_settings.get("default_days", 3), "gmail.default_days", 3),
        max_results=_parse_positive_int(gmail_settings.get("max_results", 100), "gmail.max_results", 100),
    )
```

```yaml
# config/beartools.yaml.sample
gmail:
  output_dir: email
  default_days: 3
  max_results: 100
```

```yaml
# config/beartools.secrets.yaml.sample
gmail:
  client_secret_file: config/client_secret.json
  token_file: config/gmail.token.json
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_gmail.py::test_load_config_reads_gmail_section -xvs`
Expected: PASS，Gmail 配置可从配置文件正确读出。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/config.py config/beartools.yaml.sample config/beartools.secrets.yaml.sample tests/test_gmail.py
git commit -m "ADD: 增加 gmail 配置解析"
```

### Task 3: Gmail 查询与 100 封截断

**Files:**
- Create: `src/beartools/gmail.py`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: 写 Gmail 查询与截断的失败测试**

```python
from beartools.gmail import GmailMessageSummaryInput, limit_messages


def test_limit_messages_truncates_to_max_results() -> None:
    messages = [
        GmailMessageSummaryInput(
            message_id=str(index),
            subject=f"主题{index}",
            sender="sender@example.com",
            received_at="2026-05-01T10:00:00+08:00",
            body_text="正文",
        )
        for index in range(101)
    ]

    limited, truncated = limit_messages(messages, max_results=100)

    assert len(limited) == 100
    assert truncated is True
```

```python
from beartools.gmail import build_gmail_query


def test_build_gmail_query_uses_inbox_and_days() -> None:
    assert build_gmail_query(3) == "label:inbox newer_than:3d"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_gmail.py::test_limit_messages_truncates_to_max_results tests/test_gmail.py::test_build_gmail_query_uses_inbox_and_days -xvs`
Expected: FAIL，因为 `beartools.gmail` 与相关函数尚不存在。

- [ ] **Step 3: 实现查询语句与截断逻辑**

```python
# src/beartools/gmail.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GmailMessageSummaryInput:
    message_id: str
    subject: str
    sender: str
    received_at: str
    body_text: str


def build_gmail_query(days: int) -> str:
    return f"label:inbox newer_than:{days}d"


def limit_messages(
    messages: list[GmailMessageSummaryInput],
    max_results: int,
) -> tuple[list[GmailMessageSummaryInput], bool]:
    if len(messages) <= max_results:
        return messages, False
    return messages[:max_results], True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_gmail.py::test_limit_messages_truncates_to_max_results tests/test_gmail.py::test_build_gmail_query_uses_inbox_and_days -xvs`
Expected: PASS，查询条件与截断逻辑正确。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/gmail.py tests/test_gmail.py
git commit -m "ADD: 增加 gmail 查询与截断逻辑"
```

### Task 4: Gmail 正文提取与 Markdown 输出

**Files:**
- Modify: `src/beartools/gmail.py`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: 写正文提取和文件输出的失败测试**

```python
from pathlib import Path

from beartools.gmail import extract_body_text, write_summary_markdown


def test_extract_body_text_prefers_text_plain() -> None:
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": "5rWL6K+V5paH5pys"}},
            {"mimeType": "text/html", "body": {"data": "PGI+5rWL6K+VPC9iPg=="}},
        ],
    }

    assert extract_body_text(payload) == "测试文本"


def test_write_summary_markdown_creates_timestamped_file(tmp_path: Path) -> None:
    output_file = write_summary_markdown(
        output_dir=tmp_path,
        fetched_days=3,
        total_count=126,
        processed_count=100,
        summary_text="# 标题\n\n内容",
        truncated=True,
        fetched_at_text="2026-05-01 10:30:00",
        filename_timestamp="2026-05-01_10-30-00",
    )

    assert output_file == tmp_path / "2026-05-01_10-30-00.md"
    content = output_file.read_text(encoding="utf-8")
    assert "处理的邮件个数：100" in content
    assert "抓取天数：3" in content
    assert "超过处理上限，仅处理前 100 封" in content
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_gmail.py::test_extract_body_text_prefers_text_plain tests/test_gmail.py::test_write_summary_markdown_creates_timestamped_file -xvs`
Expected: FAIL，因为正文提取和文件输出尚未实现。

- [ ] **Step 3: 实现正文提取与 Markdown 输出**

```python
# src/beartools/gmail.py
import base64
from pathlib import Path


def _decode_body_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="ignore")


def extract_body_text(payload: dict[str, object]) -> str:
    parts = payload.get("parts")
    if isinstance(parts, list):
        plain_text = _find_body_by_mime_type(parts, "text/plain")
        if plain_text:
            return plain_text
        html_text = _find_body_by_mime_type(parts, "text/html")
        if html_text:
            return _strip_html_tags(html_text)

    body = payload.get("body")
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, str) and data:
            return _decode_body_data(data)
    return ""


def write_summary_markdown(
    *,
    output_dir: Path,
    fetched_days: int,
    total_count: int,
    processed_count: int,
    summary_text: str,
    truncated: bool,
    fetched_at_text: str,
    filename_timestamp: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{filename_timestamp}.md"
    notice = "超过处理上限，仅处理前 100 封" if truncated else ""
    content = "\n".join(
        [
            "# Gmail 邮件摘要",
            "",
            f"- 抓取时间：{fetched_at_text}",
            f"- 抓取天数：{fetched_days}",
            f"- 命中邮件数：{total_count}",
            f"- 处理的邮件个数：{processed_count}",
            *( [f"- 说明：{notice}"] if notice else []),
            "",
            summary_text,
            "",
        ]
    )
    output_file.write_text(content, encoding="utf-8")
    return output_file
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_gmail.py::test_extract_body_text_prefers_text_plain tests/test_gmail.py::test_write_summary_markdown_creates_timestamped_file -xvs`
Expected: PASS，正文提取和输出文件格式符合需求。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/gmail.py tests/test_gmail.py
git commit -m "ADD: 增加 gmail 正文提取与输出"
```

### Task 5: LLM 批量摘要

**Files:**
- Modify: `src/beartools/gmail.py`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: 写批量摘要失败测试**

```python
from beartools.gmail import GmailMessageSummaryInput, summarize_messages


class FakeAgent:
    def run_sync(self, prompt: str) -> object:
        assert "最重要的 10 封邮件" in prompt
        assert "总体概览" in prompt

        class Result:
            output = "## 最重要的 10 封邮件\n\n1. 邮件A\n\n## 总体概览\n\n整体稳定"

        return Result()


def test_summarize_messages_returns_model_output() -> None:
    messages = [
        GmailMessageSummaryInput(
            message_id="1",
            subject="主题A",
            sender="a@example.com",
            received_at="2026-05-01 10:00:00",
            body_text="正文A",
        )
    ]

    summary = summarize_messages(messages, fetched_days=3, agent=FakeAgent())

    assert "最重要的 10 封邮件" in summary
    assert "总体概览" in summary
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_gmail.py::test_summarize_messages_returns_model_output -xvs`
Expected: FAIL，因为批量摘要函数尚未实现。

- [ ] **Step 3: 实现批量摘要函数**

```python
# src/beartools/gmail.py
from pydantic_ai import Agent

from beartools.llm.factory import LLFactory


def _build_summary_prompt(messages: list[GmailMessageSummaryInput], fetched_days: int) -> str:
    lines = [
        f"请总结最近 {fetched_days} 天内抓取到的 Gmail INBOX 邮件。",
        "输出必须包含两个一级部分：最重要的 10 封邮件、总体概览。",
        "最重要的 10 封邮件中，请模型自行判断重要性；如果总邮件数不足 10，则按实际数量输出。",
        "每封邮件请说明主题、发件人、时间、简要摘要和为什么重要。",
        "总体概览请总结本批邮件的主要主题、待处理事项和风险点。",
        "",
    ]
    for index, message in enumerate(messages, start=1):
        lines.extend(
            [
                f"[{index}] 主题：{message.subject}",
                f"发件人：{message.sender}",
                f"时间：{message.received_at}",
                f"正文：{message.body_text}",
                "",
            ]
        )
    return "\n".join(lines)


def summarize_messages(
    messages: list[GmailMessageSummaryInput],
    fetched_days: int,
    agent: Agent[None, str] | object | None = None,
) -> str:
    summary_agent = agent or Agent(model=LLFactory().create(), output_type=str)
    prompt = _build_summary_prompt(messages, fetched_days=fetched_days)
    result = summary_agent.run_sync(prompt)
    return str(result.output)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_gmail.py::test_summarize_messages_returns_model_output -xvs`
Expected: PASS，摘要函数能构造 prompt 并返回模型输出。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/gmail.py tests/test_gmail.py
git commit -m "ADD: 增加 gmail 批量摘要能力"
```

### Task 6: Gmail 抓取编排与命令落地

**Files:**
- Modify: `src/beartools/gmail.py`
- Modify: `src/beartools/commands/gmail/command.py`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: 写抓取编排与 CLI 输出失败测试**

```python
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from beartools.cli import app
from beartools.gmail import GmailFetchResult

runner = CliRunner()


def test_gmail_fetch_command_prints_counts_and_output_path() -> None:
    fetch_result = GmailFetchResult(
        fetched_days=3,
        total_count=126,
        processed_count=100,
        truncated=True,
        summary_text="## 最重要的 10 封邮件\n\n## 总体概览",
        output_file=Path("email/2026-05-01_10-30-00.md"),
    )

    with patch("beartools.commands.gmail.command.fetch_gmail_summary", return_value=fetch_result):
        result = runner.invoke(app, ["gmail", "fetch"])

    assert result.exit_code == 0
    assert "抓取天数: 3" in result.stdout
    assert "处理的邮件个数: 100" in result.stdout
    assert "命中邮件数: 126" in result.stdout
    assert "超过处理上限，仅处理前 100 封" in result.stdout
    assert "输出文件: email/2026-05-01_10-30-00.md" in result.stdout
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_gmail.py::test_gmail_fetch_command_prints_counts_and_output_path -xvs`
Expected: FAIL，因为抓取编排结果结构与命令输出尚未实现。

- [ ] **Step 3: 实现抓取编排结果结构与 CLI 输出**

```python
# src/beartools/gmail.py
@dataclass(slots=True)
class GmailFetchResult:
    fetched_days: int
    total_count: int
    processed_count: int
    truncated: bool
    summary_text: str
    output_file: Path


def fetch_gmail_summary(days: int, max_results: int) -> GmailFetchResult:
    raise NotImplementedError
```

```python
# src/beartools/commands/gmail/command.py
from rich.console import Console

from beartools.config import get_config
from beartools.gmail import GmailFetchResult, fetch_gmail_summary

console = Console()


@gmail_app.command("fetch")
def fetch(
    days: int | None = typer.Option(None, "--days", min=1, help="抓取最近多少天的 INBOX 邮件，默认取配置值"),
    max_results: int | None = typer.Option(None, "--max-results", min=1, help="最多处理多少封邮件，默认取配置值"),
) -> None:
    config = get_config().gmail
    resolved_days = days or config.default_days
    resolved_max_results = max_results or config.max_results
    result = fetch_gmail_summary(days=resolved_days, max_results=resolved_max_results)
    console.print(f"抓取天数: {result.fetched_days}")
    console.print(f"命中邮件数: {result.total_count}")
    console.print(f"处理的邮件个数: {result.processed_count}")
    if result.truncated:
        console.print("超过处理上限，仅处理前 100 封", style="yellow")
    console.print(result.summary_text)
    console.print(f"输出文件: {result.output_file}", style="green")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_gmail.py::test_gmail_fetch_command_prints_counts_and_output_path -xvs`
Expected: PASS，CLI 能正确展示邮件天数、处理个数、截断提示和输出路径。

- [ ] **Step 5: Commit**

```bash
git add src/beartools/gmail.py src/beartools/commands/gmail/command.py tests/test_gmail.py
git commit -m "ADD: 打通 gmail fetch 命令输出"
```

### Task 7: OAuth 与 Gmail API 集成

**Files:**
- Modify: `src/beartools/gmail.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: 写 OAuth 与 Gmail API 编排失败测试**

```python
from pathlib import Path
from unittest.mock import Mock, patch

from beartools.config import GmailConfig
from beartools.gmail import fetch_gmail_summary


def test_fetch_gmail_summary_limits_messages_and_writes_output(tmp_path: Path) -> None:
    gmail_config = GmailConfig(
        client_secret_file=Path("config/client_secret.json"),
        token_file=Path("config/gmail.token.json"),
        output_dir=tmp_path,
        default_days=3,
        max_results=100,
    )
    fake_messages = [
        {
            "id": str(index),
            "payload": {
                "headers": [
                    {"name": "Subject", "value": f"主题{index}"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Thu, 01 May 2026 10:00:00 +0800"},
                ],
                "body": {"data": "5rWL6K+V5paH5pys"},
            },
        }
        for index in range(101)
    ]

    with patch("beartools.gmail.get_config", return_value=Mock(gmail=gmail_config)):
        with patch("beartools.gmail.list_inbox_messages", return_value=fake_messages):
            with patch("beartools.gmail.summarize_messages", return_value="## 最重要的 10 封邮件\n\n## 总体概览"):
                result = fetch_gmail_summary(days=3, max_results=100)

    assert result.total_count == 101
    assert result.processed_count == 100
    assert result.truncated is True
    assert result.output_file.exists()
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_gmail.py::test_fetch_gmail_summary_limits_messages_and_writes_output -xvs`
Expected: FAIL，因为 OAuth/Gmail API 集成和抓取编排尚未完成。

- [ ] **Step 3: 安装并锁定 Gmail API 依赖**

Run: `uv add google-api-python-client google-auth-oauthlib google-auth-httplib2`
Expected: `pyproject.toml` 与 `uv.lock` 更新成功；随后手动把 `pyproject.toml` 中相关版本改成 `==` 精确版本。

- [ ] **Step 4: 实现 OAuth 客户端、Gmail API 调用和抓取总流程**

```python
# src/beartools/gmail.py
from datetime import datetime
from pathlib import Path

from beartools.config import GmailConfig, get_config


def list_inbox_messages(days: int, gmail_config: GmailConfig) -> list[dict[str, object]]:
    service = build_gmail_service(gmail_config)
    query = build_gmail_query(days)
    response = service.users().messages().list(userId="me", q=query).execute()
    items = response.get("messages", [])
    result: list[dict[str, object]] = []
    for item in items:
        message_id = item.get("id")
        if not isinstance(message_id, str):
            continue
        detail = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        result.append(detail)
    return result


def fetch_gmail_summary(days: int, max_results: int) -> GmailFetchResult:
    gmail_config = get_config().gmail
    fetched_at = datetime.now()
    raw_messages = list_inbox_messages(days, gmail_config)
    summary_inputs = [message_detail_to_summary_input(item) for item in raw_messages]
    limited_messages, truncated = limit_messages(summary_inputs, max_results=max_results)
    summary_text = summarize_messages(limited_messages, fetched_days=days)
    output_file = write_summary_markdown(
        output_dir=gmail_config.output_dir,
        fetched_days=days,
        total_count=len(summary_inputs),
        processed_count=len(limited_messages),
        summary_text=summary_text,
        truncated=truncated,
        fetched_at_text=fetched_at.strftime("%Y-%m-%d %H:%M:%S"),
        filename_timestamp=fetched_at.strftime("%Y-%m-%d_%H-%M-%S"),
    )
    return GmailFetchResult(
        fetched_days=days,
        total_count=len(summary_inputs),
        processed_count=len(limited_messages),
        truncated=truncated,
        summary_text=summary_text,
        output_file=output_file,
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_gmail.py::test_fetch_gmail_summary_limits_messages_and_writes_output -xvs`
Expected: PASS，完整流程会在超过 100 封时截断，并写出结果文件。

- [ ] **Step 6: Commit**

```bash
git add src/beartools/gmail.py pyproject.toml uv.lock tests/test_gmail.py
git commit -m "ADD: 集成 gmail oauth 与抓取流程"
```

### Task 8: 全量验证与质量检查

**Files:**
- Modify: `src/beartools/gmail.py`
- Modify: `src/beartools/commands/gmail/command.py`
- Modify: `src/beartools/config.py`
- Modify: `tests/test_gmail.py`

- [ ] **Step 1: 运行 Gmail 相关测试**

Run: `uv run pytest tests/test_gmail.py tests/test_cli_entrypoint.py -xvs`
Expected: PASS，所有 Gmail 新增测试通过。

- [ ] **Step 2: 运行静态检查**

Run: `uv run ruff check src/beartools/gmail.py src/beartools/commands/gmail/command.py src/beartools/config.py tests/test_gmail.py tests/test_cli_entrypoint.py`
Expected: PASS，无 lint 错误。

- [ ] **Step 3: 运行格式检查**

Run: `uv run ruff format src/beartools/gmail.py src/beartools/commands/gmail/command.py src/beartools/config.py tests/test_gmail.py tests/test_cli_entrypoint.py`
Expected: PASS，格式化完成且无异常。

- [ ] **Step 4: 运行类型检查**

Run: `uv run mypy src/beartools tests/test_gmail.py tests/test_cli_entrypoint.py`
Expected: PASS，无类型错误。

- [ ] **Step 5: 运行相关回归测试**

Run: `uv run pytest tests/test_config.py tests/test_fetch.py tests/test_cli_entrypoint.py tests/test_gmail.py -xvs`
Expected: PASS，新功能未破坏现有配置和 CLI 行为。

- [ ] **Step 6: Commit**

```bash
git add src/beartools/gmail.py src/beartools/commands/gmail/command.py src/beartools/config.py tests/test_gmail.py tests/test_cli_entrypoint.py
git commit -m "MOD: 完成 gmail fetch 功能验证"
```

## Self-Review

- Spec coverage: 已覆盖命令结构、默认 `--days`、`INBOX` 查询、100 封截断提示、统一摘要、Top 10、总体概览、输出到 `./email/`、终端输出处理个数与抓取天数、OAuth 首次授权与配置样例。
- Placeholder scan: 未使用 TBD/TODO/“类似前文” 等占位表达；每个代码步骤都给出明确代码片段与命令。
- Type consistency: `GmailConfig`、`GmailMessageSummaryInput`、`GmailFetchResult`、`fetch_gmail_summary()`、`summarize_messages()` 在各任务中的命名保持一致。
