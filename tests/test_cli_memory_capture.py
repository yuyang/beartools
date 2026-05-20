from __future__ import annotations

from datetime import datetime
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
from typing import NoReturn


def test_console_entrypoint_points_to_wrapper() -> None:
    pyproject_text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'beartools = "beartools.cli:_main_wrapper"' in pyproject_text


def test_tee_text_capture_writes_through_and_keeps_copy() -> None:
    from beartools.cli import _TeeTextCapture

    stream = StringIO()
    capture = _TeeTextCapture(stream)

    capture.write("开始\n")
    assert stream.getvalue() == "开始\n"
    assert capture.getvalue() == "开始\n"


def test_wrapper_records_doctor_console_output_to_day_memory(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["BEARTOOLS_MEMORY_ROOT"] = str(tmp_path)
    env["BEARTOOLS_MEMORY_FAKE_SUMMARY"] = "fake doctor summary"
    env["BEARTOOLS_MEMORY_NOW"] = "2026-05-13T09:30:00"

    result = subprocess.run(
        [sys.executable, "-m", "beartools.cli", "doctor"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert "检查总览" in result.stdout
    assert "Usage: doctor" not in result.stdout
    day_text = (tmp_path / "day" / "2026-05-13.md").read_text(encoding="utf-8")
    assert "## 09:30:00 beartools doctor" in day_text
    assert "fake doctor summary" in day_text
    assert "检查总览" in day_text


def test_wrapper_records_help_command_without_llm_summary(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["BEARTOOLS_MEMORY_ROOT"] = str(tmp_path)
    env["BEARTOOLS_MEMORY_FAKE_SUMMARY"] = "fake llm summary should not appear"
    env["BEARTOOLS_MEMORY_NOW"] = "2026-05-13T09:30:00"

    result = subprocess.run(
        [sys.executable, "-m", "beartools.cli", "doctor", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Usage: beartools doctor" in result.stdout
    day_text = (tmp_path / "day" / "2026-05-13.md").read_text(encoding="utf-8")
    assert "## 09:30:00 beartools doctor --help" in day_text
    assert "已输出帮助信息：运行环境健康检查" in day_text
    assert "fake llm summary should not appear" not in day_text


def test_wrapper_records_diary_command_itself(tmp_path: Path) -> None:
    day_dir = tmp_path / "day"
    day_dir.mkdir(parents=True)
    (day_dir / "2026-05-10.md").write_text("## 09:00:00 beartools doctor\n", encoding="utf-8")
    env = os.environ.copy()
    env["BEARTOOLS_MEMORY_ROOT"] = str(tmp_path)
    env["BEARTOOLS_MEMORY_FAKE_SUMMARY"] = "fake command summary"
    env["BEARTOOLS_DAILY_MEMORY_FAKE_SUMMARY"] = "fake daily summary"
    env["BEARTOOLS_MEMORY_NOW"] = "2026-05-13T10:30:00"

    result = subprocess.run(
        [sys.executable, "-m", "beartools.cli", "diary", "summary", "--date", "2026-05-10"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    today_text = (tmp_path / "day" / "2026-05-13.md").read_text(encoding="utf-8")
    assert "beartools diary summary --date 2026-05-10" in today_text
    assert "fake command summary" in today_text


def test_wrapper_formats_missing_subcommand_without_traceback(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["BEARTOOLS_MEMORY_ROOT"] = str(tmp_path)
    env["BEARTOOLS_MEMORY_FAKE_SUMMARY"] = "fake missing command summary"
    env["BEARTOOLS_MEMORY_NOW"] = "2026-05-13T10:30:00"

    result = subprocess.run(
        [sys.executable, "-m", "beartools.cli", "diary"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Error: Missing command." in result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_wrapper_formats_unhandled_exception_without_traceback(monkeypatch, capsys, tmp_path: Path) -> None:
    from beartools import cli

    recorded: dict[str, object] = {}
    logged: list[BaseException] = []

    def fake_app(*, args: list[str], prog_name: str, standalone_mode: bool) -> NoReturn:
        assert args == ["boom"]
        assert prog_name == "beartools"
        assert standalone_mode is False
        raise RuntimeError("底层接口失败")

    def fake_record_command_memory(**kwargs: object) -> None:
        recorded.update(kwargs)

    monkeypatch.setattr(sys, "argv", ["beartools", "boom"])
    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli, "_record_command_memory", fake_record_command_memory)
    monkeypatch.setattr(cli, "_resolve_memory_now", lambda: cli.datetime(2026, 5, 20, 10, 30, 0))
    monkeypatch.setattr(cli, "_log_cli_exception", lambda exc: logged.append(exc))
    monkeypatch.chdir(tmp_path)

    try:
        cli._main_wrapper()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("预期 _main_wrapper 退出")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "错误: 底层接口失败\n"
    assert "Traceback" not in captured.err
    assert len(logged) == 1
    assert isinstance(logged[0], RuntimeError)
    assert recorded["exit_code"] == 1
    assert recorded["stderr_text"] == "错误: 底层接口失败\n"


def test_build_memory_now_from_environment(monkeypatch) -> None:
    from beartools.cli import _resolve_memory_now

    monkeypatch.setenv("BEARTOOLS_MEMORY_NOW", "2026-05-13T11:22:33")

    assert _resolve_memory_now() == datetime(2026, 5, 13, 11, 22, 33)
