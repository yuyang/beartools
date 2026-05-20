from __future__ import annotations

from datetime import date
from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

from beartools.cli import app


def test_diary_summary_command_writes_summary(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    day_file = tmp_path / "day" / "2026-05-10.md"
    day_file.parent.mkdir(parents=True)
    day_file.write_text("## 09:00:00 beartools doctor\n\n- 结果：doctor 已运行\n", encoding="utf-8")
    monkeypatch.setenv("BEARTOOLS_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "beartools.commands.diary.command.create_daily_summarizer",
        lambda: _FakeDailySummarizer("large summary"),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["diary", "summary", "--date", "2026-05-10"])

    assert result.exit_code == 0
    assert "summary/2026-05-10.md" in result.stdout
    assert "large summary" in (tmp_path / "summary" / "2026-05-10.md").read_text(encoding="utf-8")


def test_diary_summary_command_defaults_to_yesterday(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    day_file = tmp_path / "day" / "2026-05-12.md"
    day_file.parent.mkdir(parents=True)
    day_file.write_text("## 09:00:00 beartools doctor\n\n- 结果：doctor 已运行\n", encoding="utf-8")
    monkeypatch.setenv("BEARTOOLS_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr("beartools.commands.diary.command.today", lambda: date(2026, 5, 13))
    monkeypatch.setattr(
        "beartools.commands.diary.command.create_daily_summarizer",
        lambda: _FakeDailySummarizer("yesterday summary"),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["diary", "summary"])

    assert result.exit_code == 0
    assert "summary/2026-05-12.md" in result.stdout
    assert "yesterday summary" in (tmp_path / "summary" / "2026-05-12.md").read_text(encoding="utf-8")


def test_diary_summary_command_rejects_today_or_future_date(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BEARTOOLS_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr("beartools.commands.diary.command.today", lambda: date(2026, 5, 13))
    runner = CliRunner()

    today_result = runner.invoke(app, ["diary", "summary", "--date", "2026-05-13"])
    future_result = runner.invoke(app, ["diary", "summary", "--date", "2026-05-14"])

    assert today_result.exit_code == 1
    assert "不能处理今天或未来日期" in today_result.stdout
    assert future_result.exit_code == 1
    assert "不能处理今天或未来日期" in future_result.stdout


def test_diary_summary_command_errors_when_day_missing(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BEARTOOLS_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "beartools.commands.diary.command.create_daily_summarizer",
        lambda: _FakeDailySummarizer("unused"),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["diary", "summary", "--date", "2026-05-10"])

    assert result.exit_code == 1
    assert "day 记忆不存在" in result.stdout


def test_diary_append_command_defaults_to_recent_30_days_and_skips_existing_summary(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    day_dir = tmp_path / "day"
    day_dir.mkdir(parents=True)
    (day_dir / "2026-04-12.md").write_text("outside range", encoding="utf-8")
    (day_dir / "2026-04-13.md").write_text("range start", encoding="utf-8")
    (day_dir / "2026-05-10.md").write_text("doctor day", encoding="utf-8")
    (day_dir / "2026-05-12.md").write_text("diary day", encoding="utf-8")
    (day_dir / "2026-05-13.md").write_text("today day", encoding="utf-8")
    summary_dir = tmp_path / "summary"
    summary_dir.mkdir(parents=True)
    (summary_dir / "2026-05-12.md").write_text("保留旧 summary", encoding="utf-8")
    monkeypatch.setenv("BEARTOOLS_MEMORY_ROOT", str(tmp_path))
    monkeypatch.setattr("beartools.commands.diary.command.today", lambda: date(2026, 5, 13))
    monkeypatch.setattr(
        "beartools.commands.diary.command.create_daily_summarizer",
        lambda: _FakeDailySummarizer("补齐 summary"),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["diary", "append"])

    assert result.exit_code == 0
    assert "补齐 2 天" in result.stdout
    assert "补齐 summary" in (summary_dir / "2026-04-13.md").read_text(encoding="utf-8")
    assert "补齐 summary" in (summary_dir / "2026-05-10.md").read_text(encoding="utf-8")
    assert not (summary_dir / "2026-04-12.md").exists()
    assert (summary_dir / "2026-05-12.md").read_text(encoding="utf-8") == "保留旧 summary"
    assert not (summary_dir / "2026-05-13.md").exists()


def test_diary_append_command_rejects_month_option(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("BEARTOOLS_MEMORY_ROOT", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(app, ["diary", "append", "--month", "2026/05"])

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)


class _FakeDailySummarizer:
    def __init__(self, summary: str) -> None:
        self.summary = summary

    def summarize_day(self, day_content: str) -> str:
        return self.summary
