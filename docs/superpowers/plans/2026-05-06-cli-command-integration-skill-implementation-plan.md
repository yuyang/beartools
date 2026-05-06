# CLI Command Integration Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 beartools 增加一个 `testing-cli-integrations` skill，并补一组基于 `pytest` 的真实 CLI 集成测试，使用真实配置与真实输入，按 `core/live` 分组覆盖除 `clear` 外的所有顶层命令。

**Architecture:** 新增一个独立的 pytest 集成测试文件，集中维护 `doctor/record/markdown/siyuan/fetch/gmail/codex/bill` 的最小真实执行路径，通过环境变量控制 `core/live/all` 与 `full/smoke` 的 case 选择。其中 `bill` 因真实链路依赖外部 LLM 能力，归入 `live` 组。skill 文档与 assets 索引只负责说明什么时候使用、需要什么真实资产、如何执行以及哪些命令受网络/凭据/本地服务影响。

`live` 组测试需要真实执行；但若环境不满足（例如思源未启动、Gmail 凭据失效、上游 LLM 兼容性异常），测试应 `skip` 并输出原因，而不是伪造成功。

**Tech Stack:** Python 3.13、pytest、subprocess、标准库 `os`/`random`/`pathlib`/`tempfile`、Markdown 文档

---

### Task 1: 先补真实集成 case 选择逻辑的失败测试

**Files:**
- Create: `tests/test_cli_integration_commands.py`
- Reference: `src/beartools/cli.py`
- Reference: `docs/superpowers/specs/2026-05-06-cli-command-integration-skill-design.md`

- [ ] **Step 1: 写分组清单与 smoke 选择器的失败测试**

```python
from __future__ import annotations

from dataclasses import dataclass
import os
import random


@dataclass(frozen=True, slots=True)
class IntegrationCase:
    name: str
    group: str
    command: list[str]


INTEGRATION_CASES = [
    IntegrationCase("doctor", "core", ["doctor"]),
    IntegrationCase("record", "core", ["record", "getall"]),
    IntegrationCase("markdown", "core", ["markdown", "embed-images"]),
    IntegrationCase("bill-normalize", "core", ["bill", "normalize"]),
    IntegrationCase("bill-run", "core", ["bill", "run"]),
    IntegrationCase("siyuan", "live", ["siyuan", "ls-notebooks"]),
    IntegrationCase("fetch", "live", ["fetch"]),
    IntegrationCase("gmail", "live", ["gmail", "fetch"]),
    IntegrationCase("codex", "live", ["codex", "run"]),
]


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
```

- [ ] **Step 2: 运行单测，确认在新文件不存在时失败**

Run: `uv run pytest tests/test_cli_integration_commands.py::test_selected_cases_exclude_clear_and_default_to_core -v`
Expected: FAIL，提示 `tests/test_cli_integration_commands.py` 不存在

- [ ] **Step 3: 写 smoke 可复现性的失败测试**

```python
def test_selected_cases_are_reproducible_in_smoke_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEARTOOLS_INTEGRATION_GROUP", "live")
    monkeypatch.setenv("BEARTOOLS_SMOKE", "1")
    monkeypatch.setenv("BEARTOOLS_SMOKE_SAMPLE", "2")
    monkeypatch.setenv("BEARTOOLS_SMOKE_SEED", "42")

    first = [case.name for case in _selected_cases()]
    second = [case.name for case in _selected_cases()]

    assert first == second
```

- [ ] **Step 4: 运行单测，确认 smoke 逻辑也处于红灯状态**

Run: `uv run pytest tests/test_cli_integration_commands.py::test_selected_cases_are_reproducible_in_smoke_mode -v`
Expected: FAIL，提示测试文件或目标函数不存在

### Task 2: 实现集成测试骨架与真实资产索引

**Files:**
- Create: `tests/test_cli_integration_commands.py`
- Create: `tests/assets/bill/jd-220.csv`
- Create: `tests/assets/codex/m1.md`
- Create: `tests/assets/cli_integration_assets.yaml`

- [ ] **Step 1: 复制真实 bill 与 codex 输入文件到仓库测试资产目录**

执行内容：

- 将 `/Users/liuyy/Documents/个人/结算/2601/京东交易流水(申请时间2026年01月09日22时53分47秒)_220.csv` 复制为 `tests/assets/bill/jd-220.csv`
- 将 `input/m1.md` 复制为 `tests/assets/codex/m1.md`

完成后检查：

- `tests/assets/bill/jd-220.csv` 存在
- `tests/assets/codex/m1.md` 存在

- [ ] **Step 2: 写固定资产索引文件**

```yaml
bill:
  path: "tests/assets/bill/jd-220.csv"
  from: "yy"
  source: "京东"

codex:
  path: "tests/assets/codex/m1.md"

fetch:
  urls:
    - "https://mp.weixin.qq.com/s/Jac9uhA6zE1OsIYDGjr9-g"
    - "https://mp.weixin.qq.com/s/Iu9g7Ol8jLgtXu18QxMwOg"
```

- [ ] **Step 3: 在测试文件中实现资产加载与 case 选择器**

```python
from pathlib import Path
import subprocess
import tempfile

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_BASE_COMMAND = ["uv", "run", "python", "-m", "beartools.cli"]
ASSET_FILE = PROJECT_ROOT / "tests" / "assets" / "cli_integration_assets.yaml"


def _load_assets() -> dict[str, object]:
    return yaml.safe_load(ASSET_FILE.read_text(encoding="utf-8"))
```

- [ ] **Step 4: 运行选择器测试，确认转绿**

Run: `uv run pytest tests/test_cli_integration_commands.py::test_selected_cases_exclude_clear_and_default_to_core tests/test_cli_integration_commands.py::test_selected_cases_are_reproducible_in_smoke_mode -v`
Expected: PASS

- [ ] **Step 5: 加一个资产存在性校验测试**

```python
def test_required_assets_exist() -> None:
    assets = _load_assets()

    bill_path = PROJECT_ROOT / str(assets["bill"]["path"])
    codex_path = PROJECT_ROOT / str(assets["codex"]["path"])

    assert bill_path.exists()
    assert codex_path.exists()
    assert assets["fetch"]["urls"]
```

- [ ] **Step 6: 运行资产校验测试，确认路径与输入都有效**

Run: `uv run pytest tests/test_cli_integration_commands.py::test_required_assets_exist -v`
Expected: PASS

### Task 3: 先实现 core 组真实集成测试

**Files:**
- Modify: `tests/test_cli_integration_commands.py`
- Reference: `src/beartools/cli.py`

- [ ] **Step 1: 写 `doctor` 真实集成测试**

```python
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
```

- [ ] **Step 2: 写 `record getall` 真实集成测试**

```python
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
```

- [ ] **Step 3: 写 `markdown embed-images` 真实集成测试**

```python
def test_markdown_embed_images_integration(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.png"
    image_path.write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C6360000000020001E221BC330000000049454E44AE426082"
        )
    )
    markdown_path = tmp_path / "demo.md"
    markdown_path.write_text(f"![demo]({image_path.name})\n", encoding="utf-8")

    result = subprocess.run(
        [*CLI_BASE_COMMAND, "markdown", "embed-images", str(markdown_path)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "data:image/png;base64," in markdown_path.read_text(encoding="utf-8")
```

- [ ] **Step 4: 运行 core 组测试，确认真实链路可用**

Run: `BEARTOOLS_INTEGRATION_GROUP=core uv run pytest tests/test_cli_integration_commands.py -v`
Expected: PASS，至少覆盖 `doctor/record/markdown`

### Task 4: 实现 live 组真实集成测试

**Files:**
- Modify: `tests/test_cli_integration_commands.py`

- [ ] **Step 1: 写 `siyuan ls-notebooks` 真实集成测试**

```python
def test_siyuan_ls_notebooks_integration() -> None:
    result = subprocess.run(
        [*CLI_BASE_COMMAND, "siyuan", "ls-notebooks"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip()
```

- [ ] **Step 2: 写 `fetch --no-upload` 真实集成测试**

```python
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

    assert result.returncode == 0
    assert result.stdout.strip()
```

- [ ] **Step 3: 写 `gmail fetch` 真实集成测试**

```python
def test_gmail_fetch_integration() -> None:
    result = subprocess.run(
        [*CLI_BASE_COMMAND, "gmail", "fetch"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip()
```

- [ ] **Step 4: 写 `codex run` 真实集成测试**

```python
def test_codex_run_integration() -> None:
    assets = _load_assets()
    md_path = str(assets["codex"]["path"])

    result = subprocess.run(
        [*CLI_BASE_COMMAND, "codex", "run", md_path],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert ".codex.md" in result.stdout
    assert ".trace.log" in result.stdout
```

- [ ] **Step 5: 写 `bill normalize` 与 `bill run` 真实集成测试**

```python
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

    assert result.returncode == 0
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

    assert result.returncode == 0
    assert "归一化输出" in result.stdout
    assert "分析输出" in result.stdout
```

- [ ] **Step 6: 运行 live 组测试，确认真实服务与外网链路可用**

Run: `BEARTOOLS_INTEGRATION_GROUP=live uv run pytest tests/test_cli_integration_commands.py -v`
Expected: 已满足环境的命令 PASS；环境不满足的命令 SKIP，并输出明确原因

### Task 5: 实现 full/smoke 组装执行逻辑

**Files:**
- Modify: `tests/test_cli_integration_commands.py`

- [ ] **Step 1: 把 case 定义升级为可执行函数映射**

```python
CASE_RUNNERS: dict[str, Callable[[], None]] = {
    "doctor": test_doctor_command_integration,
    "record": test_record_getall_integration,
    "markdown": lambda: test_markdown_embed_images_integration(Path(tempfile.mkdtemp())),
    "bill-normalize": lambda: test_bill_normalize_integration(Path(tempfile.mkdtemp())),
    "bill-run": test_bill_run_integration,
    "siyuan": test_siyuan_ls_notebooks_integration,
    "fetch": test_fetch_integration_without_upload,
    "gmail": test_gmail_fetch_integration,
    "codex": test_codex_run_integration,
}
```

- [ ] **Step 2: 新增统一 smoke/full 入口测试**

```python
@pytest.mark.parametrize("case", _selected_cases(), ids=lambda case: case.name)
def test_selected_integration_case(case: IntegrationCase, tmp_path: Path) -> None:
    if case.name == "markdown":
        test_markdown_embed_images_integration(tmp_path)
        return
    if case.name == "bill-normalize":
        test_bill_normalize_integration(tmp_path)
        return
    CASE_RUNNERS[case.name]()
```

- [ ] **Step 3: 运行 smoke-core，确认随机抽样真实执行成功**

Run: `BEARTOOLS_INTEGRATION_GROUP=core BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=2 BEARTOOLS_SMOKE_SEED=42 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
Expected: PASS，稳定抽中同样的 core cases

- [ ] **Step 4: 运行 smoke-live，确认 live 抽样也可复现**

Run: `BEARTOOLS_INTEGRATION_GROUP=live BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=2 BEARTOOLS_SMOKE_SEED=42 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
Expected: PASS，稳定抽中同样的 live cases

### Task 6: 编写 skill 文档与 assets 说明

**Files:**
- Create: `skills/testing-cli-integrations/SKILL.md`
- Create: `skills/testing-cli-integrations/assets/README.md`
- Create: `skills/testing-cli-integrations/assets/fetch-urls.txt`

- [ ] **Step 1: 写 skill frontmatter 与 overview**

```markdown
---
name: testing-cli-integrations
description: Use when validating whether beartools top-level CLI commands still work through real integrations with local files, local services, network access, or real credentials after changes or before release.
---

# Testing CLI Integrations

## Overview

这是一组真实 CLI 集成测试，不是 `--help` 冒烟。核心原则是：每个顶层命令只选一条真实且尽量最小副作用的执行路径，默认优先跑 `core`，按需跑 `live`。
```

- [ ] **Step 2: 在 skill 中写清 full/core/live/smoke 执行命令**

```markdown
## Quick Reference

- `core` 全量：`BEARTOOLS_INTEGRATION_GROUP=core uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `live` 全量：`BEARTOOLS_INTEGRATION_GROUP=live uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `all` 全量：`BEARTOOLS_INTEGRATION_GROUP=all uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `core` smoke：`BEARTOOLS_INTEGRATION_GROUP=core BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=2 BEARTOOLS_SMOKE_SEED=42 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `live` smoke：`BEARTOOLS_INTEGRATION_GROUP=live BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=2 BEARTOOLS_SMOKE_SEED=42 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
```

- [ ] **Step 3: 在 skill 中写清真实资产与约束**

```markdown
## Assets

- bill 样例：见 `tests/assets/cli_integration_assets.yaml`
- codex prompt：见 `tests/assets/cli_integration_assets.yaml`
- fetch URL：见 `assets/fetch-urls.txt`

## Common Mistakes

- 把这套测试当成稳定纯单测：它依赖真实配置、真实服务和真实网络
- 在 `fetch` 集成测试里忘记加 `--no-upload`
- 没有提供 `seed` 就运行 smoke，导致失败不可复现
- 误把 `clear` 加回覆盖范围
- 把 `live` 环境错误硬断言成 FAIL，导致整组在不满足环境时完全不可用
```

- [ ] **Step 4: 写 assets README 与 fetch URL 清单**

`assets/README.md` 说明：

- 哪些资产直接放 skill 目录
- 哪些资产只在 `tests/assets/cli_integration_assets.yaml` 中做索引

`assets/fetch-urls.txt` 内容：

```text
https://mp.weixin.qq.com/s/Jac9uhA6zE1OsIYDGjr9-g
https://mp.weixin.qq.com/s/Iu9g7Ol8jLgtXu18QxMwOg
```

- [ ] **Step 5: 手工检查 skill frontmatter 与范围描述**

Run: 手工检查 `name`、`description`、`core/live`、`--no-upload`、`clear` 排除项都已写明
Expected: 文档满足 writing-skills 要求

### Task 7: 按 writing-skills 要求做基线与带 skill 验证

**Files:**
- Modify: `skills/testing-cli-integrations/SKILL.md`

- [ ] **Step 1: 记录无 skill 的基线失败模式**

```text
基线提示词示例：
“给 beartools 增加命令集成测试，覆盖所有命令，用真实配置，不要 mock。”
```

重点记录：

- 是否会忘记 `core/live` 分层
- 是否会把 `fetch` 默认上传保留
- 是否会遗漏真实资产索引
- 是否会把 `clear` 带回覆盖列表
- 是否会把 smoke 做成不可复现抽样

- [ ] **Step 2: 运行带 skill 的同类场景验证**

```text
带 skill 场景目标：
代理应明确使用 `tests/test_cli_integration_commands.py`，区分 `core/live`，指出 `fetch --no-upload`，并引用 bill/codex/fetch 资产。
```

Expected: 输出稳定落在正确范围，不再退化为 help-only 测试

- [ ] **Step 3: 如果验证发现新漏洞，回写 skill 文档**

优先补的漏洞：

- 把 `fetch` 写成默认上传
- 忽略 `tests/assets/cli_integration_assets.yaml`
- 把 `gmail/codex` 混进默认 core
- 把 smoke 写成不可复现随机

- [ ] **Step 4: 增加 rationalization table 与 red flags（如果需要）**

```markdown
| 借口 | 现实 |
|------|------|
| “真实集成就顺手让 fetch 上传吧” | 这会污染思源数据，不属于最小副作用验证。 |
| “反正 live 命令少，没必要分层” | 没有 core/live 分层，日常验证成本会迅速失控。 |
| “随机抽样不需要 seed” | 不可复现的 smoke 对排查回归帮助很小。 |
```

- [ ] **Step 5: 重新验证 skill，直到输出稳定符合设计**

Run: 再跑一轮同类提示词验证
Expected: 代理能稳定给出 `core/live`、资产路径和真实执行命令

### Task 8: 最终校验与交付说明

**Files:**
- Modify: `tests/test_cli_integration_commands.py`
- Modify: `skills/testing-cli-integrations/SKILL.md`

- [ ] **Step 1: 运行 core 全量最终校验**

Run: `BEARTOOLS_INTEGRATION_GROUP=core uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
Expected: PASS

- [ ] **Step 2: 运行 live 全量最终校验**

Run: `BEARTOOLS_INTEGRATION_GROUP=live uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
Expected: PASS

- [ ] **Step 3: 运行 smoke 模式最终校验**

Run: `BEARTOOLS_INTEGRATION_GROUP=all BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=3 BEARTOOLS_SMOKE_SEED=20260506 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
Expected: PASS

- [ ] **Step 4: 做计划自检**

检查项：

- 是否明确排除 `clear`
- 是否使用真实配置且无 mock
- 是否区分 `core/live`
- 是否固定 `fetch --no-upload`
- 是否引用 bill/codex/fetch 资产

- [ ] **Step 5: 准备交付说明**

交付时应说明：

- 新测试文件：`tests/test_cli_integration_commands.py`
- 资产索引：`tests/assets/cli_integration_assets.yaml`
- 新 skill：`skills/testing-cli-integrations/SKILL.md`
- `core/live/full/smoke` 运行方式
- `fetch` 为什么显式禁用上传
