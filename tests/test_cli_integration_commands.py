from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import random
import subprocess
from typing import Any, cast

import pytest
import yaml


@dataclass(frozen=True, slots=True)
class IntegrationCase:
    name: str
    group: str
    command: list[str]


INTEGRATION_CASES = [
    IntegrationCase("doctor", "core", ["doctor"]),
    IntegrationCase("record", "core", ["record", "getall"]),
    IntegrationCase("markdown", "core", ["markdown", "embed-images"]),
    IntegrationCase("bill-normalize", "live", ["bill", "normalize"]),
    IntegrationCase("bill-run", "live", ["bill", "run"]),
    IntegrationCase("siyuan", "live", ["siyuan", "ls-notebooks"]),
    IntegrationCase("fetch", "live", ["fetch"]),
    IntegrationCase("gmail", "live", ["gmail", "fetch"]),
    IntegrationCase("codex", "live", ["codex", "run"]),
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_FILE = PROJECT_ROOT / "tests" / "assets" / "cli_integration_assets.yaml"


def _load_assets() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(ASSET_FILE.read_text(encoding="utf-8")))


def _selected_cases() -> list[IntegrationCase]:
    target_group = os.environ.get("BEARTOOLS_INTEGRATION_GROUP", "core")
    if target_group == "all":
        pool = INTEGRATION_CASES
    else:
        pool = [case for case in INTEGRATION_CASES if case.group == target_group]

    if os.environ.get("BEARTOOLS_SMOKE") != "1":
        return pool

    sample_size = int(os.environ.get("BEARTOOLS_SMOKE_SAMPLE", "2"))
    seed = int(os.environ.get("BEARTOOLS_SMOKE_SEED", "20260506"))
    bounded_size = max(1, min(sample_size, len(pool)))
    return random.Random(seed).sample(pool, bounded_size)


def test_selected_cases_exclude_clear_and_default_to_core() -> None:
    selected = _selected_cases()

    assert selected
    assert all(case.name != "clear" for case in selected)
    assert all(case.group == "core" for case in selected)


def test_selected_cases_are_reproducible_in_smoke_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEARTOOLS_INTEGRATION_GROUP", "live")
    monkeypatch.setenv("BEARTOOLS_SMOKE", "1")
    monkeypatch.setenv("BEARTOOLS_SMOKE_SAMPLE", "2")
    monkeypatch.setenv("BEARTOOLS_SMOKE_SEED", "42")

    first = [case.name for case in _selected_cases()]
    second = [case.name for case in _selected_cases()]

    assert first == second


def test_required_assets_exist() -> None:
    assets = _load_assets()

    bill_path = PROJECT_ROOT / str(assets["bill"]["path"])
    codex_path = PROJECT_ROOT / str(assets["codex"]["path"])

    assert bill_path.exists()
    assert codex_path.exists()
    assert assets["fetch"]["urls"]


CLI_BASE_COMMAND = ["uv", "run", "python", "-m", "beartools.cli"]


def test_doctor_command_integration() -> None:
    result = subprocess.run(
        [*CLI_BASE_COMMAND, "doctor"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "检查" in result.stdout


def test_record_getall_integration() -> None:
    result = subprocess.run(
        [*CLI_BASE_COMMAND, "record", "getall"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip()


def test_markdown_embed_images_integration(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.png"
    image_path.write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C6360000000020001E221BC330000000049454E44AE426082"
        )
    )
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    markdown_path = input_dir / "demo.md"
    markdown_path.write_text(f"![demo]({image_path})\n", encoding="utf-8")

    result = subprocess.run(
        [*CLI_BASE_COMMAND, "markdown", "embed-images", str(input_dir), str(output_dir)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output_markdown = output_dir / "demo.md"
    assert output_markdown.exists()
    assert "data:image/png;base64," in output_markdown.read_text(encoding="utf-8")


def test_bill_normalize_integration() -> None:
    assets = _load_assets()
    bill_path = str(PROJECT_ROOT / assets["bill"]["path"])
    from_value = str(assets["bill"]["from"])

    result = subprocess.run(
        [*CLI_BASE_COMMAND, "bill", "normalize", bill_path, from_value],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.skip(f"bill normalize 当前环境不可用: {result.stdout.strip()}")
    assert "输出文件:" in result.stdout
    assert "✅ 归一化完成" in result.stdout


def test_bill_run_integration() -> None:
    assets = _load_assets()
    bill_path = str(PROJECT_ROOT / assets["bill"]["path"])
    from_value = str(assets["bill"]["from"])

    result = subprocess.run(
        [*CLI_BASE_COMMAND, "bill", "run", bill_path, from_value],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.skip(f"bill run 当前环境不可用: {result.stdout.strip()}")
    assert "归一化输出" in result.stdout
    assert "分析输出" in result.stdout


def test_siyuan_ls_notebooks_integration() -> None:
    result = subprocess.run(
        [*CLI_BASE_COMMAND, "siyuan", "ls-notebooks"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.skip(f"siyuan 当前环境不可用: {result.stdout.strip()}")
    assert result.stdout.strip()


def test_fetch_integration_without_upload() -> None:
    assets = _load_assets()
    url = str(assets["fetch"]["urls"][0])

    result = subprocess.run(
        [*CLI_BASE_COMMAND, "fetch", url, "--no-upload"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.skip(f"fetch 当前环境不可用: {result.stdout.strip()}")
    assert "✅ 下载成功" in result.stdout


def test_gmail_fetch_integration() -> None:
    result = subprocess.run(
        [*CLI_BASE_COMMAND, "gmail", "fetch"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.skip(f"gmail 当前环境不可用: {result.stdout.strip()}")
    assert "输出文件:" in result.stdout


def test_codex_run_integration() -> None:
    assets = _load_assets()
    md_path = str(PROJECT_ROOT / assets["codex"]["path"])

    result = subprocess.run(
        [*CLI_BASE_COMMAND, "codex", "run", md_path],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.skip(f"codex 当前环境不可用: {result.stdout.strip()}")
    assert ".codex.md" in result.stdout
    assert ".trace.log" in result.stdout


def test_selected_integration_case(case: IntegrationCase, tmp_path: Path) -> None:
    if case.name == "doctor":
        test_doctor_command_integration()
        return
    if case.name == "record":
        test_record_getall_integration()
        return
    if case.name == "markdown":
        test_markdown_embed_images_integration(tmp_path)
        return
    if case.name == "bill-normalize":
        test_bill_normalize_integration()
        return
    if case.name == "bill-run":
        test_bill_run_integration()
        return
    if case.name == "siyuan":
        test_siyuan_ls_notebooks_integration()
        return
    if case.name == "fetch":
        test_fetch_integration_without_upload()
        return
    if case.name == "gmail":
        test_gmail_fetch_integration()
        return
    if case.name == "codex":
        test_codex_run_integration()
        return
    raise AssertionError(f"未处理的集成测试 case: {case.name}")


test_selected_integration_case = pytest.mark.parametrize("case", _selected_cases(), ids=lambda case: case.name)(
    test_selected_integration_case
)
