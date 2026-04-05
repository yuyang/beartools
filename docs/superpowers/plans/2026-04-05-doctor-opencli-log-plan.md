# doctor opencli 输出截断与日志调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 doctor 中 opencli 检查在终端只展示头 10 行和尾 20 行，同时默认日志仅写文件且补充 AGENTS 规范。

**Architecture:** 保持 doctor 现有展示层不变，在 opencli 检查内部生成摘要文本并将完整输出写入日志文件。默认 logger 简单配置移除 console handler，只保留异步文件输出，并通过测试锁定摘要规则与日志行为。

**Tech Stack:** Python 3.13+, pytest, unittest.mock, logging, rich, uv

---

## 文件结构

- 修改：`src/beartools/commands/doctor/checks/opencli.py`
  - 负责执行 `opencli doctor`
  - 新增输出合并与摘要函数
  - 在检查内部记录完整日志
- 修改：`src/beartools/logger.py`
  - 调整默认简单日志配置，取消 console 输出
- 修改：`AGENTS.md`
  - 补充日志使用规范
- 新增：`tests/test_doctor_opencli_check.py`
  - 覆盖 opencli 输出摘要与完整日志行为
- 新增：`tests/test_logger.py`
  - 覆盖默认 logger 只写文件、不挂 console handler 的行为

### Task 1: 为 opencli 输出摘要行为补充失败测试

**Files:**
- Create: `tests/test_doctor_opencli_check.py`
- Modify: `src/beartools/commands/doctor/checks/opencli.py:17-155`

- [ ] **Step 1: 写出摘要函数的失败测试**

```python
from __future__ import annotations

import importlib


opencli_module = importlib.import_module("beartools.commands.doctor.checks.opencli")


def test_summarize_output_returns_original_text_when_line_count_not_exceed_limit() -> None:
    source = "\n".join([f"line-{index}" for index in range(1, 31)])

    result = opencli_module._summarize_output(source)

    assert result == source


def test_summarize_output_keeps_head_and_tail_when_line_count_exceeds_limit() -> None:
    source = "\n".join([f"line-{index}" for index in range(1, 41)])

    result = opencli_module._summarize_output(source)

    assert result == "\n".join(
        [
            *[f"line-{index}" for index in range(1, 11)],
            "...(省略 10 行)",
            *[f"line-{index}" for index in range(21, 41)],
        ]
    )
```

- [ ] **Step 2: 运行测试，确认因函数缺失而失败**

Run: `uv run pytest tests/test_doctor_opencli_check.py -xvs`
Expected: FAIL，报 `module 'beartools.commands.doctor.checks.opencli' has no attribute '_summarize_output'`

- [ ] **Step 3: 写最小实现让摘要测试通过**

在 `src/beartools/commands/doctor/checks/opencli.py` 中加入下面的辅助函数：

```python
def _summarize_output(output: str) -> str:
    """将输出摘要为头10行和尾20行。"""
    lines = output.splitlines()
    if len(lines) <= 30:
        return output

    omitted_count = len(lines) - 30
    summarized_lines = [
        *lines[:10],
        f"...(省略 {omitted_count} 行)",
        *lines[-20:],
    ]
    return "\n".join(summarized_lines)
```

- [ ] **Step 4: 重新运行测试，确认通过**

Run: `uv run pytest tests/test_doctor_opencli_check.py -xvs`
Expected: PASS，2 个测试全部通过

- [ ] **Step 5: 本任务提交**

```bash
git add tests/test_doctor_opencli_check.py src/beartools/commands/doctor/checks/opencli.py
git commit -m "ADD: 新增opencli输出摘要逻辑测试"
```

### Task 2: 用 TDD 实现 opencli 检查摘要输出与完整日志落盘

**Files:**
- Modify: `tests/test_doctor_opencli_check.py`
- Modify: `src/beartools/commands/doctor/checks/opencli.py:17-155`

- [ ] **Step 1: 写出 run() 行为的失败测试**

把下面测试追加到 `tests/test_doctor_opencli_check.py`：

```python
from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, patch


pytest = importlib.import_module("pytest")


@pytest.mark.asyncio
async def test_run_returns_summarized_detail_and_logs_full_output() -> None:
    source_lines = [f"line-{index}" for index in range(1, 41)]
    stdout = "\n".join(source_lines)

    with (
        patch("beartools.commands.doctor.checks.opencli.shutil.which", return_value="/usr/local/bin/opencli"),
        patch(
            "beartools.commands.doctor.checks.opencli.OpenCliCheck._run_command",
            new=AsyncMock(return_value=opencli_module.CommandResult(return_code=0, stdout=stdout, stderr="")),
        ),
        patch("beartools.commands.doctor.checks.opencli.get_logger") as mock_get_logger,
    ):
        mock_logger = mock_get_logger.return_value
        result = await opencli_module.OpenCliCheck().run()

    assert result.detail == "\n".join(
        [
            *[f"line-{index}" for index in range(1, 11)],
            "...(省略 10 行)",
            *[f"line-{index}" for index in range(21, 41)],
        ]
    )
    mock_logger.info.assert_called_once_with("opencli doctor 完整输出:\n%s", stdout)
```

- [ ] **Step 2: 运行测试，确认为预期失败**

Run: `uv run pytest tests/test_doctor_opencli_check.py::test_run_returns_summarized_detail_and_logs_full_output -xvs`
Expected: FAIL，`result.detail` 仍为完整文本，且 `get_logger` 未被调用

- [ ] **Step 3: 写最小实现让 run() 测试通过**

在 `src/beartools/commands/doctor/checks/opencli.py` 中做以下修改：

1. 增加导入：

```python
from beartools.logger import get_logger
```

2. 在模块级新增 logger：

```python
logger = get_logger(__name__)
```

3. 抽取输出合并函数：

```python
def _build_full_output(result: CommandResult) -> str:
    """拼接命令完整输出。"""
    full_output = ""
    if result.stdout.strip():
        full_output += f"STDOUT:\n{result.stdout}\n"
    if result.stderr.strip():
        full_output += f"STDERR:\n{result.stderr}"
    return full_output.strip()
```

4. 在 `run()` 的成功/失败分支前处理完整输出和摘要输出：

```python
full_output = _build_full_output(result)
summary_output = _summarize_output(full_output) if full_output else ""

if full_output:
    logger.info("opencli doctor 完整输出:\n%s", full_output)
```

5. 将所有 `detail=full_output or None` 改为：

```python
detail=summary_output or None
```
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `uv run pytest tests/test_doctor_opencli_check.py -xvs`
Expected: PASS，摘要函数测试与 run() 测试全部通过

- [ ] **Step 5: 本任务提交**

```bash
git add tests/test_doctor_opencli_check.py src/beartools/commands/doctor/checks/opencli.py
git commit -m "MOD: 调整opencli检查终端输出摘要"
```

### Task 3: 为默认日志仅写文件补充失败测试并实现

**Files:**
- Create: `tests/test_logger.py`
- Modify: `src/beartools/logger.py:48-115`

- [ ] **Step 1: 写出默认简单日志配置的失败测试**

创建 `tests/test_logger.py`：

```python
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from unittest.mock import patch


logger_module = importlib.import_module("beartools.logger")
config_module = importlib.import_module("beartools.config")


def test_setup_simple_config_only_registers_queue_handler_on_root_logger(tmp_path: Path) -> None:
    logger_module.shutdown_logging()
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    log_config = config_module.LogConfig(path=tmp_path / "beartools.log", level="INFO", config_file=None)

    logger_module._setup_simple_config(log_config)

    try:
        assert len(root_logger.handlers) == 1
        assert root_logger.handlers[0].__class__.__name__ == "QueueHandler"
        assert logger_module._queue_listener is not None
        listener_handlers = logger_module._queue_listener.handlers
        assert len(listener_handlers) == 1
        assert listener_handlers[0].__class__.__name__ == "TimedRotatingFileHandler"
    finally:
        logger_module.shutdown_logging()
```

- [ ] **Step 2: 运行测试，确认当前行为失败**

Run: `uv run pytest tests/test_logger.py -xvs`
Expected: FAIL，`listener_handlers` 当前包含 `StreamHandler` 和 `TimedRotatingFileHandler`

- [ ] **Step 3: 写最小实现让测试通过**

在 `src/beartools/logger.py` 中删除默认简单配置里的 console handler，并将监听器改为只监听文件处理器：

```python
# 创建文件处理器（每天切分一次，保留最近30天日志）
try:
    file_handler = TimedRotatingFileHandler(
        log_config.path,
        when="MIDNIGHT",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        delay=True,
    )
    file_handler.suffix = "%Y-%m-%d"
except PermissionError as e:
    raise RuntimeError(f"无法打开日志文件: {log_config.path}, 权限不足 - {e}") from e
except OSError as e:
    raise RuntimeError(f"打开日志文件失败: {log_config.path} - {e}") from e

file_handler.setFormatter(formatter)

queue_handler = QueueHandler(log_queue)
root_logger.addHandler(queue_handler)

_queue_listener = QueueListener(log_queue, file_handler)
_queue_listener.start()
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `uv run pytest tests/test_logger.py -xvs`
Expected: PASS，默认 listener 只包含文件处理器

- [ ] **Step 5: 本任务提交**

```bash
git add tests/test_logger.py src/beartools/logger.py
git commit -m "MOD: 默认日志仅输出到文件"
```

### Task 4: 更新 AGENTS 规范并完成回归验证

**Files:**
- Modify: `AGENTS.md`
- Modify: `tests/test_doctor_opencli_check.py`
- Modify: `tests/test_logger.py`

- [ ] **Step 1: 写出 AGENTS 规范补充**

在 `AGENTS.md` 的“代码质量检查”或“协作规则”后补充以下条目：

```md
## 日志与调试规范
- 默认不要把日志打印到 console。
- 需要排查问题时，优先查看 `log/` 目录下的日志文件。
```

- [ ] **Step 2: 运行本次相关测试，确认整体通过**

Run: `uv run pytest tests/test_doctor_opencli_check.py tests/test_logger.py -xvs`
Expected: PASS，全部测试通过

- [ ] **Step 3: 运行代码质量检查**

Run: `uv run ruff check src/beartools/commands/doctor/checks/opencli.py src/beartools/logger.py tests/test_doctor_opencli_check.py tests/test_logger.py AGENTS.md`
Expected: PASS，Python 文件无 lint 问题；如 `AGENTS.md` 被忽略属正常

- [ ] **Step 4: 运行格式化检查**

Run: `uv run ruff format src/beartools/commands/doctor/checks/opencli.py src/beartools/logger.py tests/test_doctor_opencli_check.py tests/test_logger.py --check`
Expected: PASS，所有 Python 文件格式正确

- [ ] **Step 5: 本任务提交**

```bash
git add AGENTS.md tests/test_doctor_opencli_check.py tests/test_logger.py src/beartools/commands/doctor/checks/opencli.py src/beartools/logger.py
git commit -m "MOD: 完善doctor日志与调试规范"
```

## 计划自检

- Spec coverage:
  - opencli 终端摘要输出：Task 1 + Task 2 覆盖
  - 完整输出写入日志文件：Task 2 覆盖
  - 默认日志不输出到 console：Task 3 覆盖
  - AGENTS.md 规范补充：Task 4 覆盖
- Placeholder scan: 无 TBD/TODO/“类似任务N”占位项
- Type consistency:
  - 摘要函数统一命名为 `_summarize_output`
  - 完整输出函数统一命名为 `_build_full_output`
  - 测试文件路径统一为 `tests/test_doctor_opencli_check.py` 与 `tests/test_logger.py`
