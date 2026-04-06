# doctor google_ping 科学上网检测改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `doctor` 中的 `google_ping` 从单点 TCP 探测改为 5 个 HTTPS 目标并发检测，按 3/5 阈值判断“科学上网检查”是否通过。

**Architecture:** 保留 `google_ping` 检查名与 `doctor.checks.google_ping` 配置入口，在配置层扩展 `targets` 与 `success_threshold`，在检查层使用 `aiohttp` 并发请求 5 个目标，并显式关闭环境代理继承。测试分为配置解析、sample 配置同步、检查结果汇总与错误分类四部分，按 TDD 逐步落地。

**Tech Stack:** Python 3.13+, aiohttp, asyncio, pytest, pytest-asyncio, dynaconf, uv

---

## 文件结构

- 修改：`src/beartools/config.py`
  - 扩展 `DoctorCheckConfig`，支持 `targets` 与 `success_threshold`
  - 扩展 `doctor.checks.*` 配置解析逻辑
- 修改：`config/beartools.yaml.sample`
  - 为 `google_ping` 增加默认 5 个目标与通过阈值
- 新增：`tests/test_doctor_google_ping_check.py`
  - 覆盖 `google_ping` 的多目标汇总、错误分类、顺序稳定性与并发调用
- 修改：`tests/test_config.py`
  - 覆盖 `google_ping` 新配置字段解析与 sample 配置一致性
- 修改：`src/beartools/commands/doctor/checks/google_ping.py`
  - 使用 `aiohttp` 实现 HTTPS 检查
  - 输出“科学上网检查通过/失败（x/5）”与逐项 detail

## 实施约束

- 所有新增注释、docstring 使用中文。
- 不读取 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`；请求必须显式 `trust_env=False`。
- “成功”定义为：只要拿到 HTTPS 响应即可，不限制 2xx/3xx。
- `detail` 输出顺序必须与 `targets` 配置顺序一致。
- 不新增新的 doctor 检查项。

### Task 1: 先用测试锁定 `google_ping` 新配置结构

**Files:**
- Modify: `tests/test_config.py`
- Modify: `src/beartools/config.py:42-55`
- Modify: `config/beartools.yaml.sample`

- [ ] **Step 1: 写出 `google_ping` 配置解析的失败测试**

把下面两个测试追加到 `tests/test_config.py` 的 `TestConfig` 类中：

```python
    def test_google_ping_extended_config_is_parsed(self) -> None:
        self._write_config(
            """
doctor:
  checks:
    google_ping:
      timeout: 4
      fail_on_error: true
      success_threshold: 3
      targets:
        - "https://www.google.com/generate_204"
        - "https://www.youtube.com/"
        - "https://www.facebook.com/"
        - "https://x.com/"
        - "https://www.instagram.com/"
"""
        )

        config = load_config()

        google_ping = config.doctor.checks["google_ping"]
        assert google_ping.timeout == 4
        assert google_ping.fail_on_error is True
        assert google_ping.success_threshold == 3
        assert google_ping.targets == [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
            "https://x.com/",
            "https://www.instagram.com/",
        ]

    def test_google_ping_sample_yaml_contains_extended_fields(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        google_ping = sample_data["doctor"]["checks"]["google_ping"]

        assert google_ping["timeout"] == 2
        assert google_ping["fail_on_error"] is True
        assert google_ping["success_threshold"] == 3
        assert google_ping["targets"] == [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
            "https://x.com/",
            "https://www.instagram.com/",
        ]
```

- [ ] **Step 2: 运行测试，确认因配置结构尚未扩展而失败**

Run: `uv run pytest tests/test_config.py::TestConfig::test_google_ping_extended_config_is_parsed tests/test_config.py::TestConfig::test_google_ping_sample_yaml_contains_extended_fields -xvs`
Expected: FAIL，报 `DoctorCheckConfig` 缺少 `success_threshold` 或 `targets`

- [ ] **Step 3: 写最小实现让配置测试通过**

在 `src/beartools/config.py` 中把 `DoctorCheckConfig` 改成：

```python
@dataclass
class DoctorCheckConfig:
    """健康检查单项配置"""

    timeout: int = 2
    fail_on_error: bool = True
    targets: list[str] = field(default_factory=list)
    success_threshold: int = 1
```

并把 `_convert_to_dataclass()` 中解析 `doctor.checks` 的部分改成：

```python
    merged_checks: dict[str, DoctorCheckConfig] = {}
    checks_dict_val = doctor_settings.get("checks", {})
    if isinstance(checks_dict_val, dict):
        for check_name, check_config in checks_dict_val.items():
            if isinstance(check_config, dict):
                normalized_check_config = _as_dict(check_config, f"doctor.checks.{check_name}")
                timeout_val = normalized_check_config.get("timeout", 2)
                timeout = int(timeout_val) if isinstance(timeout_val, (int, str, float)) else 2
                fail_on_error_val = normalized_check_config.get("fail_on_error", True)
                fail_on_error = bool(fail_on_error_val) if isinstance(fail_on_error_val, (bool, int, str)) else True

                targets_val = normalized_check_config.get("targets", [])
                if isinstance(targets_val, list):
                    targets = [str(item) for item in targets_val]
                else:
                    targets = []

                success_threshold_val = normalized_check_config.get("success_threshold", 1)
                if isinstance(success_threshold_val, bool):
                    success_threshold = 1
                elif isinstance(success_threshold_val, int):
                    success_threshold = success_threshold_val
                elif isinstance(success_threshold_val, float):
                    success_threshold = int(success_threshold_val)
                elif isinstance(success_threshold_val, str) and success_threshold_val.strip():
                    success_threshold = int(success_threshold_val)
                else:
                    success_threshold = 1

                merged_checks[str(check_name)] = DoctorCheckConfig(
                    timeout=timeout,
                    fail_on_error=fail_on_error,
                    targets=targets,
                    success_threshold=success_threshold,
                )
```

把 `config/beartools.yaml.sample` 中的 `doctor.checks.google_ping` 改成：

```yaml
    google_ping:
      # 单个目标的超时时间（秒），默认：2
      timeout: 2
      # 检查失败时是否终止运行，默认：true
      fail_on_error: true
      # 当至少 3 个目标返回 HTTPS 响应时视为通过
      success_threshold: 3
      # 用于判断科学上网能力的目标站点
      targets:
        - "https://www.google.com/generate_204"
        - "https://www.youtube.com/"
        - "https://www.facebook.com/"
        - "https://x.com/"
        - "https://www.instagram.com/"
```

- [ ] **Step 4: 重新运行测试，确认通过**

Run: `uv run pytest tests/test_config.py::TestConfig::test_google_ping_extended_config_is_parsed tests/test_config.py::TestConfig::test_google_ping_sample_yaml_contains_extended_fields -xvs`
Expected: PASS，2 个测试全部通过

- [ ] **Step 5: 本任务提交**

```bash
git add tests/test_config.py src/beartools/config.py config/beartools.yaml.sample
git commit -m "MOD: 扩展google_ping配置结构"
```

### Task 2: 先写 `google_ping` 汇总行为的失败测试

**Files:**
- Create: `tests/test_doctor_google_ping_check.py`
- Modify: `src/beartools/commands/doctor/checks/google_ping.py:1-99`

- [ ] **Step 1: 写出 3/5 成功与 2/5 失败的测试**

创建 `tests/test_doctor_google_ping_check.py`：

```python
from __future__ import annotations

import importlib
from types import SimpleNamespace

pytest = importlib.import_module("pytest")


def _load_module():
    return importlib.import_module("beartools.commands.doctor.checks.google_ping")


class TestGooglePingCheck:
    @pytest.mark.asyncio
    async def test_run_returns_success_when_threshold_is_met(self, monkeypatch) -> None:
        module = _load_module()
        targets = [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
            "https://x.com/",
            "https://www.instagram.com/",
        ]

        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(timeout=2, fail_on_error=True, targets=targets, success_threshold=3)
                    }
                )
            ),
        )

        responses = {
            targets[0]: module._TargetCheckResult(label="google", ok=True, summary="成功 204"),
            targets[1]: module._TargetCheckResult(label="youtube", ok=True, summary="成功 200"),
            targets[2]: module._TargetCheckResult(label="facebook", ok=True, summary="成功 200"),
            targets[3]: module._TargetCheckResult(label="x", ok=False, summary="超时"),
            targets[4]: module._TargetCheckResult(label="instagram", ok=False, summary="连接失败"),
        }

        async def fake_check_target(self, session, target, timeout):
            return responses[target]

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)

        result = await module.GooglePingCheck().run()

        assert result.status is module.CheckStatus.SUCCESS
        assert result.message == "科学上网检查通过（3/5）"
        assert result.detail == (
            "google: 成功 204\n"
            "youtube: 成功 200\n"
            "facebook: 成功 200\n"
            "x: 超时\n"
            "instagram: 连接失败"
        )

    @pytest.mark.asyncio
    async def test_run_returns_failure_when_threshold_is_not_met(self, monkeypatch) -> None:
        module = _load_module()
        targets = [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
            "https://x.com/",
            "https://www.instagram.com/",
        ]

        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(timeout=2, fail_on_error=True, targets=targets, success_threshold=3)
                    }
                )
            ),
        )

        responses = {
            targets[0]: module._TargetCheckResult(label="google", ok=True, summary="成功 204"),
            targets[1]: module._TargetCheckResult(label="youtube", ok=True, summary="成功 200"),
            targets[2]: module._TargetCheckResult(label="facebook", ok=False, summary="DNS 解析失败"),
            targets[3]: module._TargetCheckResult(label="x", ok=False, summary="超时"),
            targets[4]: module._TargetCheckResult(label="instagram", ok=False, summary="连接失败"),
        }

        async def fake_check_target(self, session, target, timeout):
            return responses[target]

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)

        result = await module.GooglePingCheck().run()

        assert result.status is module.CheckStatus.FAILURE
        assert result.message == "科学上网检查失败（2/5）"
        assert result.detail == (
            "google: 成功 204\n"
            "youtube: 成功 200\n"
            "facebook: DNS 解析失败\n"
            "x: 超时\n"
            "instagram: 连接失败"
        )
```

- [ ] **Step 2: 运行测试，确认因新模型与新文案尚不存在而失败**

Run: `uv run pytest tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_run_returns_success_when_threshold_is_met tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_run_returns_failure_when_threshold_is_not_met -xvs`
Expected: FAIL，报模块中没有 `_TargetCheckResult` 或 `GooglePingCheck._check_target`

- [ ] **Step 3: 写最小实现让汇总测试通过**

把 `src/beartools/commands/doctor/checks/google_ping.py` 改成下面结构：

```python
"""Google Ping 网络连通性检查。

通过多个 HTTPS 目标站点检测当前环境的科学上网可用性。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

import aiohttp

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.config import get_config

DEFAULT_TARGETS = [
    "https://www.google.com/generate_204",
    "https://www.youtube.com/",
    "https://www.facebook.com/",
    "https://x.com/",
    "https://www.instagram.com/",
]
DEFAULT_SUCCESS_THRESHOLD = 3


@dataclass(frozen=True)
class _TargetCheckResult:
    """单个目标检测结果。"""

    label: str
    ok: bool
    summary: str


def _label_for_target(target: str) -> str:
    """根据目标 URL 生成展示标签。"""
    if "google.com" in target:
        return "google"
    if "youtube.com" in target:
        return "youtube"
    if "facebook.com" in target:
        return "facebook"
    if "x.com" in target:
        return "x"
    if "instagram.com" in target:
        return "instagram"
    return target


@register_check
class GooglePingCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "google_ping"

    @property
    def description(self) -> str:
        return "检查科学上网所需的 HTTPS 连通性"

    async def _check_target(self, session: aiohttp.ClientSession, target: str, timeout: int) -> _TargetCheckResult:
        return _TargetCheckResult(label=_label_for_target(target), ok=False, summary=f"未实现: {timeout}")

    async def run(self) -> CheckResult:
        start_time = time.time()
        config = get_config()
        check_config = config.doctor.checks.get("google_ping")
        timeout = check_config.timeout if check_config else 2
        targets = check_config.targets if check_config and check_config.targets else list(DEFAULT_TARGETS)
        success_threshold = (
            check_config.success_threshold
            if check_config and check_config.success_threshold > 0
            else DEFAULT_SUCCESS_THRESHOLD
        )

        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout, trust_env=False) as session:
            results = await asyncio.gather(*(self._check_target(session, target, timeout) for target in targets))

        success_count = sum(1 for item in results if item.ok)
        duration = time.time() - start_time
        detail = "\n".join(f"{item.label}: {item.summary}" for item in results)

        if success_count >= success_threshold:
            return CheckResult(
                name=self.name,
                status=CheckStatus.SUCCESS,
                message=f"科学上网检查通过（{success_count}/{len(results)}）",
                duration=duration,
                detail=detail,
            )

        return CheckResult(
            name=self.name,
            status=CheckStatus.FAILURE,
            message=f"科学上网检查失败（{success_count}/{len(results)}）",
            duration=duration,
            detail=detail,
        )
```

- [ ] **Step 4: 重新运行测试，确认通过**

Run: `uv run pytest tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_run_returns_success_when_threshold_is_met tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_run_returns_failure_when_threshold_is_not_met -xvs`
Expected: PASS，2 个测试通过

- [ ] **Step 5: 本任务提交**

```bash
git add tests/test_doctor_google_ping_check.py src/beartools/commands/doctor/checks/google_ping.py
git commit -m "MOD: 改造google_ping为多目标汇总检查"
```

### Task 3: 用测试锁定错误分类、顺序稳定和并发调用

**Files:**
- Modify: `tests/test_doctor_google_ping_check.py`
- Modify: `src/beartools/commands/doctor/checks/google_ping.py:1-160`

- [ ] **Step 1: 追加错误分类与并发行为测试**

把下面测试追加到 `tests/test_doctor_google_ping_check.py`：

```python
    def test_label_for_target_returns_expected_short_name(self) -> None:
        module = _load_module()

        assert module._label_for_target("https://www.google.com/generate_204") == "google"
        assert module._label_for_target("https://www.youtube.com/") == "youtube"
        assert module._label_for_target("https://www.facebook.com/") == "facebook"
        assert module._label_for_target("https://x.com/") == "x"
        assert module._label_for_target("https://www.instagram.com/") == "instagram"

    @pytest.mark.asyncio
    async def test_check_target_classifies_timeout(self) -> None:
        module = _load_module()

        class FakeSession:
            def get(self, target: str, ssl: bool = True):
                raise asyncio.TimeoutError

        result = await module.GooglePingCheck()._check_target(FakeSession(), "https://www.youtube.com/", 2)

        assert result == module._TargetCheckResult(label="youtube", ok=False, summary="超时")

    @pytest.mark.asyncio
    async def test_check_target_classifies_dns_error(self) -> None:
        module = _load_module()

        class FakeSession:
            def get(self, target: str, ssl: bool = True):
                raise module.aiohttp.ClientConnectorDNSError(None, OSError("dns failed"))

        result = await module.GooglePingCheck()._check_target(FakeSession(), "https://www.facebook.com/", 2)

        assert result == module._TargetCheckResult(label="facebook", ok=False, summary="DNS 解析失败")

    @pytest.mark.asyncio
    async def test_check_target_classifies_connection_error(self) -> None:
        module = _load_module()

        class FakeSession:
            def get(self, target: str, ssl: bool = True):
                raise module.aiohttp.ClientConnectorError(None, OSError("connect failed"))

        result = await module.GooglePingCheck()._check_target(FakeSession(), "https://x.com/", 2)

        assert result == module._TargetCheckResult(label="x", ok=False, summary="连接失败")

    @pytest.mark.asyncio
    async def test_run_preserves_target_order_and_uses_concurrent_requests(self, monkeypatch) -> None:
        module = _load_module()
        targets = [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
        ]
        started: list[str] = []
        release = asyncio.Event()

        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(timeout=2, fail_on_error=True, targets=targets, success_threshold=2)
                    }
                )
            ),
        )

        async def fake_check_target(self, session, target, timeout):
            started.append(target)
            if len(started) == len(targets):
                release.set()
            await release.wait()
            return module._TargetCheckResult(label=module._label_for_target(target), ok=True, summary="成功 200")

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)

        result = await module.GooglePingCheck().run()

        assert started == targets
        assert result.detail == "google: 成功 200\nyoutube: 成功 200\nfacebook: 成功 200"
```

- [ ] **Step 2: 运行新增测试，确认因 `_check_target` 仍是占位实现而失败**

Run: `uv run pytest tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_check_target_classifies_timeout tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_check_target_classifies_dns_error tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_check_target_classifies_connection_error tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_run_preserves_target_order_and_uses_concurrent_requests -xvs`
Expected: FAIL，错误分类断言不匹配

- [ ] **Step 3: 写最小实现让错误分类测试通过**

把 `src/beartools/commands/doctor/checks/google_ping.py` 中的 `_check_target()` 改成：

```python
    async def _check_target(self, session: aiohttp.ClientSession, target: str, timeout: int) -> _TargetCheckResult:
        label = _label_for_target(target)

        try:
            async with session.get(target, ssl=True) as response:
                return _TargetCheckResult(label=label, ok=True, summary=f"成功 {response.status}")
        except asyncio.TimeoutError:
            return _TargetCheckResult(label=label, ok=False, summary="超时")
        except aiohttp.ClientConnectorDNSError:
            return _TargetCheckResult(label=label, ok=False, summary="DNS 解析失败")
        except aiohttp.ClientConnectorCertificateError:
            return _TargetCheckResult(label=label, ok=False, summary="HTTPS 请求失败")
        except aiohttp.ClientSSLError:
            return _TargetCheckResult(label=label, ok=False, summary="HTTPS 请求失败")
        except aiohttp.ClientConnectorError:
            return _TargetCheckResult(label=label, ok=False, summary="连接失败")
        except aiohttp.ClientError:
            return _TargetCheckResult(label=label, ok=False, summary="HTTPS 请求失败")
        except OSError:
            return _TargetCheckResult(label=label, ok=False, summary="连接失败")
```

- [ ] **Step 4: 运行全部 `google_ping` 测试，确认通过**

Run: `uv run pytest tests/test_doctor_google_ping_check.py -xvs`
Expected: PASS，全部测试通过

- [ ] **Step 5: 本任务提交**

```bash
git add tests/test_doctor_google_ping_check.py src/beartools/commands/doctor/checks/google_ping.py
git commit -m "ADD: 补充google_ping多目标检查测试"
```

### Task 4: 收尾默认值、文案和配置回归验证

**Files:**
- Modify: `src/beartools/commands/doctor/checks/google_ping.py`
- Modify: `tests/test_config.py`
- Modify: `config/beartools.yaml.sample`

- [ ] **Step 1: 补一条默认回退行为测试**

把下面测试追加到 `tests/test_doctor_google_ping_check.py`：

```python
    @pytest.mark.asyncio
    async def test_run_falls_back_to_default_targets_and_threshold(self, monkeypatch) -> None:
        module = _load_module()

        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(timeout=2, fail_on_error=True, targets=[], success_threshold=0)
                    }
                )
            ),
        )

        seen_targets: list[str] = []

        async def fake_check_target(self, session, target, timeout):
            seen_targets.append(target)
            return module._TargetCheckResult(label=module._label_for_target(target), ok=True, summary="成功 200")

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)

        result = await module.GooglePingCheck().run()

        assert seen_targets == module.DEFAULT_TARGETS
        assert result.message == "科学上网检查通过（5/5）"
```

- [ ] **Step 2: 运行新增测试，确认默认回退逻辑正确**

Run: `uv run pytest tests/test_doctor_google_ping_check.py::TestGooglePingCheck::test_run_falls_back_to_default_targets_and_threshold -xvs`
Expected: PASS

- [ ] **Step 3: 做最终代码整理**

确认 `src/beartools/commands/doctor/checks/google_ping.py` 最终包含以下关键实现：

```python
DEFAULT_TARGETS = [
    "https://www.google.com/generate_204",
    "https://www.youtube.com/",
    "https://www.facebook.com/",
    "https://x.com/",
    "https://www.instagram.com/",
]
DEFAULT_SUCCESS_THRESHOLD = 3
```

```python
    @property
    def description(self) -> str:
        return "检查科学上网所需的 HTTPS 连通性"
```

```python
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout, trust_env=False) as session:
            results = await asyncio.gather(*(self._check_target(session, target, timeout) for target in targets))
```

- [ ] **Step 4: 运行完整验证**

Run: `uv run pytest tests/test_doctor_google_ping_check.py tests/test_config.py -xvs`
Expected: PASS，所有相关测试通过

Run: `uv run ruff check src/beartools/commands/doctor/checks/google_ping.py src/beartools/config.py tests/test_doctor_google_ping_check.py tests/test_config.py`
Expected: PASS，无 lint 错误

Run: `uv run ruff format src/beartools/commands/doctor/checks/google_ping.py src/beartools/config.py tests/test_doctor_google_ping_check.py tests/test_config.py --check`
Expected: PASS，格式正确

- [ ] **Step 5: 本任务提交**

```bash
git add src/beartools/commands/doctor/checks/google_ping.py src/beartools/config.py tests/test_doctor_google_ping_check.py tests/test_config.py config/beartools.yaml.sample
git commit -m "MOD: 增强doctor科学上网检查能力"
```

## 计划自检

- Spec coverage:
  - 保留 `google_ping` 名称且不新增检查项：Task 2 + Task 4 覆盖
  - 5 个默认 HTTPS 目标：Task 1 + Task 4 覆盖
  - 3/5 阈值：Task 1 + Task 2 + Task 4 覆盖
  - 不读取代理环境变量：Task 2 + Task 4 覆盖（`trust_env=False`）
  - detail 输出逐项结果且顺序稳定：Task 2 + Task 3 覆盖
  - 错误分类：Task 3 覆盖
- Placeholder scan: 无 TBD/TODO/“类似 Task N” 之类占位项
- Type consistency:
  - 配置类型统一使用 `DoctorCheckConfig.targets` 与 `DoctorCheckConfig.success_threshold`
  - 检查结果模型统一使用 `_TargetCheckResult(label, ok, summary)`
  - 默认常量统一命名为 `DEFAULT_TARGETS` 与 `DEFAULT_SUCCESS_THRESHOLD`
