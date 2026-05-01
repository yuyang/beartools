"""Gmail 命令与业务测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from beartools.cli import app
from beartools.config import load_config, reset_config

runner = CliRunner()


class ConfigStub:
    def __init__(self, gmail: object) -> None:
        self.gmail = gmail


def _build_fake_message(index: int) -> dict[str, object]:
    headers: list[dict[str, object]] = [
        {"name": "Subject", "value": f"主题{index}"},
        {"name": "From", "value": "sender@example.com"},
        {"name": "Date", "value": "Thu, 01 May 2026 10:00:00 +0800"},
    ]
    payload: dict[str, object] = {
        "headers": headers,
        "body": {"data": "5rWL6K+V5paH5pys"},
    }
    return {
        "id": str(index),
        "payload": payload,
    }


def test_gmail_command_group_is_registered() -> None:
    result = runner.invoke(app, ["gmail", "--help"])

    assert result.exit_code == 0
    assert "fetch" in result.stdout


def test_gmail_fetch_uses_default_days() -> None:
    result = runner.invoke(app, ["gmail", "fetch", "--help"])

    assert result.exit_code == 0
    assert "--days" in result.stdout
    assert "默认" in result.stdout


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


def test_load_config_rejects_invalid_gmail_default_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "beartools.yaml").write_text(
        """
gmail:
  default_days: abc
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    reset_config()

    with pytest.raises(RuntimeError, match="gmail.default_days 必须是正整数"):
        load_config()


def test_limit_messages_truncates_to_max_results() -> None:
    from beartools.gmail import GmailMessageSummaryInput, limit_messages

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


def test_build_gmail_query_uses_inbox_and_days() -> None:
    from beartools.gmail import build_gmail_query

    assert build_gmail_query(3) == "label:inbox newer_than:3d"


def test_extract_body_text_prefers_text_plain() -> None:
    from beartools.gmail import extract_body_text

    parts: list[dict[str, object]] = [
        {"mimeType": "text/plain", "body": {"data": "5rWL6K+V5paH5pys"}},
        {"mimeType": "text/html", "body": {"data": "PGI+5rWL6K+VPC9iPg=="}},
    ]
    payload: dict[str, object] = {
        "mimeType": "multipart/alternative",
        "parts": parts,
    }

    assert extract_body_text(payload) == "测试文本"


def test_extract_body_text_strips_single_part_html() -> None:
    from beartools.gmail import extract_body_text

    payload: dict[str, object] = {
        "mimeType": "text/html",
        "body": {"data": "PGRpdj7mtYvor5XmlofmnKw8L2Rpdj4="},
    }

    assert extract_body_text(payload) == "测试文本"


def test_write_summary_markdown_creates_timestamped_file(tmp_path: Path) -> None:
    from beartools.gmail import write_summary_markdown

    output_file = write_summary_markdown(
        output_dir=tmp_path,
        fetched_days=3,
        total_count=126,
        processed_count=100,
        summary_text="# 标题\n\n内容",
        truncated=True,
        max_results=100,
        fetched_at_text="2026-05-01 10:30:00",
        filename_timestamp="2026-05-01_10-30-00",
    )

    assert output_file == tmp_path / "2026-05-01_10-30-00.md"
    content = output_file.read_text(encoding="utf-8")
    assert "处理的邮件个数：100" in content
    assert "抓取天数：3" in content
    assert "超过处理上限，仅处理前 100 封" in content


def test_write_summary_markdown_uses_dynamic_max_results_notice(tmp_path: Path) -> None:
    from beartools.gmail import write_summary_markdown

    output_file = write_summary_markdown(
        output_dir=tmp_path,
        fetched_days=7,
        total_count=55,
        processed_count=20,
        summary_text="# 标题\n\n内容",
        truncated=True,
        max_results=20,
        fetched_at_text="2026-05-01 10:30:00",
        filename_timestamp="2026-05-01_10-30-01",
    )

    content = output_file.read_text(encoding="utf-8")
    assert "超过处理上限，仅处理前 20 封" in content


class FakeAgent:
    def run_sync(self, prompt: str) -> object:
        assert "最重要的 10 封邮件" in prompt
        assert "总体概览" in prompt

        class Result:
            output = "## 最重要的 10 封邮件\n\n1. 邮件A\n\n## 总体概览\n\n整体稳定"

        return Result()


def test_summarize_messages_returns_model_output() -> None:
    from beartools.gmail import GmailMessageSummaryInput, summarize_messages

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


def test_gmail_fetch_command_prints_counts_and_output_path() -> None:
    from beartools.gmail import GmailFetchResult

    fetch_result = GmailFetchResult(
        fetched_days=3,
        total_count=126,
        processed_count=100,
        truncated=True,
        max_results=100,
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


def test_gmail_fetch_command_uses_dynamic_max_results_notice() -> None:
    from beartools.gmail import GmailFetchResult

    fetch_result = GmailFetchResult(
        fetched_days=3,
        total_count=55,
        processed_count=20,
        truncated=True,
        max_results=20,
        summary_text="## 最重要的 10 封邮件\n\n## 总体概览",
        output_file=Path("email/2026-05-01_10-30-00.md"),
    )

    with patch("beartools.commands.gmail.command.fetch_gmail_summary", return_value=fetch_result):
        result = runner.invoke(app, ["gmail", "fetch"])

    assert result.exit_code == 0
    assert "超过处理上限，仅处理前 20 封" in result.stdout


def test_gmail_fetch_command_logs_timeout_and_prints_brief_message() -> None:
    with patch("beartools.commands.gmail.command.fetch_gmail_summary", side_effect=TimeoutError("timed out")):
        with patch("beartools.commands.gmail.command.logger", new=Mock()):
            result = runner.invoke(app, ["gmail", "fetch"])

    assert result.exit_code == 1
    assert "Gmail 抓取超时，请稍后重试" in result.stdout
    assert "Traceback" not in result.stdout


def test_fetch_gmail_summary_limits_messages_and_writes_output(tmp_path: Path) -> None:
    from beartools.config import GmailConfig
    from beartools.gmail import fetch_gmail_summary

    gmail_config = GmailConfig(
        client_secret_file=Path("config/client_secret.json"),
        token_file=Path("config/gmail.token.json"),
        output_dir=tmp_path,
        default_days=3,
        max_results=100,
    )
    fake_messages = [_build_fake_message(index) for index in range(101)]

    with patch("beartools.gmail.get_config", return_value=ConfigStub(gmail_config)):
        with patch("beartools.gmail.list_inbox_messages", return_value=fake_messages):
            with patch("beartools.gmail.summarize_messages", return_value="## 最重要的 10 封邮件\n\n## 总体概览"):
                result = fetch_gmail_summary(days=3, max_results=100)

    assert result.total_count == 101
    assert result.processed_count == 100
    assert result.truncated is True
    assert result.output_file.exists()


def test_list_inbox_messages_reads_multiple_pages_until_max_results() -> None:
    from beartools.config import GmailConfig
    from beartools.gmail import list_inbox_messages

    gmail_config = GmailConfig(
        client_secret_file=Path("config/client_secret.json"),
        token_file=Path("config/gmail.token.json"),
        output_dir=Path("email"),
        default_days=3,
        max_results=150,
    )

    class FakeMessagesApi:
        def __init__(self) -> None:
            self.list_calls: list[dict[str, object]] = []

        def list(self, *, userId: str, q: str, maxResults: int, pageToken: str | None = None) -> object:
            self.list_calls.append({"userId": userId, "q": q, "maxResults": maxResults, "pageToken": pageToken or ""})

            class ListRequest:
                def execute(inner_self) -> dict[str, object]:
                    del inner_self
                    if pageToken is None:
                        return {
                            "messages": [{"id": str(index)} for index in range(100)],
                            "nextPageToken": "page-2",
                        }
                    return {"messages": [{"id": str(index)} for index in range(100, 150)]}

            return ListRequest()

        def get(self, *, userId: str, id: str, format: str) -> object:
            class GetRequest:
                def execute(inner_self) -> dict[str, object]:
                    del inner_self
                    return {"id": id, "payload": {"headers": [], "body": {"data": ""}}}

            assert userId == "me"
            assert format == "full"
            return GetRequest()

    fake_messages_api = FakeMessagesApi()

    class FakeUsersApi:
        def messages(self) -> FakeMessagesApi:
            return fake_messages_api

    class FakeService:
        def users(self) -> FakeUsersApi:
            return FakeUsersApi()

    with patch("beartools.gmail.build_gmail_service", return_value=FakeService()):
        messages = list_inbox_messages(days=3, gmail_config=gmail_config, max_results=150)

    assert len(messages) == 150
    assert fake_messages_api.list_calls[0]["pageToken"] == ""
    assert fake_messages_api.list_calls[1]["pageToken"] == "page-2"
