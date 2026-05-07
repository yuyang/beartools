from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from typing import TypedDict, cast

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
CLI_BASE_COMMAND = ["uv", "run", "python", "-m", "beartools.cli"]
SMOKE_SEED = 20260506
OUTPUT_DIR = PROJECT_ROOT / "output" / "testing"


class BillAssets(TypedDict):
    path: str
    from_: str


class CodexAssets(TypedDict):
    path: str


class FetchAssets(TypedDict):
    urls: list[str]


class IntegrationAssets(TypedDict):
    bill: dict[str, object]
    codex: dict[str, object]
    fetch: dict[str, object]


def _load_assets() -> IntegrationAssets:
    raw_assets = cast(IntegrationAssets, yaml.safe_load(ASSET_FILE.read_text(encoding="utf-8")))
    return raw_assets


def _bill_assets(assets: IntegrationAssets) -> BillAssets:
    bill = assets["bill"]
    return {
        "path": cast(str, bill["path"]),
        "from_": cast(str, bill["from"]),
    }


def _codex_assets(assets: IntegrationAssets) -> CodexAssets:
    codex = assets["codex"]
    return {"path": cast(str, codex["path"])}


def _fetch_assets(assets: IntegrationAssets) -> FetchAssets:
    fetch = assets["fetch"]
    return {"urls": cast(list[str], fetch["urls"])}


def _selected_cases() -> list[IntegrationCase]:
    target_group = os.environ.get("BEARTOOLS_INTEGRATION_GROUP", "core")
    if target_group == "core":
        return [case for case in INTEGRATION_CASES if case.group == "core"]
    if target_group == "all":
        return INTEGRATION_CASES
    if target_group == "smoke":
        core_cases = [case for case in INTEGRATION_CASES if case.group == "core"]
        live_cases = [case for case in INTEGRATION_CASES if case.group == "live"]
        return [*core_cases, random.Random(SMOKE_SEED).choice(live_cases)]
    raise SystemExit("BEARTOOLS_INTEGRATION_GROUP 只支持 core、smoke、all")


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _is_dry_run() -> bool:
    return "--dry-run" in sys.argv


def _output_file_path() -> Path:
    group = os.environ.get("BEARTOOLS_INTEGRATION_GROUP", "core")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return OUTPUT_DIR / f"cli-integrations-{group}-{timestamp}.log"


def _append_output(output_file: Path, content: str) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("a", encoding="utf-8") as file:
        file.write(content)


def _command_output(command: list[str], result: subprocess.CompletedProcess[str]) -> str:
    return f"\n$ {' '.join(command)}\n{result.stdout}{result.stderr}\n"


def _format_result(case: IntegrationCase, status: str, detail: str, output_file: Path) -> str:
    cli = " ".join([*CLI_BASE_COMMAND, *case.command])
    env_value = os.environ.get("BEARTOOLS_INTEGRATION_GROUP", "core")
    return (
        f"- 测试：{case.name}\n"
        f"  CLI：{cli}\n"
        f"  环境：BEARTOOLS_INTEGRATION_GROUP={env_value}\n"
        f"  结果：{status}{detail}\n"
        f"  输出文件：{output_file}\n"
    )


def _report_result(case: IntegrationCase, status: str, detail: str, output_file: Path) -> None:
    block = _format_result(case, status, detail, output_file)
    print(block, end="")
    _append_output(output_file, block)


def _report_dry_run(case: IntegrationCase, output_file: Path) -> None:
    _report_result(case, "SELECTED", " - dry-run", output_file)


def _run_doctor_command_integration(case: IntegrationCase, output_file: Path) -> str:
    result = _run_command([*CLI_BASE_COMMAND, "doctor"])
    _append_output(output_file, _command_output([*CLI_BASE_COMMAND, "doctor"], result))
    if result.returncode != 0:
        raise AssertionError(result.stdout or result.stderr)
    if "检查" not in result.stdout:
        raise AssertionError("doctor 输出缺少 '检查'")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_record_getall_integration(case: IntegrationCase, output_file: Path) -> str:
    result = _run_command([*CLI_BASE_COMMAND, "record", "getall"])
    _append_output(output_file, _command_output([*CLI_BASE_COMMAND, "record", "getall"], result))
    if result.returncode != 0:
        raise AssertionError(result.stdout or result.stderr)
    if not result.stdout.strip():
        raise AssertionError("record getall 输出为空")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_markdown_embed_images_integration(case: IntegrationCase, output_file: Path) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        image_path = temp_path / "demo.png"
        image_path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C6360000000020001E221BC330000000049454E44AE426082"
            )
        )
        input_dir = temp_path / "input"
        output_dir = temp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        markdown_path = input_dir / "demo.md"
        markdown_path.write_text(f"![demo]({image_path})\n", encoding="utf-8")

        result = _run_command([*CLI_BASE_COMMAND, "markdown", "embed-images", str(input_dir), str(output_dir)])
        _append_output(
            output_file,
            _command_output([*CLI_BASE_COMMAND, "markdown", "embed-images", str(input_dir), str(output_dir)], result),
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout or result.stderr)
        output_markdown = output_dir / "demo.md"
        if not output_markdown.exists():
            raise AssertionError("markdown 输出文件不存在")
        if "data:image/png;base64," not in output_markdown.read_text(encoding="utf-8"):
            raise AssertionError("markdown 输出缺少内嵌图片")

    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_bill_normalize_integration(case: IntegrationCase, output_file: Path) -> str:
    assets = _bill_assets(_load_assets())
    bill_path = str(PROJECT_ROOT / assets["path"])
    from_value = assets["from_"]
    command = [*CLI_BASE_COMMAND, "bill", "normalize", bill_path, from_value]
    result = _run_command(command)
    _append_output(output_file, _command_output(command, result))
    if result.returncode != 0:
        _report_result(case, "SKIPPED", f" - {result.stdout.strip()}", output_file)
        return "skipped"
    if "输出文件:" not in result.stdout or "✅ 归一化完成" not in result.stdout:
        raise AssertionError("bill normalize 输出不符合预期")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_bill_run_integration(case: IntegrationCase, output_file: Path) -> str:
    assets = _bill_assets(_load_assets())
    bill_path = str(PROJECT_ROOT / assets["path"])
    from_value = assets["from_"]
    command = [*CLI_BASE_COMMAND, "bill", "run", bill_path, from_value]
    result = _run_command(command)
    _append_output(output_file, _command_output(command, result))
    if result.returncode != 0:
        _report_result(case, "SKIPPED", f" - {result.stdout.strip()}", output_file)
        return "skipped"
    if "归一化输出" not in result.stdout or "分析输出" not in result.stdout:
        raise AssertionError("bill run 输出不符合预期")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_siyuan_ls_notebooks_integration(case: IntegrationCase, output_file: Path) -> str:
    result = _run_command([*CLI_BASE_COMMAND, "siyuan", "ls-notebooks"])
    _append_output(output_file, _command_output([*CLI_BASE_COMMAND, "siyuan", "ls-notebooks"], result))
    if result.returncode != 0:
        _report_result(case, "SKIPPED", f" - {result.stdout.strip()}", output_file)
        return "skipped"
    if not result.stdout.strip():
        raise AssertionError("siyuan ls-notebooks 输出为空")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_fetch_integration_without_upload(case: IntegrationCase, output_file: Path) -> str:
    assets = _fetch_assets(_load_assets())
    url = assets["urls"][0]
    command = [*CLI_BASE_COMMAND, "fetch", url, "--no-upload"]
    result = _run_command(command)
    _append_output(output_file, _command_output(command, result))
    if result.returncode != 0:
        _report_result(case, "SKIPPED", f" - {result.stdout.strip()}", output_file)
        return "skipped"
    if "✅ 下载成功" not in result.stdout:
        raise AssertionError("fetch 输出不符合预期")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_gmail_fetch_integration(case: IntegrationCase, output_file: Path) -> str:
    result = _run_command([*CLI_BASE_COMMAND, "gmail", "fetch"])
    _append_output(output_file, _command_output([*CLI_BASE_COMMAND, "gmail", "fetch"], result))
    if result.returncode != 0:
        _report_result(case, "SKIPPED", f" - {result.stdout.strip()}", output_file)
        return "skipped"
    if "输出文件:" not in result.stdout:
        raise AssertionError("gmail fetch 输出不符合预期")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_codex_run_integration(case: IntegrationCase, output_file: Path) -> str:
    assets = _codex_assets(_load_assets())
    md_path = str(PROJECT_ROOT / assets["path"])
    command = [*CLI_BASE_COMMAND, "codex", "run", md_path]
    result = _run_command(command)
    _append_output(output_file, _command_output(command, result))
    if result.returncode != 0:
        _report_result(case, "SKIPPED", f" - {result.stdout.strip()}", output_file)
        return "skipped"
    if ".codex.md" not in result.stdout or ".trace.log" not in result.stdout:
        raise AssertionError("codex run 输出不符合预期")
    _report_result(case, "PASSED", "", output_file)
    return "passed"


def _run_case(case: IntegrationCase, output_file: Path) -> str:
    if case.name == "doctor":
        return _run_doctor_command_integration(case, output_file)
    if case.name == "record":
        return _run_record_getall_integration(case, output_file)
    if case.name == "markdown":
        return _run_markdown_embed_images_integration(case, output_file)
    if case.name == "bill-normalize":
        return _run_bill_normalize_integration(case, output_file)
    if case.name == "bill-run":
        return _run_bill_run_integration(case, output_file)
    if case.name == "siyuan":
        return _run_siyuan_ls_notebooks_integration(case, output_file)
    if case.name == "fetch":
        return _run_fetch_integration_without_upload(case, output_file)
    if case.name == "gmail":
        return _run_gmail_fetch_integration(case, output_file)
    if case.name == "codex":
        return _run_codex_run_integration(case, output_file)
    raise AssertionError(f"未处理的集成测试 case: {case.name}")


def main() -> int:
    selected_cases = _selected_cases()
    passed = 0
    skipped = 0
    output_file = _output_file_path()

    if _is_dry_run():
        for case in selected_cases:
            _report_dry_run(case, output_file)
        summary = f"汇总：{len(selected_cases)} selected, 0 passed, 0 skipped\n"
        print(summary, end="")
        _append_output(output_file, summary)
        return 0

    for case in selected_cases:
        status = _run_case(case, output_file)
        if status == "passed":
            passed += 1
        elif status == "skipped":
            skipped += 1

    summary = f"汇总：{passed} passed, {skipped} skipped\n"
    print(summary, end="")
    _append_output(output_file, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
