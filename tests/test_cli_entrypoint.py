from __future__ import annotations

from pathlib import Path
import subprocess


def test_uv_run_can_resolve_beartools_entrypoint() -> None:
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        ["uv", "run", "python", "-c", "import shutil; path = shutil.which('beartools'); print(path or '')"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip().endswith("beartools")


def test_cli_registers_gmail_group() -> None:
    from typer.testing import CliRunner

    from beartools.cli import app

    runner = CliRunner()

    result = runner.invoke(app, ["gmail", "--help"])

    assert result.exit_code == 0
    assert "fetch" in result.stdout


def test_cli_registers_codex_group() -> None:
    from typer.testing import CliRunner

    from beartools.cli import app

    runner = CliRunner()

    result = runner.invoke(app, ["codex", "--help"])

    assert result.exit_code == 0
    assert "run" in result.stdout
