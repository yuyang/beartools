from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys


def test_console_entrypoint_points_to_wrapper() -> None:
    pyproject_text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'beartools = "beartools.cli:_main_wrapper"' in pyproject_text


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


def test_build_memory_now_from_environment(monkeypatch) -> None:
    from beartools.cli import _resolve_memory_now

    monkeypatch.setenv("BEARTOOLS_MEMORY_NOW", "2026-05-13T11:22:33")

    assert _resolve_memory_now() == datetime(2026, 5, 13, 11, 22, 33)
